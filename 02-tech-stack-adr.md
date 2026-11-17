# AI Steward: tech stack decision records (ADR)

Written 2026-11-14 · Decision maker: the user · Status values: **Decided** (set by the user), **Proposed** (this document's recommendation, not yet confirmed by the user), **Deferred**

**Revised 2026-11-14.** Following the user's decision, the models changed to OpenAI (`gpt-6.1-terra` for the final run, `gpt-6-luna` for development) and the embedding to `text-embedding-3-large`. The first draft assumed Anthropic, which had not been chosen by comparing it with other providers. The question count was also corrected to the real count taken from fia.com.

**Revised 2026-11-16.** ADR-004: the search method is no longer fixed in advance as hybrid. The three candidates are compared on the dev questions and the better one is used. For past decisions the comparison was run and vector search was chosen (user decision); the numbers are in ADR-004.

**Revised 2026-11-15.** The screen became the product (AI Steward) and the method comparison moved to the README (ADR-007). The final question set is 100. Decisions are shown as page images instead of in a PDF viewer (ADR-010). Tool-based lookup (an agent) was taken out of scope (ADR-008). Model calls changed from direct OpenAI SDK calls to LangChain throughout (ADR-002).

**Change of direction, 2026-11-15.** The backbone of the project changed from "an experiment comparing three methods" to "a RAG product that searches past decisions" (user decision; ADR-004 and the system design document). Putting the rules in whole was demoted to an optional experiment, and "the final question set is 100" no longer applies. The previous version is in `archive/2026-11-15-three-way-comparison/`. Passages below that speak of "the three methods" (no documents, RAG, full documents) are records from before the change.

## Inputs

**A tally of 30 job postings** (10 Applied AI, 10 FDE, 10 AI Engineer; 2026-11-14; postings on Greenhouse, Lever and Ashby, so biased towards startups). The counts below were confirmed by recounting `postings.csv` this time.

| Category | Mentions |
|---|---|
| Concepts | Agents 27, evaluation 25, RAG 19, prompt engineering 14, MCP 12 |
| Languages | Python 25, TypeScript 13 |
| Frameworks | LangGraph 7, LangChain 3 (all "or a similar tool"), CrewAI 3, LlamaIndex 1 |
| Evaluation and observability tools | LangSmith 4, Langfuse 3, Braintrust 3, Arize/Phoenix 2, OpenTelemetry 2 |
| Model providers | Anthropic/Claude 5, OpenAI 4, open-source models 5 |
| Web and UI | React 5, FastAPI 3, Streamlit 1, Gradio 1 |
| Vector DBs | Weaviate 2, the rest (FAISS, Chroma, Qdrant, Pinecone, pgvector) 1 each |

How to read it: what the postings ask for is concepts more than tool names. 21 postings name no framework at all. So the criterion for choosing the stack was set as "is the measurement clean, and can we explain why we chose it", not "how many names does it include".

**Already decided**: Python is required. LangChain is wanted; no objection to LangGraph. TypeScript and cloud are out of scope. Three methods (no documents, RAG, full documents). FIA original text does not go in the repository.

---

## At a glance

| # | Decision | Choice | Status |
|---|---|---|---|
| 001 | Language and packaging | Python 3.12, uv, a lock file | Proposed |
| 002 | Model call layer | Every model call through LangChain `ChatOpenAI` | Decided |
| 003 | Models | Final `gpt-6.1-terra` + `gpt-6-luna`, development `gpt-6-luna` | Decided |
| 004 | RAG search | The search method is chosen by comparing BM25, vector and hybrid on dev. Past decisions: vector search (measured 2026-11-16). Rule articles: measured in step 3. Chroma, `text-embedding-3-large` | Targets decided; method for past decisions decided; method for rule articles open |
| 005 | Running the evaluation and storing results | Two layers: search evaluation and answer evaluation. Our own runner + JSONL, rule-based scoring. LangSmith for tracing during development | Proposed |
| 006 | Output format | Pydantic schema and structured output | Proposed |
| 007 | Product screen and reporting results | The product screen is one static page + FastAPI (local); evaluation results go in the README | Decided |
| 008 | Tool-based lookup | LangGraph + MCP server | Excluded (user decision, 2026-11-15) |
| 009 | How the data is distributed | Only labels, positions and hashes in the repository; each person downloads the documents | Decided |
| 010 | PDF parsing and display | pypdf for parsing, page images for display | Proposed |

---

## ADR-001: Language and packaging

**Status:** Proposed

**Context.** Python is settled. Someone who clones the repository must be able to build the same environment with a few commands.

**Decision.** Python 3.12, `uv` for dependency management and locking (`uv.lock`), a single `pyproject.toml`. Tests with pytest, linting and formatting with ruff, type checking with either mypy or pyright.

| Option | Pros | Cons |
|---|---|---|
| uv | Fast install and lock; runs with one line of `uv run`. Common in new projects since 2025 | One more install step if the reader does not know uv |
| pip + requirements.lock (hash-pinned) | The same approach as the current career repository | Needs a separate tool to generate the lock file |
| Poetry | 1 posting | Slower than uv, with nothing gained |

**Consequences.** The run instructions in the README take the form `uv sync`, then `uv run f1aisteward ...`. Only a standard `pyproject.toml` is used, so it also installs without uv through `pip install -e .`.

---

## ADR-002: Model call layer

**Status:** Decided (user decision, 2026-11-15)

**Context.** This project measures tokens, cost and response time per query. So the configurations being compared must share the same call path, and we need to know exactly where the cache breakpoint sits and how many tokens there are. The first recommendation was to make generation calls directly with the OpenAI SDK and use LangChain only for search. That gives two ways of calling a model. The user wants to use LangChain and LangSmith, and wants one way throughout instead of a mix.

**Decision.** Every model call goes through LangChain. Calls that produce an answer go through a single `ChatOpenAI` from `langchain-openai` (Responses API), embeddings use `OpenAIEmbeddings`, and search uses LangChain retrievers (ADR-004). The calling code lives in one place only (`llm/client.py`).

The three configurations of the answer evaluation (no search, rules only, rules + past decisions) differ only in the search results placed in the prompt and go through the same `ChatOpenAI` call. What the first recommendation was guarding against was each configuration taking a different path.

| Option | Cleanliness of measurement | Number of call paths | LangSmith | Notes |
|---|---|---|---|---|
| **LangChain throughout (`ChatOpenAI`)** | Medium. Usage arrives tidied once into `usage_metadata`. The cache breakpoint can be set [verified] | One | Automatic once the environment variables are set | Easy to swap providers |
| OpenAI SDK directly + LangChain for search only (first recommendation) | High. Usage and cache fields arrive as they are | Two | SDK calls have to be wrapped separately [Responses API support unverified] | New API features are available at once |
| LiteLLM | Medium | Two | Separate wiring | One more dependency |

**Trade-off.** Token and cache figures arrive in the form LangChain has tidied, not as the raw OpenAI response. There may be a lag before LangChain supports a new API feature. If caching does not take effect through LangChain, only the single file `llm/client.py` is switched back to direct SDK calls.

**To observe during implementation**

The items below that deal with the cache apply only to the optional experiment of putting the rules in whole (step 7 of the system design). The product's prompt holds only search results and is small, so it does not rely on the cache.

- The first check to make when running the optional experiment: send the same full-document call twice and see whether `cache_read` in the second response is above 0. The items below were confirmed from documentation, not by running them.
- Caching is on by default for supported models [verified: OpenAI documentation, 2026-11-15]. Models from GPT-5.6 on let you set the breakpoint yourself, and `langchain-openai` 1.3.5 and later supports this [verified: LangChain documentation, 2026-11-15]. Attach `"prompt_cache_breakpoint": {"mode": "explicit"}` to the last content block of the document block and set `prompt_cache_options={"mode": "explicit", "ttl": "30m"}`. The question goes after it. Putting a date or a run ID in the document block breaks the cache.
- Cache lifetime: the OpenAI documentation lists `"30m"` (default) and `"12h"`, and the LangChain documentation says only `"30m"` is supported. We use 30 minutes. A write costs 1.25 times the input price (30 minutes); a read costs 0.05 times on terra and 0.1 times on luna. The minimum length that gets cached is 1,024 tokens.
- Cache-hit tokens are in `response.usage_metadata.input_token_details.cache_read` and cache writes in `cache_creation` [verified: LangChain documentation]. If `cache_read` stays at 0 the cache is not taking effect, so the runner warns.
- The Responses API is used through `ChatOpenAI(use_responses_api=True)` [verified: LangChain documentation].
- Structured output is received with `llm.with_structured_output(Answer, include_raw=True)`. `include_raw` is needed to get the raw message carrying usage along with the parsed answer [from my memory; verify during implementation].
- Reasoning tokens are billed at the output rate. Set `reasoning.effort` explicitly and record it in the settings. Which field carries the reasoning token count in LangChain has not been confirmed.
- A truncated response (`max_output_tokens`) and a refusal are recorded as separate states, not as wrong answers. Where to read these two in a LangChain response has not been confirmed.
- Above 272,000 input tokens the price doubles. Measure the token count of the document bundle first and confirm it is under this line.
- LangSmith tracing is switched off for the full-document method and for runs that measure response time (ADR-005).
- Not confirmed: whether `temperature` is supported, and how to count input tokens before sending a request. Deterministic runs are not assumed; variance is measured by repeating some questions.

---

## ADR-003: Model choice

**Status:** Decided (user decision, 2026-11-14)

**Decision.** OpenAI models throughout.
- Development (writing code, tuning the prompt and search settings): `gpt-6-luna`
- Final run: `gpt-6.1-terra`. The same questions are also run once on `gpt-6-luna`, giving two rows in the table.
- `reasoning.effort` is set to one value on the development questions and fixed for both models.

**Context.** The answer to "which method is better" can depend on model price and model size. The first draft used Claude models, but they had been picked without a comparison; after comparing the prices of three providers the choice was changed to fit the budget.

**The chosen models** (USD per 1 million tokens; OpenAI pricing and model pages, checked 2026-11-14)

| | Input | Cache read | Output | Context limit | Training cutoff | OpenAI's description |
|---|---|---|---|---|---|---|
| gpt-6.1-terra | $1.00 | $0.05 | $5.00 | 1.05M | 2026-06-01 | A fast, efficient model. Visual reasoning, computer use, writing |
| gpt-6-luna | $0.10 | $0.01 | $0.50 | 1.05M | 2026-05-18 | For focused, high-volume work; the most efficient |

Above 272,000 input tokens, the price doubles for both models.

**Cost per question** [estimate: assumes 4,000 tokens of retrieved articles, 4,000 tokens for 5 past decisions, 1,500 tokens of output. All unmeasured]

| | No search | Rules only | Rules + past decisions | (Optional experiment) full rules, cache hit | (Optional experiment) full rules, no cache |
|---|---|---|---|---|---|
| gpt-6.1-terra | $0.008 | $0.012 | $0.016 | $0.016 | $0.16 |
| gpt-6-luna | $0.0008 | $0.0012 | $0.0016 | $0.0023 | $0.016 |

The full rules are assumed to be 150,000 tokens.

**Considered and not chosen**

| Option | Why not | To add it later |
|---|---|---|
| gpt-6.1-sol ($2 / $10) | Twice the cost of terra. OpenAI presents it as the model "for complex work", so it may suit this problem better | About $11 more with the same runner |
| Claude Sonnet 5.5 ($2 / $10, the same price as sol) | A second set of calling code would have to be written | About $11 more, plus one client implementation |
| Claude Opus 5.5 + Haiku 5.5 (first draft) | Expensive. Haiku 5.5 costs 5 times as much once the prompt exceeds 100,000 tokens, which is a disadvantage for the full-document method | – |
| Gemini 4 Argon | Prices double from 1 December. Caching is automatic only, which makes it hard to measure no-cache and cache-hit cost separately | – |
| gpt-6-luna only | Possible for about $2, but the conclusion would be limited to the cheapest model | – |

**Risks.**
- OpenAI does not present terra as a model for reasoning work such as interpreting rules. If all three methods sit at the floor on the development questions, switching to sol is reconsidered.
- terra's training cutoff is 2026-06-01. It may have memorised the decisions from the 5 events held before then (Australia, China, Japan, Miami, Canada), so the score of the no-documents method is reported separately for before and after the cutoff.
- Prices change. The price table is pinned in the repository with the date it was checked.

**Cost.** Estimated at about $8 from development through answer evaluation, about $10 with some margin (the optional experiment excluded). The breakdown by stage is in section 5 of the system design document.

---

## ADR-004: RAG search

**Status:** The search targets are decided (user decision, 2026-11-15). The search method for past decisions is decided (user decision, 2026-11-16, after the comparison below). The method for rule articles is open until it is measured in step 3

**Context.** RAG is the centre of this product (system design, section 1.3). There are two search targets. Past decisions number 359 in the 2026 season and grow with each event. Rule articles are expected to number 1,000 to 3,000 [estimate]. Both are sizes that need no vector DB server. Decisions use fixed expressions such as "left the track" and "pit lane speeding", so keyword search may well be strong. The user wants to use LangChain.

**Decision.**
- Search targets: two collections, `decisions` (past decisions) and `rules` (rule articles).
- Chunking: one decision is one chunk, one article is one chunk. An article gets its heading path in front (for example `Section B > 1 General > 1.8 Driving > 1.8.6`).
- The text searched for a decision is "what happened": the session and the Fact, joined as one line. The Reason field is not included; separating its findings of fact from its conclusion has not been tried. The article and the penalty are kept in metadata only.
- Search method: not fixed in advance. Three candidates are built and compared on the dev questions (system design, section 4.3): BM25 alone, vector alone, and hybrid (the two rankings combined by reciprocal rank fusion, RRF). The best one is used; when they are level, the simplest. They are built with LangChain's BM25 retriever, the Chroma vector retriever and `EnsembleRetriever`, and all three stay in the code so the comparison can be repeated.
- For past decisions the comparison gave vector search (below). For rule articles it is made in step 3.
- Storage: Chroma, local files.
- Metadata filter: `decisions` searches only events earlier than the question's event; `rules` searches only the issue in force on the question's event date.
- Embedding: OpenAI `text-embedding-3-large` ($0.13 per 1 million tokens), called through `OpenAIEmbeddings` from `langchain-openai`.
- The number retrieved starts at 5 decisions and 8 articles and is settled on dev.
- No reranker. If the search evaluation is low, it is reconsidered then.

| Option | Pros | Cons |
|---|---|---|
| **LangChain retrievers + Chroma + OpenAI embedding** | Matches what the user wants. The same library and the same API key as the model calls. The index is a local file, so it rarely has to be rebuilt. Metadata filters handle the date and the issue | In LangChain 1.x some retrievers may have moved package, so the import paths have to be checked during implementation [unverified] |
| Our own implementation (rank_bm25 + numpy) | Minimal dependencies, under 100 lines | LangChain would not be used. LangSmith tracing would have to be attached separately |
| LlamaIndex | Chunking that is aware of document structure | Overlaps with LangChain |
| Hosted vector DB (Pinecone, Weaviate and others) | Suits large scale | Needs an account and a key, and makes reproduction harder. Nothing gained at this size. Original text would be stored externally |
| Local open models (the sentence-transformers family) | Free; the version can be pinned | Needs a heavy library installed |

**What the comparison showed for past decisions (dev events Monaco to Hungarian, 5 results, `text-embedding-3-large`, 2026-11-16).** hit@5 is the share of questions with at least one decision under the same article among the 5 results; precision@5 is the share of the 5 results that are under the same article.

| Method | Reworded questions (94): hit@5 | precision@5 | Stewards' wording (87): hit@5 | precision@5 |
|---|---|---|---|---|
| BM25 alone | 0.702 (66 questions) | 0.357 | 0.770 (67) | 0.480 |
| Vector alone | 0.745 (70) | 0.479 | 0.770 (67) | 0.487 |
| Hybrid, equal weights, 20 candidates | 0.734 (69) | 0.447 | 0.747 (65) | 0.499 |
| Hybrid, best of 18 settings (vector weight 0.9, 50 candidates) | 0.755 (71) | 0.474 | 0.759 (66) | 0.485 |

- When the question uses other words than the stewards', vector search is clearly ahead of BM25 on precision@5 (0.479 against 0.357).
- Hybrid was tried with vector weights 0.3, 0.5, 0.6, 0.7, 0.8 and 0.9 and with 10, 20 and 50 candidates from each search. On the reworded questions no setting beat vector alone: the best one has one more question in hit@5 and a slightly lower precision@5, and hybrid improved only as the vector weight rose, that is, as it became vector search. On the stewards' wording hybrid has a slightly higher precision@5 (at most 0.499 against 0.487) and one or two fewer questions in hit@5.
- So vector search is used for past decisions: the same or slightly better numbers with one index and no weights to choose. Decided by the user on 2026-11-16. BM25 and hybrid remain available (`--method`) and remain in the reported comparison.
- What this does not show. There are 94 questions, so one question is 1.1 points and no confidence interval was computed; "level" is the honest reading of the small gaps. The reworded questions were written by one model in one sitting and stay close to the originals (they keep car and turn numbers). The test events were not used. Rule articles are a different kind of text and may come out differently.

**Trade-off.** If the provider retires an API embedding model, the index cannot be rebuilt identically. Which embedding model is better on these documents has not been measured either. On the other hand, the search evaluation (system design, section 4.3) runs without model calls, so it is easy to swap embedding models and settings and compare them.

**On the choice of vector DB.** Chroma was chosen for two reasons: metadata filters and local file storage. Switching to FAISS would give the same results.

---

## ADR-005: Running the evaluation and storing results

**Status:** Proposed

**Context.** The earlier session kept LangSmith as a candidate evaluation tool. Evaluation is a concept 25 postings mention, and the tools split into LangSmith 4, Langfuse 3, Braintrust 3.

**Decision.** The evaluation has two layers (system design, section 4). The search evaluation calls no model and measures "does it find similar decisions"; the answer evaluation compares the answers of three configurations (no search, rules only, rules + past decisions) with the stewards' decisions. We build the runner and the scorer ourselves and store results as JSONL files. These are the only source of truth. LangSmith is used for looking at call details during development. Every model call goes through LangChain (ADR-002), so tracing attaches once the environment variables are set.

| Option | Pros | Cons |
|---|---|---|
| **Our own runner + JSONL** | Reproducible without an account. Failure classification, repeats, cache records and resuming are controlled as we like. Evaluation design skill is visible in code | The experiment comparison view has to be built ourselves (the report page does that job) |
| LangSmith as the source of truth | The experiment comparison view and tracing come for free. 4 postings | The free plan allows 5,000 traces a month [verified: several third-party pricing summaries. The official pricing page was not checked directly]. The final run is about 1,000 calls across both models, which is within the limit, but repeated runs during development could push it over. With the full-document method each trace carries the full rule text and is large. Whoever clones the repository has to create an account |
| Langfuse (can be self-hosted) | No limit on call counts. 3 postings | A server has to be run locally |
| Inspect, promptfoo, DeepEval, Ragas | A ready-made evaluation framework | Not in the postings. Scoring is by deterministic rules, so little is gained from a framework |

**Trade-off.** The LangSmith name shows less in the README. In exchange, "why it was not used as the source of truth" (trace size, reproducibility, the free limit) goes into the README as one paragraph, and we consider this stronger evidence than simply having used the tool. One screenshot of the LangSmith screen from the dev stage can be included.

**Caution.** Sending traces of the full-document method to LangSmith uploads the full text of the FIA rules to a third-party service. It is not public distribution, but the optional feature is off by default, and even when it is on it applies only to the RAG and no-documents methods.

---

## ADR-006: Output format

**Status:** Proposed

**Decision.** The answer is defined as a Pydantic model (`Answer`) and received through LangChain's structured output (`llm.with_structured_output(Answer)`). Articles are received as a list of free strings and normalisation happens on the scoring side.

| Option | Pros | Cons |
|---|---|---|
| **Structured output + normalisation on the scoring side** | Parsing almost never fails. However the model writes article notation, it is scored by the same rules | The normaliser becomes the weak point of the scoring (covered by table-driven tests) |
| Force article IDs with an enum | No normalisation needed | It amounts to giving the model the list of candidate answers, which is a hint for the no-documents method. An enum of several thousand articles may hit the schema limits |
| Free text + an LLM judge | Evaluates the quality of the reasoning too | Adds judge variance and cost, and blurs the differences between methods |

**Note.** Receiving the citation's position within the article text is not done in this scope. The schema size limits (number of properties, enum size) could not be confirmed from the OpenAI documentation.

---

## ADR-007: Product screen and reporting results

**Status:** Decided (user decision, 2026-11-15)

**Context.** At first one screen held everything: the comparison table for the three methods, the chart, the reasons for wrong answers and the per-incident comparison (`mockup-v2.html`). Even its author found it hard to read what was being compared, and we judged it would be harder still for a recruiter to understand in 30 seconds.

**Decision.**
- The screen is one thing, the product **AI Steward**. Enter an incident and it answers with the article, the expected penalty and similar past incidents; for a real incident, the stewards' actual decision and the original document follow the answer. The mockup is `mockup-v4.html`.
- The evaluation results (what search added) go in the README as tables. The draft is `README-draft.md`.
- The implementation is a single HTML page (no build step, plain JS) and FastAPI. FastAPI serves the question text, the answers and the page images of decisions locally, and sends real call results to the screen.

| Option | Pros | Cons |
|---|---|---|
| **Product screen + comparison in the README** | The screen is understood in 5 seconds. The comparison sits where engineers read (the README). It tells the story "we built a product and chose the engine by experiment" | No screen for exploring the comparison results by clicking |
| One comparison dashboard screen (v2) | The experiment results are all in one place | Too many comparisons on one screen to be readable |
| The comparison in a slide PDF | Ready to use in a presentation | People who land on the repository rarely open a PDF. Make it when an interview presentation comes up |

The screen technology is unchanged from the first decision.

| Option | Pros | Cons |
|---|---|---|
| **Static HTML + FastAPI** | The screen can be built as designed. The mockup becomes the frontend almost as it is. FastAPI is in 3 postings | More code than Streamlit |
| Streamlit, Gradio | Fastest to get working | Custom layout is hard and it ends up looking like the default widgets. 1 posting each |
| React + TypeScript | React 5 and TypeScript 13 in the postings | Decided to be out of scope. Adds a build step |

**Consequences.** No public page (GitHub Pages) is made. Because of the FIA document terms the product runs locally only, and the README carries screenshots and the results tables. The README screenshots include the stewards' decision and the image of the original document (user decision, 2026-11-15). That image shows the FIA and F1 logos and the text of one decision. The first recommendation was to capture only as far as the answer and the comparison table.

---

## ADR-008: Tool-based lookup (LangGraph + MCP)

**Status:** Excluded (user decision, 2026-11-15). Neither the product nor the three-method comparison needs it, so it is not built. What follows is the record of the review.

**Context.** The postings tally has agents at 27, MCP at 12 and LangGraph at 7. The current three methods have no place for these three. We agree with the earlier session's judgment (the only place LangGraph does real work is tool-based lookup). Putting LangGraph into any of the three methods would be decoration.

**The design, if it were added.**
- MCP server (Python, local stdio): two tools. `search_rules(query, issue)` calls the retriever from ADR-004 as it is, and `get_article(id, issue)` returns the article text and the IDs of its parent and child articles.
- LangGraph graph: lookup → draft answer → citation verification (were the article IDs used in the answer actually looked up) → look up again on failure, at most N times. Tokens and time are recorded at each step.
- It enters the runner through the same `Method` interface and becomes the fourth column of the results table. The error classification gains "did not look up" and "step limit exceeded".

**Cost.** 3 to 5 days to implement [estimate]. Each question takes several calls, so run cost and latency go up, but that is what would be measured.

**What does not have to be decided now.** Whether to document the MCP server so that other clients such as Claude Desktop can use it too.

---

## ADR-009: How the data is distributed

**Status:** Decided

**Decision.** The repository holds only the download script, the document URLs, the labels (article IDs, penalty type and size) and the hashes. Each person downloads the PDFs and the original text on their own machine.

**Grounds.** FIA website terms 3.4 (copyright in the regulations and the ISC), 3.5 (no reproduction or distribution without written consent), 3.7 (no embedding in other sites or applications), 3.9 (championship information and data). We stay within what 3.6 (personal, non-commercial viewing; short quotations with the source given) and 3.8 (direct links tolerated) allow.

**Details added this time.**
- The question text (the session and the Fact) is original text too, so it does not go in the repository. Each machine rebuilds it by parsing the downloaded PDFs. Nothing is masked, because the Reason field is not part of the question. The reworded questions in `data/questions/paraphrased.jsonl` were written for this project and are in the repository.
- Of the run records, the model's written reasoning and the text of retrieved articles stay local. The repository's `results.jsonl` holds only the structured answers and the figures.
- The public report page shows only aggregate figures and article IDs.

**Consequences.** A hosted public demo cannot be made. If the FIA takes a document down or edits it, reproduction breaks, and the hash check reports it. Asking the FIA for permission remains an open option.

---

## ADR-010: PDF parsing and display

**Status:** Proposed

**Parsing**

| Option | Pros | Cons |
|---|---|---|
| **pypdf** | All 31 decisions succeeded in the pilot [verified]. Pure Python, BSD licence | Tables and multi-column layout in the rule documents are unverified |
| pdfplumber | Good table extraction | Not needed for decisions |
| PyMuPDF | Fastest, with accurate layout information | AGPL licence [from my memory; needs checking before implementation]. Affects the licence choice for a public repository |

pypdf for decisions. The rule documents are also tried with pypdf first, and where the article tree breaks, pdfplumber is used for that document only.

**Display**

| Option | Pros | Cons |
|---|---|---|
| **Render page images and show them with `<img>`** | Fits the document size exactly. Looks the same in every browser. The blank part at the bottom of a page can be trimmed | Text cannot be selected (covered by the fields transcribed as text alongside and a link that opens the PDF). One library is needed to render the images |
| Browser PDF viewer (`<object>`) | No extra library. Text selection and zoom | The box height does not match the document, leaving blank space underneath [verified: reproduced in the mockup]. It looks different in each browser and is not drawn in headless captures |

The fetch stage renders the PDFs as page images into `.cache/pages`. The candidate library is pypdfium2 [licence and installation to be checked before implementation]. The images in the mockup were made with the PDF facilities of macOS, and that approach works on macOS only.

---

## Dependencies

```
pydantic             schemas
pypdf                PDF text
pypdfium2            page images of decisions (candidate; check before implementation)
httpx                downloading documents
langchain-core, langchain-community, langchain-chroma, langchain-openai
                     model calls, structured output, embeddings, retrievers
                     (the exact package set is checked during implementation)
rank-bm25, chromadb
numpy, scipy         bootstrap, McNemar
fastapi, uvicorn     local demo
typer                CLI
pytest, ruff         development
langsmith            optional
```

## What this stack shows from the postings

| Posting item | In this project |
|---|---|
| Python (25) | All of it |
| Evaluation (25) | Scorer, statistics, error classification, runner |
| RAG (19) | Article-level chunking, vector search chosen over BM25 and hybrid by measurement, search metrics |
| Prompt engineering (14) | Shared instructions, cache structure |
| Agents (27) | None (taken out of scope, ADR-008) |
| MCP (12) | None (taken out of scope, ADR-008) |
| LangGraph (7) | None (taken out of scope, ADR-008) |
| LangChain (3), LangSmith (4), FastAPI (3) | Model calls and retrievers, optional tracing, local server |
| TypeScript (13), cloud (AWS 9 and others) | Out of scope |

Agents, MCP and LangGraph are items this project does not show.
