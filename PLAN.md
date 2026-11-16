# AI Steward: implementation plan

## Status

| Step | What | State |
|---|---|---|
| Prep | Apply the Codex review to the README draft and the design | Done 2026-11-15 |
| 0 | Project skeleton and `fetch` | Done 2026-11-15 |
| 1 | Parse decisions and build labels | Next |
| 2 | Search over past decisions | |
| 3 | Parse the rules and search them | |
| 4 | Generate answers and check citations | |
| 5 | Evaluate answers | |
| 6 | Product screen and final README | |
| 7 | Optional: compare with the whole rulebook in the prompt | |
| 8 | Optional: photo input | |

Nothing is committed yet. The git repository exists with one branch, `main`.

`01-system-design.md`, `02-tech-stack-adr.md` and `03-ui-ux-design.md` were rewritten in English on 2026-11-15. `01` and `02` were translated as they were. `03` was cut down to the current screen (`mockup-v4.html`); the critique of the first mockup and the record of the v2 comparison screen were removed.

## Found along the way

Things earlier steps learned from the real data. Read these before writing a parser.

**Step 0**

- **Titles are typed by hand and are not uniform.** One 2026 Dutch Grand Prix title reads `Infringement- Car 55` with no space before the dash. The first filter missed it and counted 358 decisions instead of 359. `manifest.parse_title` now tolerates missing spaces, and a test covers it. Expect the same kind of irregularity inside the PDFs.
- **Decisions can be published days after the race.** A Canadian Grand Prix decision came out four days later. An event's date is therefore the day its final race classification was published, not the day of its latest document (`manifest._race_day`).
- **fia.com shows Central European time.** Races in the Americas land on the next calendar day. The date is only used to put events in order, so this is harmless for now. It would matter if a rule issue changed on exactly that day.
- **Counts.** 20 events, 1,469 documents, 488 decision-like titles, 129 lap-time deletion lists, 359 decisions kept. Per event: 6 (Japanese) to 34 (Canadian).

## Context

**What we are building.** A local web app. You describe a Formula 1 incident in text; it searches stewards' decisions from earlier race weekends, names the rule in question and says what penalty usually follows. For a real incident it shows the stewards' actual decision under the answer.

**Why this shape.** The user's goals are (1) to implement RAG and understand all of it, and (2) a good portfolio piece. The rulebook fits in a prompt, so retrieval is not needed for it. Stewards' decisions keep growing and are the best evidence for a penalty, so retrieval over them is the centre of the product.

**Decided.** Python 3.12 and uv. Every model call and all search go through LangChain. OpenAI models: `gpt-6-luna` while building, `gpt-6.1-terra` for final numbers. Chroma. LangSmith for tracing during development. FastAPI and one static HTML page. CLI and package name `f1aisteward`. No agent (LangGraph). No FIA text in the repository, except that the README demo GIF shows one decision.

**Where things are.**

| File | What it is |
|---|---|
| `01-system-design.md` | Architecture and evaluation rules |
| `02-tech-stack-adr.md` | Tool decisions and why |
| `03-ui-ux-design.md` | Screen design |
| `README-draft.md` | README for the public repository, numbers still TBD |
| `mockup-v4.html` | Product screen mockup (local, not in git) |
| `mockup-readme.html` | How the README will look on GitHub (local, not in git) |
| `archive/` | The design before 2026-11-15 (local, not in git) |

## How we work

Claude writes the code. The user must understand all of it. **One step at a time**, and each step follows this order:

1. Explain what this step builds and why, with a diagram.
2. Write the code. Explain a new concept the first time it appears. Install a library in the step that first needs it.
3. Give the commands the user runs and the output to expect.
4. Ask one or two questions an interviewer might ask, to check understanding.
5. Move on when the user says so. Update "Status" and "Found along the way" in this file first.

Commit only when the user asks.

## Layout

```
pyproject.toml  .gitignore  .env.example
data/manifest/events.yaml          events, dates, decision links and sha256      (exists)
data/manifest/regulations.yaml     rule documents, issue, effective date, link, sha256
data/labels/decisions.jsonl        decision id, article ids, penalty, kind, split (no FIA text)
scripts/make_events_manifest.py    builds events.yaml from a saved fia.com listing (exists)
src/f1aisteward/
  cli.py            fetch (exists) / build / search / ask / serve / eval
  config.py         paths, settings (exists); later model names and price table
  manifest.py       title filter, read and write the manifest (exists)
  fetch.py          download PDFs, check hashes (exists)
  parse/decisions.py  decision PDF -> its eight fields
  parse/labels.py     normalise articles, structure penalties, classify kind
  parse/rules.py      rules PDF -> list of articles
  index.py          two Chroma collections and BM25
  search.py         hybrid search (RRF), date and issue filters
  llm/client.py     the one place ChatOpenAI is called; records tokens and cost
  answer.py         prompt, Answer schema, citation check, outcome counts
  eval/retrieval.py search evaluation
  eval/answers.py   answer evaluation runner (three configurations)
  eval/score.py     scoring rules
  eval/report.py    results/summary.json and the README tables
  app/server.py     FastAPI
  app/static/index.html
tests/              test_manifest.py, test_fetch.py (exist)
docs/demo.gif       recorded in step 6
.cache/  runs/      local only, not in git
```

## Steps

### Step 0: project skeleton and fetch (done)

- **Built**: `pyproject.toml`, `.gitignore`, `config.py`, `manifest.py`, `fetch.py`, `cli.py`, `scripts/make_events_manifest.py`, `data/manifest/events.yaml`, 13 tests.
- **Works**: `uv run f1aisteward fetch --event sao-paulo` downloads that event's decisions into `.cache/pdf/sao-paulo/`. A second run downloads nothing. A file whose hash contradicts the manifest is not saved.
- **Not done here**: fetching the rule documents. That is part of step 3.

### Step 1: parse decisions and build labels

- **Build**: `parse/decisions.py`, `parse/labels.py`, tests, CLI `build --decisions`.
- **How**: extract text with `pypdf`, then cut it at the field names (No / Driver, Competitor, Time, Session, Fact, Infringement, Decision, Reason). Infringement becomes article ids such as `ISC-L:IV.2.d` and `F1-B:8.2.2`. Decision becomes `{type, value, unit}`. Tests use decision text we write ourselves, never FIA text.
- **Learn**: getting text out of a PDF, regular expressions, why one notation matters, unit tests.
- **Check**: `uv run f1aisteward build --decisions` prints parsed and failed counts and counts by kind. Compare three decisions with their PDFs by eye.
- **Done when**: every 2026 decision has been parsed and the failure count is known. `pytest` passes.
- **Decide here**: whether the Fact field alone works as the question. In the two documents read so far (São Paulo 79 and 43) Fact was one sentence saying which car did what where, or a list of parts.

### Step 2: search over past decisions (the retrieval half of RAG)

- **Build**: `index.py`, `search.py`, `eval/retrieval.py`, CLI `search`.
- **How**: one decision is one chunk. Embed only the "what happened" part and store it in the Chroma collection `decisions`; article, penalty and date go in metadata. Combine LangChain's BM25 retriever and vector retriever with RRF. Search only events earlier than the question's event.
- **Learn**: embeddings, a vector database, keyword search against meaning search, hybrid search, metadata filters, measuring search with numbers.
- **Check**: `uv run f1aisteward search "car 16 made contact with car 30 at turn 12" --event sao-paulo` returns five similar past decisions. `uv run f1aisteward eval --retrieval` compares hit@5 and precision@5 for BM25 only, vector only and hybrid. That comparison goes into the README.
- **Done when**: search numbers exist, a test proves no decision from the same event is ever retrieved, and the dev and test events are fixed.
- **Needs**: the user puts `OPENAI_API_KEY` in `.env`. For LangSmith the user also prepares an account and key.

### Step 3: parse the rules and search them

- **Build**: `parse/rules.py`, `regulations.yaml`, the Chroma collection `rules`, fetching of rule documents.
- **How**: one article is one chunk with its heading path in front. Search only the issue in force on the question's event date.
- **Learn**: chunking that follows document structure, handling a document with several issues.
- **Check**: `uv run f1aisteward search "..." --rules` returns eight articles. The search evaluation gains article recall@8 and the number of questions whose article is outside the included documents.
- **Done when**: recall@8 exists.
- **Risk**: extracting articles from the rules PDFs has never been tried. The product works on decision search alone, so if this stalls, cut down to the Sporting Regulations and move on.
- **Decide first**: which rule documents to include.

### Step 4: generate answers and check citations

- **Build**: `llm/client.py`, `answer.py`, CLI `ask`.
- **How**: the prompt is instructions, then retrieved articles, then retrieved past decisions, then the question. `ChatOpenAI` structured output returns `Answer` (articles, penalty type, value and unit, reason, ids of the decisions relied on). Code then checks that every cited article and decision id was actually retrieved. Counts such as "5 of 8 got 10 seconds" are computed in code, never written by the model.
- **Learn**: building a prompt, structured output, checking grounding, tokens and cost, reading a call in LangSmith.
- **Check**: `uv run f1aisteward ask "..." --event sao-paulo` prints the answer, the outcome counts, the time and the cost.
- **Done when**: three real incidents give well-formed answers and the citation check works.
- **Verify while building**: `langchain-openai` is 1.3.5 or later; `with_structured_output(..., include_raw=True)` returns token usage; which field carries reasoning tokens.

### Step 5: evaluate answers

- **Build**: `eval/score.py`, `eval/answers.py`, `eval/report.py`.
- **How**: decisions from the test events are the questions. Each is answered in three configurations: no search, rules only, rules and past decisions. Scoring is rule-based only. Report citation precision next to rule hits. Timeouts and truncated answers are not scored as wrong, and their count per configuration is reported beside the results. Differences between configurations carry bootstrap confidence intervals. A run can be resumed.
- **Learn**: ablation, rule-based scoring, baselines, confidence intervals, answer leakage.
- **Check**: `uv run f1aisteward eval --answers --model gpt-6-luna` first, on the cheap model, then `gpt-6.1-terra`.
- **Done when**: the checks pass (gold labels score 100%, search switched off equals the no-search score, no question retrieves itself, no article number in question text), `results/summary.json` exists and the README's TBD cells are filled.
- **Cost**: about $6, estimated from token counts that have not been measured. Measure real token counts on ten dev questions first and tell the user the recalculated cost before the full run.

### Step 6: product screen and final README

- **Build**: `app/server.py`, `app/static/index.html`, page images of decisions, `docs/demo.gif`, `README.md`.
- **How**: turn `mockup-v4.html` into the frontend, including "Similar past incidents". Render page images with `pypdfium2`; the trimming and stacking approach is in `scratch/render_pages/stack.py`. Record the demo GIF by driving the real app in a browser. It includes the stewards' decision and the FIA document image (user decision, 2026-11-15).
- **Learn**: how an API server and a page talk to each other, running it locally.
- **Check**: `uv run f1aisteward serve`, then in the browser pick an incident and see the answer, the similar incidents and the stewards' decision.
- **Done when**: a real incident and a typed one both work. `README-draft.md` becomes `README.md`. Whether Mermaid and the GIF render on GitHub can only be checked after pushing.

### Step 7 (optional): the whole rulebook in the prompt

Replace rule search with the full rule text and measure accuracy and cost. Decide after step 6.

### Step 8 (optional): photo input

Let the user attach a photo to an incident. Decide after step 6.

- **How**: send photo and text to the model and get back one or two sentences of "what happened". Show that text and let the user edit it. Search with it. Search and answering stay text-based.
- **Limits**: one still image rarely shows who was ahead. Decisions have no photos, so this cannot be scored. Broadcast frames are copyrighted and do not go in the repository or the README.
- **Verify while building**: that the model accepts images through LangChain, and how many tokens one image costs.

## Not in this plan

Creating the GitHub repository and pushing. Do it when the user asks.

## Reuse

| File | Use |
|---|---|
| `scratch/season_2026.json` | Titles and links for all 20 events. Source of `events.yaml` |
| `documents/doc_*.pdf` (9 files) | São Paulo decisions used for the mockup. The same files are now in `.cache/pdf/sao-paulo/` |
| `scratch/render_pages/stack.py` | Trimming page images and stacking them into one |
| `mockup-v4.html` | Structure, copy and colour tokens for the screen |
| `mockup-readme.html` | Reference for how the README should look on GitHub |
| `01-system-design.md` sections 3 and 4 | How each part behaves, and the evaluation rules |

`scratch/render_pages/render.swift` runs on macOS only and is not used.

## What the user does

- Put `OPENAI_API_KEY` in `.env` before step 2. Claude does not handle keys.
- Prepare a LangSmith account and key before step 2, if using it.
- Run each step's commands and confirm the result.

## Open decisions

| Decision | When | Suggestion |
|---|---|---|
| Is the Fact field enough as the question | End of step 1 | Decide after reading the real text |
| Which events are dev and which are test | Step 2 | Test on later events, all after 2026-06-01 |
| Which rule documents to include | Before step 3 | Sporting Regulations, ISC, Appendix L and H. Sporting Regulations only if parsing stalls |
| Also run the final evaluation on `gpt-6-luna` | Step 5 | Yes, it costs about $1 |
| Code licence | Before pushing to GitHub | The user decides |

## Verification

- Every step: `uv run pytest -q`, plus that step's "Check" commands and expected output.
- Search: the search numbers, and the "never retrieves its own event" test run over every question.
- Answers: all four checks in step 5 must pass before any number goes into the README.
- Screen: after `uv run f1aisteward serve`, click through a real incident where the outcome differs (São Paulo 79), one fixed by the rules (São Paulo 43) and a typed incident.
- No FIA text in git: `git status` must show `.cache/`, `documents/` and `mockup-*` as untracked and ignored.
