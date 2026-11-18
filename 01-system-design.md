# AI Steward: system design

Written 2026-11-14 · Fully revised 2026-11-15 · Status: draft

**Revised 2026-11-15.** The backbone of the project changed from "an experiment comparing three methods" to "a RAG product that searches past decisions" (user decision). The previous version is in `archive/2026-11-15-three-way-comparison/`. Decided the same day: no agent (LangGraph + MCP), every model call goes through LangChain, the CLI is named `f1aisteward`. The evaluation additions that came out of Codex's (`gpt-6.1-sol`) review of the README (citation precision, a comparison of search methods, failure counts, the number of out-of-scope questions) are in sections 3.7 and 4.

**Revised 2026-11-16.** Section 3.5: the search method is chosen by comparing BM25, vector and hybrid on the dev questions instead of being fixed as hybrid. For past decisions the comparison was run and vector search was chosen (user decision). The numbers are in section 3.5 and ADR-004.

**Revised 2026-11-17.** Brought in line with implementation steps 1 to 3. Sections 3.2, 3.4, 4.2, 5.1 and 6: what parsing the real decisions and rules showed. Section 3.5: the search numbers after the label fix of step 3; rule articles use vector search plus the articles cited by the past decisions found (user decision). Section 8: what is decided now.

Markers: **[verified]** is a fact checked directly, **[estimate]** is a value that has not been measured or an assumption, **[decision needed]** is something the user has to decide.

---

## 1. What we are building

### 1.1 The product

**AI Steward** takes a written description of an incident in an F1 race and answers three things.

1. Which rule is in question (the article)
2. What penalty usually follows (the expected penalty)
3. How the stewards actually decided similar past incidents (a list of past decisions and their distribution)

If the incident really happened, the stewards' actual decision and the original document are shown under the answer.

### 1.2 Goals

- **Implement RAG ourselves and understand all of it.** Claude writes the code, and the user must be able to explain every part.
- **Make a good portfolio piece.** A good product comes before covering the words in job postings. Tools that are not needed are left out.

### 1.3 Why search past decisions

RAG is the technique for when there are too many documents to put in the prompt whole.

- **The rulebook fits whole.** The four rule books in force on one date are about 210,000 tokens [verified: tiktoken `cl100k_base` count of the parsed articles, 2026-11-17] and the model's limit is 1.05 million. With the rules alone as the target, RAG is not needed, and in the previous design RAG could lose the comparison and drop out of the product.
- **Past decisions keep growing.** The 2026 season alone has 359 [verified] and each event adds about 18. Several seasons together do not fit whole. Putting all of them in every question is also expensive.
- **The penalty cannot be known from the rules alone.** Whether it is 5 seconds or 10 is at the stewards' discretion. How similar incidents were decided in the past is the best evidence.

So in this product RAG is the centre, not one option among several.

### 1.4 Out of scope

An agent (LangGraph, MCP), a production service, cloud deployment, TypeScript, user accounts, a hosted demo (local only, because of the FIA terms).

---

## 2. The whole picture

### 2.1 Two stages: preparing ahead and answering a question

```
[Prepare ahead: once, and again after each new event]

 fia.com ──fetch──▶ PDF (.cache/pdf)
                      │
        ┌─────────────┴──────────────┐
   parse decisions              parse rules
   1 decision = 1 chunk         1 article = 1 chunk
        │                            │
   embedding                     embedding
        │                            │
   Chroma: decisions            Chroma: rules
   (BM25 is built in memory, only for the comparison, section 3.5)


[Answer a question: for every question]

 incident description + event
      │
      ├──▶ search decisions ──▶ 5 similar past decisions   (earlier events only)
      └──▶ search rules     ──▶ 8 relevant articles        (only the issues in force at that event)
                                + the articles the 5 decisions cite
                 │
                 ▼
      Model (LangChain ChatOpenAI): reads only what was retrieved and writes the answer
                 │
                 ▼
      Check in code: were the cited articles and decisions actually retrieved?
                 │
                 ▼
      Answer: article · expected penalty · reason · similar incidents and their distribution
```

### 2.2 Two things to search

| | Past decisions (`decisions`) | Rule articles (`rules`) |
|---|---|---|
| Question it answers | How did the stewards deal with similar incidents | Which rule is it, and what does it say |
| One chunk | 1 decision | 1 article |
| Count | 342 parsed of the 359 in the 2026 season [verified], still growing | 3,630 in 11 issues; 1,147 to 1,356 in force on one event's date [verified] |
| Filter | Only events earlier than the question's event | Only the issues in force on the question's event date |
| Without it | There is no product | The article text cannot be shown. Article numbers also come from past decisions, and the articles they cite are added to rule search (section 3.5) |

### 2.3 Design principles

1. **Answers rest on the retrieved documents.** The model reads only the search results and answers from them. Code checks that the articles and decisions the answer cites were actually in the search results.
2. **No looking into the future.** When solving an incident from an event, only decisions from earlier events are searched. Other decisions from the same event are excluded too. This keeps the gold answer from leaking in evaluation, and it matches real use.
3. **Code counts the numbers.** A distribution such as "5 of 8 similar incidents got 10 seconds" is not written by the model. Code computes it from the labels of the retrieved decisions.
4. **Original text does not go in the repository.** Because of the FIA terms (section 2.4).
5. **Results must be recomputable from the records.** Every number in the README is computed from the run record files.

### 2.4 Storage

| Location | Contents | In the repository? |
|---|---|---|
| `data/manifest/regulations.yaml` | Rule document ID, title, issue number, effective date, fia.com URL, sha256 | Yes |
| `data/manifest/events.yaml` | Events, dates, URLs of the decision listings | Yes |
| `data/labels/decisions.jsonl` | Decision ID, document URL and sha256, gold article IDs, penalty type and size, split (dev/test) | Yes |
| `.cache/pdf`, `.cache/text` | Downloaded PDFs and extracted text | Local only |
| `.cache/index` | Chroma collections `decisions` and `rules` (BM25 is built in memory when needed) | Local only |
| `.cache/pages` | Page images of decisions for the screen | Local only |
| `runs/<run_id>/results.jsonl` | Structured answers, retrieved document IDs, tokens, cost, time | Yes (no original text) |
| `runs/<run_id>/transcripts/` | Full prompts and the model's written reasons | Local only |
| `results/summary.json` | Aggregate figures | Yes |

Because of FIA website terms 3.4 to 3.9 [verified], PDFs, rule text and decision text do not go in the repository. The repository holds only "where to get it" and "a hash to check it arrived intact", and each person downloads the documents on their own machine with `fetch`. The indexes contain original text too, so they stay local. If the FIA edits a document, its hash changes; in that case nothing is overwritten and a warning is raised.

---

## 3. Components

### 3.1 Collection (fetch)

- Downloads the PDFs listed by URL in the manifest. It waits between requests, and files already downloaded are checked by sha256 and skipped.
- The User-Agent carries no personal information.
- Downloaded decisions are also rendered as page images into `.cache/pages` (for the screen, section 3.8).

### 3.2 Parsing decisions

- Extract text with `pypdf` and cut the body at the positions of the field names (No / Driver, Competitor, Time, Session, Fact, Infringement, Decision, Reason). Over the whole 2026 season: 342 parsed (320 forms about one car, 22 cover pages with a table of cars), 17 left out, 0 failed [verified: `build --decisions`, 2026-11-15].
- Documents that are not about an incident are left out and counted: 13 answers to a team's request, 2 Technical Delegate's reports, 1 list of deleted lap times under an ordinary title, 1 ruling on the running of the event. Their titles look like decisions, so only the text tells them apart.
- Labels are built from the fields.
  - **Article**: the citation in the Infringement field, normalised to an ID. Examples: `F1-B:1.8.6`, `ISC-L:IV.2.d`
  - **Penalty**: the Decision field as `{type, value, unit}`. The type is one of `no_further_action, warning, reprimand, fine, time_penalty, grid_drop, pit_lane_start, drive_through, stop_go, disqualification, other`
  - **Kind**: judgment incident / procedural or technical breach / component allowance exceeded / pit lane speeding
- Parsing failures are not thrown away; their count is reported. "0 failed" means every required field was found, not that every label is right: five decisions were compared with their page images, and then a random sample of 30 (section 4.1), with no label wrong.

### 3.3 The decisions index

- **Chunk**: one decision is one chunk. Decisions are short, so there is no reason to split further.
- **Text that is searched**: the session and the Fact, joined as one line ("<session>. <Fact>"; the Fact alone for the four decisions with no session). The question is built the same way, so like is compared with like. The Reason field is not included: it mixes the findings of fact with the conclusion, and separating the two has not been tried.
- **Metadata**: event, date, session, article IDs, penalty, kind, document URL. The date filters to "earlier events only", and the article and penalty are used to count distributions.
- If article numbers and penalties are mixed into the searched text, search turns into finding "the same number". The article and the penalty are kept only in metadata. Nothing has to be filtered out of the text: over the 2026 season no Fact names a penalty and two name an article (British 83, Mexico City 57). Those two stay in the index as they are and are left out of the evaluation questions. **[verified: counted over the 342 parsed decisions, 2026-11-16]**

### 3.4 Parsing and indexing the rules

- Documents covered (user decision, 2026-11-16): the Sporting Regulations (Section B), the ISC body, ISC Appendix L and Appendix H. Of the decisions with an article, 98 of 99 dev and 158 of 160 test cite at least one article in these four; Section B alone would be 72 and 101. Section C is left out (7 decisions cite it). The Driving Standards Guidelines are not cited as an article by any decision and are not included.
- Eleven issues were in force at some point of the season (`data/manifest/regulations.yaml`): Section B issues 5 to 9, two each of the ISC, Appendix L and Appendix H. An issue is in force from the date the document gives itself until the next issue of the same book, and only the issues in force on the question's event date are searched.
- Text is read with `pdfplumber`. The ISC and its appendices print French on the left and English on the right; each page is cropped at the empty band between the columns, found from the words' positions.
- One article is one chunk, with its heading path in front. Example: `ARTICLE B1: ORGANISATION OF A COMPETITION > B1.8 Driving > F1-B:1.8.7`. Each article carries `{key, id, book, issue, headings, text}`. 3,630 articles in all. Points such as a) to e) stay inside their article, so a citation of `ISC-L:IV.2.d` is found in the article `ISC-L:IV.2`.
- Every article that the 342 decisions cite from the four books is in the issue in force on its decision's date [verified: `eval --retrieval` counts the ones that are not; 0].

### 3.5 Search

The search method is not fixed in advance. Three candidates are built, compared on the dev questions (section 4.3), and the best one is used. When they are level, the simplest is used.

| | What it finds | Where it is strong |
|---|---|---|
| BM25 (keyword) | Documents containing the same words | Fixed expressions such as "pit lane" or "Turn 4" |
| Vector (embedding) | Documents with similar meaning | The same situation described in different words |
| Hybrid | Both of the above | The two rankings are combined with RRF (Reciprocal Rank Fusion: turn the rank in each list into a score and add them up) |

**Past decisions: vector search** (user decision, 2026-11-16). Measured on the dev events (Monaco to Hungarian), 5 results **[verified: `eval --retrieval` and a throwaway sweep of the hybrid settings, rerun 2026-11-17 after the label fix of step 3]**:

| Method | Reworded questions (94): hit@5 | precision@5 | Stewards' wording (87): hit@5 | precision@5 |
|---|---|---|---|---|
| BM25 alone | 0.713 (67 questions) | 0.360 | 0.782 (68) | 0.490 |
| Vector alone | 0.755 (71) | 0.483 | 0.782 (68) | 0.499 |
| Hybrid, equal weights, 20 candidates | 0.745 (70) | 0.451 | 0.759 (66) | 0.508 |
| Hybrid, best of 18 settings (vector weight 0.9, 50 candidates) | 0.766 (72) | 0.479 | 0.782 (68) | 0.499 |

Vector is clearly ahead of BM25 when the question is worded differently from the decision. Hybrid was tried at 18 settings (vector weight 0.3 to 0.9; 10, 20 or 50 candidates). On the reworded questions none beat vector alone: the best has one more question in hit@5 and a lower precision@5. On the stewards' wording the best setting equals vector alone, and the others are slightly higher on precision@5 (at most 0.508 against 0.499) and one or two questions lower on hit@5. No confidence interval was computed. BM25 and hybrid stay in the code and in the reported comparison. The full reading and its limits are in ADR-004.

**Rule articles: vector search, plus the articles cited by the past decisions found** (user decisions, 2026-11-17). Recall is the share of the articles the stewards cited that are among the retrieved articles, averaged over questions; an article counts as found when a retrieved article holds it (`ISC-L:IV.2` holds `ISC-L:IV.2.d`). Dev events **[verified: `eval --retrieval`, 2026-11-17; the 14-article row is from a throwaway script]**:

| Method | Articles per question | Reworded (94 questions citing 113 articles): recall | Stewards' wording (87 citing 104): recall |
|---|---|---|---|
| BM25 alone | 8 | 0.518 | 0.607 |
| Vector alone | 8 | 0.644 | 0.699 |
| Hybrid, equal weights, 20 candidates | 8 | 0.635 | 0.734 |
| Vector alone, more articles (a control) | 14 | 0.702 | 0.762 |
| **Vector + the articles the 5 decisions found cite** | 9.7 and 9.6 on average, at most 15 | **0.924** | **0.933** |

The best possible recall is 0.989 on both sets: one citation is of Section C, which is not included.

- Search alone missed mostly two general articles. Appendix L IV.2 (overtaking, car control, track limits, causing a collision) was found for 1 of 13 questions and ISC 12.2.1 (failure to follow instructions) for 0 of 12. The places went to text F1 does not use, such as Appendix L chapter V (offroad circuits) and Appendix H 2.10 (safety car procedures for championships without regulations of their own).
- Every past decision names the articles it was decided under. The articles cited by the 5 decisions that decision search found are looked up in the issues in force on the question's date and added after the 8 found by search, without repeats. Returning more articles from search alone does not do the same (the control row).
- Hybrid against vector for rules: three questions ahead on one question set, one behind on the other. Vector was chosen, as for decisions. No fusion weights were tried for rules.
- The added articles inherit the mistakes of decision search: when none of the 5 decisions is right, what they cite is noise in the prompt. Answer evaluation (section 4.4) shows whether that costs anything.

- Implemented with LangChain retrievers; storage is Chroma (local files) and the embedding is `text-embedding-3-large` (ADR-004).
- The model is given 5 decisions and 8 articles plus the articles those decisions cite (9.6 on average on dev).
- The distribution on the screen ("5 of 8 got 10 seconds") is counted over the decisions, among a wider top 20, that have the same article as the answer. **[estimate: 20 is a provisional value and is settled on dev]**
- No reranker (a step that re-sorts the search results with a model). If the search evaluation (section 4.3) is low, it is reconsidered then.

### 3.6 Generating the answer

- Model calls go through a single LangChain `ChatOpenAI` (ADR-002). The calling code lives in one place only, `llm/client.py`.
- Prompt layout: instructions → retrieved articles → retrieved past decisions (facts, article, penalty) → question.
- The answer comes back in a fixed format (Pydantic, structured output).

```
Answer {
  articles:        [article ID]       # 1 or more
  penalty_type:    enum
  penalty_value:   number | null
  penalty_unit:    "s" | "places" | "EUR" | null
  rationale:       string (3 sentences at most)
  precedents_used: [decision ID]      # past decisions used as grounds
}
```

### 3.7 Citation check

After the answer arrives, code checks it.

- Is each article in `articles` among the retrieved articles or the articles of the retrieved decisions?
- Is each decision in `precedents_used` among the retrieved decisions?

On a mismatch the answer is flagged and recorded, and on the screen that citation is removed from the list of grounds. There is no loop that asks again.

This check only looks at whether the cited IDs were in the search results. It catches invented citations, but it does not check whether the written reason actually follows from those grounds.

### 3.8 Product screen

FastAPI serves it locally and the screen is a single static HTML page (ADR-007, `03-ui-ux-design.md`).

1. Write the incident as text, or pick a real past incident. Choosing the event fixes "only decisions before it" and "the rules in force then".
2. The answer appears: expected penalty, article, reason, similar past incidents (list and distribution), the articles relied on.
3. For a real incident, the stewards' actual decision follows under the answer. The original document is shown as page images.

---

## 4. Evaluation

Whether the product answers correctly is looked at in two layers. The gold answer is the stewards' decision, written by people, and all scoring is rule-based. No model grades another model.

### 4.1 Questions

- One decision is one question. The question is that decision's session and Fact field. The gold answer is the labels from section 3.2. Decisions of one event that share the same Fact (one per car in the same incident) are one question whose gold answer is all their articles. `car_table` decisions are left out: their Fact only points at a table.
- A second question set asks the same incidents in other words (`data/questions/paraphrased.jsonl`, one per `single_car` decision, written for this project), to measure search on wording a user would write.
- Questions and gold answers come out of parsing automatically, so nobody writes them by hand. Instead, 30 questions are sampled and their labels are checked against the original text. **[verified, 2026-11-17]** 30 decisions drawn at random by kind in proportion to the season; article ids, penalty, kind, session and Fact compared with the rendered pages: 0 wrong. Zero in 30 bounds the error rate at about 10% (one-sided 95%), and no more. The decisions and the conventions met are listed in PLAN.md, step 1.
- Every question text is checked with regular expressions for leftover article numbers or penalty values.

### 4.2 Split by time

The events are put in date order and divided.

| Range | Events | Use |
|---|---|---|
| Before 2026-06-01 | Australian to Canadian (5 events, 83 parsed decisions) | Search corpus only, never a question |
| Dev, 2026-06-01 to 2026-07-31 | Monaco to Hungarian (6 events, 99) | Questions used to tune search settings and the prompt |
| Test, from 2026-08-01 | Dutch to São Paulo (9 events, 160) | Questions that produce the reported numbers. Not used for tuning |

For any question, the search corpus is the decisions from events earlier than its event, whatever their range. Both boundaries are the user's decision (2026-11-16) and are set in `config.py`.

The training cutoff of `gpt-6.1-terra` is 2026-06-01 [verified: ADR-003]. No question comes from an event before that date, so the model cannot answer correctly because it memorised the decision. The cut between dev and test is the summer break. With about 160 test questions, a score near 0.7 has a 95% interval of about ±7 points.

### 4.3 Search evaluation (no model calls)

This looks at "does it find similar incidents properly".

| Metric | Meaning |
|---|---|
| Decision hit@k | Is at least one of the k retrieved decisions under the same article as the gold answer |
| Decision precision@k | The share of the k retrieved decisions that are under the same article |
| Article recall | The share of the gold articles held by one of the retrieved articles, averaged over questions. Reported for search alone (k = 8) and with the articles cited by the decisions found added, with the average number of articles beside it |
| Out-of-scope questions | The number of questions whose gold article is in none of the included rule documents. They are not removed from the questions; the count is reported separately |

Recall, not hit or precision, for the rules: the gold answer is the one to three articles the stewards cited, and the answer needs each of them. Hit would score a question that found one of three cited articles the same as a perfect search. Decisions are the other way round: the number of right earlier decisions runs from 0 to 26 per question, so their recall would measure how common an article is, and five good decisions are enough.

- The same questions are run through three search methods (BM25 only, vector only, hybrid) and reported side by side. This is to show with numbers which method is actually better; the product uses the one the dev numbers favour (section 3.5).

- It uses embeddings only, so it is nearly free and finishes in seconds. Settings such as what goes into a chunk, the weight between BM25 and vector, and k are compared here.
- "Same article" is an approximation of "similar incident". The same article can cover different situations, and a different article can still be a useful reference.

### 4.4 Answer evaluation

The same questions are solved in three configurations, to see what search adds.

| Configuration | What the model receives |
|---|---|
| No search | The question only. It answers from memory. The baseline |
| Rules only | The retrieved articles |
| Rules + past decisions | The retrieved articles and past decisions. The configuration the product uses |

The three configurations differ only in the search results placed in the prompt; the instructions, answer format, model and calling code are the same.

### 4.5 Scoring rules

| Metric | Definition |
|---|---|
| Article hit | At least one of the answer's articles matches a gold article at the article-number level. `8.2.2` and `8.2.2.a` count as a match |
| Citation precision | The share of the articles the answer cites that are gold articles. Catches answers that list many articles to raise the hit rate |
| Penalty type match | Same type |
| Penalty size match | Same type, and the same value and unit |
| Both right | Article hit and penalty size match |

- Penalties are reported separately for "computed from the rules" (component allowance exceeded, pit lane speeding) and "discretionary".
- Numbers are given per kind. The overall average is driven by the share of easy repeated questions (component allowance exceeded and the like).
- Differences between configurations are paired on the same questions and carry bootstrap confidence intervals. With few questions, a small difference is written down as "not distinguishable".
- Timeouts, 429s and truncated responses are not counted as wrong answers, and their count per configuration is reported alongside the results table. If failures were simply dropped, a configuration that fails on the hard questions would look better.
- The score measures agreement with the article and penalty in the stewards' document. For a discretionary penalty a different answer is not necessarily a wrong one, and the quality of the written reason is not measured.

The normaliser that turns article notation into one ID (for example "Appendix L, Chapter IV, Article 2 d)" → `ISC-L:IV.2.d`) is the weak point of the scoring. It gets table-driven unit tests.

### 4.6 Checking the evaluation itself

| Check | How |
|---|---|
| Gold in, 100% out | Feed the gold labels in as answers and run them through the scorer |
| Empty answer and most common value | Report the scores of an empty answer and of an answer that always gives the most common article |
| Never retrieves itself | For every question, check that no decision from the same event as that decision is in the search results |
| Switching search off lowers the score | With the search results emptied, is the score the same as "no search" |
| Answer leakage | Check every question text with regular expressions for article numbers or penalty values |
| Truncation | How many responses hit `max_output_tokens` |

### 4.7 Code tests

| Target | Example |
|---|---|
| Decision parser | Extract the 8 fields from decision text we wrote ourselves (only the field structure is the same) |
| Article normalisation | `"Article B8.2.2a (read with B8.2.3)"` → `[F1-B:8.2.2.a, F1-B:8.2.3]`, 40 or more notation variants |
| Penalty structuring | `"5 second time penalty. 2 penalty points"` → `{time_penalty, 5, s}` |
| Scorer | Parent and child articles match; a wrong but plausible answer scores lower |
| Date filter | No decision later than the question's event is retrieved |
| Cost calculation | The value computed from token counts and the price table equals the hand calculation |

FIA documents cannot go in the repository, so the automated tests run on made-up text only. Tests that need the real documents are marked `local_corpus` and run locally only. The automated tests never call the API.

### 4.8 Limits

- One sport, one season, 359 decisions.
- A penalty set by discretion cannot be predicted from text alone. Past decisions only narrow the range.
- The question is one line of Fact, so it is shorter and more formulaic than the description a real user would write.

---

## 5. Scale and cost

### 5.1 Document counts

The 2026 season document listings on fia.com were downloaded per event and counted by title [verified: `scratch/season_2026.json`, recounted on 2026-11-15].

| Item | Count |
|---|---|
| Events | 20 |
| All published documents | 1,469 |
| Stewards' decision documents (title starts with Infringement, Decision or Offence) | 488 |
| Lap-time deletion lists (not used) | 129 |
| **Decisions (the search corpus and the question candidates)** | **359** |

By kind, over the 342 parsed decisions: 164 incidents that need judgment, 109 procedural or technical breaches, 36 component allowance exceeded, 33 pit lane speeding [verified: `build --decisions`, 2026-11-15]. The rule documents give 3,630 articles across 11 issues.

### 5.2 Cost [estimate]

Assumptions: 4,000 tokens of retrieved articles, 4,000 tokens for 5 past decisions, 1,500 tokens of output (reasoning included). **None of the three has been measured.** Prices are from the table in ADR-003.

| Per question | No search | Rules only | Rules + past decisions |
|---|---|---|---|
| gpt-6.1-terra | $0.008 | $0.012 | $0.016 |
| gpt-6-luna | $0.0008 | $0.0012 | $0.0016 |

| Stage | Model | What | Cost |
|---|---|---|---|
| Embedding | text-embedding-3-large | Index of 359 decisions and the rule articles, plus the questions | About $0.30 |
| Search evaluation | None | No model calls | $0 |
| Development | gpt-6-luna | Repeated runs on the dev questions | About $1 |
| Answer evaluation | gpt-6.1-terra | 150 test questions × 3 configurations | About $6 |
| **Total** | | | **About $8** |

With some margin, about $10. The rules are not put in whole, so this is less than the previous design (about $16) and does not depend on prompt caching. The number of test questions is fixed after the split in section 4.2 is settled.

---

## 6. Trade-offs and risks

| Decision | What we gain | What we lose |
|---|---|---|
| Past-decision search at the centre | RAG becomes a part the product cannot do without. Grounds are shown even for discretionary penalties | The "RAG vs the whole rulebook in the prompt" comparison is no longer the subject (kept as the optional experiment in step 7) |
| The Fact field as the question | Questions are produced automatically, so every decision can be used. About 4 hours of hand review go away | Less information than a question given the detailed findings of fact |
| No original text in the repository | Lowers the risk of breaching the terms | No hosted demo. Whoever clones it has to run `fetch` first |
| Rule-based scoring only | Scoring does not wobble and is easy to explain | The quality of the written reason is not measured |
| Every model call through LangChain | One way of calling; LangSmith tracing attaches automatically | Token figures arrive in the form LangChain has tidied |
| No agent | Small scope, all of it understandable | LangGraph is left for a separate project |
| The citation check runs once | A simple flow | A wrong citation is not corrected and asked again |

**Remaining risks**

1. **With one season only, the need for RAG may look weak.** 359 decisions may be an amount that could go in whole [unmeasured]. The case for RAG is that the documents keep growing, and the cost per question. The optional experiment in step 7 shows this difference in numbers.
2. **Adding past seasons is hard.** The season selector on fia.com offers 2015 and 2019 to 2026 [verified: 2026-11-15]. Whether the decisions exist in the same format has not been checked. The rule numbering changed in 2026, so a table mapping the article numbers of earlier seasons' decisions to the 2026 numbers would be needed. Finish with the 2026 season first.
3. **Repeated decisions inflate the numbers.** Decisions such as component allowance exceeded have nearly identical wording, so both search and answering are easy. They are reported per kind.
4. **Article extraction from the rules PDFs.** Resolved in step 3: every cited article of the four books is found in its issue (section 3.4).
5. **The decision format at other events.** Resolved in step 1: three layouts over the season, all handled or counted (section 3.2).
6. **The Fact field may be too short.** If it is at the level of "Car 12 – causing a collision", search becomes matching the article's name. In step 2, after reading the real text, decide whether to put the factual part of Reason into the question. **Settled 2026-11-15:** the Facts say which car did what where (12 words at the median), so the question and the searched text are the session and the Fact, without Reason.

---

## 7. Implementation order

For each step: explain what it builds and why, write the code, run it and confirm the result, then move on.

| Step | What | Done when |
|---|---|---|
| 0 | Project skeleton, manifest, fetch | The decision PDFs of 3 events are downloaded locally |
| 1 | Parsing decisions and labels | Every 2026 decision is parsed and the failure count is seen. The article normalisation tests pass |
| 2 | Decision search (embedding, Chroma, BM25, hybrid) | Typing an incident returns similar past decisions. The search evaluation numbers exist |
| 3 | Parsing the rules and rule search | Article recall@k exists |
| 4 | Answer generation and the citation check | Typing an incident returns the article, penalty, reason and supporting decisions in the right format |
| 5 | Answer evaluation | The results table for the three configurations exists and the checks pass. The README tables are filled |
| 6 | Product screen | The screen shows incident input, the answer, similar incidents and the stewards' decision |
| 7 | (Optional) comparison with putting the rules in whole | Accuracy and cost when the full rules replace rule search |

Once step 2 is finished, "find similar incidents" works without calling a model. The retrieval half of RAG is the first thing to be seen working.

## 8. Decided and still open

**Decided**
- The name "AI Steward"; CLI and package name `f1aisteward`
- Models: `gpt-6.1-terra` for the final run, `gpt-6-luna` for development (ADR-003)
- Every model call goes through LangChain (ADR-002). LangSmith is used
- No agent (ADR-008)
- Past-decision search is at the centre
- The question is the session and the Fact (2026-11-15)
- Dev and test ranges by event date (section 4.2, 2026-11-16)
- Past decisions: vector search (section 3.5, 2026-11-16)
- Rule documents: Section B, the ISC body, Appendix L and H, 11 issues (section 3.4, 2026-11-16)
- Rule articles: vector search plus the articles cited by the past decisions found (section 3.5, 2026-11-17)

**Still open**
- **Whether to also run the final evaluation on `gpt-6-luna`**: the previous design had it. The product does not need it, and it costs about $1.
