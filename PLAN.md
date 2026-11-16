# AI Steward: implementation plan

## Status

| Step | What | State |
|---|---|---|
| Prep | Apply the Codex review to the README draft and the design | Done 2026-11-15 |
| 0 | Project skeleton and `fetch` | Done 2026-11-15 |
| 1 | Parse decisions and build labels | Done 2026-11-15 |
| 2 | Search over past decisions | Next |
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

**Step 1**

- **Only 124 of the 359 PDFs are on disk.** The step 0 download stopped inside the Canadian Grand Prix (16 of 34). On 2026-11-15 fia.com answered every request for a missing file with HTTP 429 and a "Just a moment..." page, which is a bot check. Nothing was done to get around it. Everything below is from the 124 files of seven events (Australian, Chinese, Japanese, Miami, part of Canadian, Mexico City, São Paulo).
- **There are three layouts, not one.** 101 are the form with one car (`single_car`). 10 are a cover page plus an attached decision about several cars listed in a table, mostly Safety Car line time limits (`car_table`); these have no Driver or Competitor field and spell the last field "Reasons". 13 have no fields at all: 11 answer a team's request (start despite no qualifying time, change a driver) and 2 are Technical Delegate's reports. The 13 are left out and counted, not failed. The manifest's title filter cannot tell them apart, because their titles also start with "Decision" or "Infringement".
- **A field name is followed by an ordinary space; the words inside a value are joined by non-breaking spaces (U+00A0).** The parser uses this to tell a field name from a wrapped line that starts with the same word. The `car_table` attachment is made by other software and uses ordinary spaces everywhere.
- **pypdf's default text mode is the one to use.** Its `layout` mode returned an empty string for the one `single_car` document tried (São Paulo 79). The default mode breaks some words in `car_table` attachments ("Regu lations" in 5 of 10), so the article normaliser never relies on the name of the rule book.
- **The word "Reason" can be missing** (Canadian 47): the reason follows the decision with no label. The parser then cuts the Decision field after its first sentence and records a note.
- **A cover page and its attachment can carry different document numbers** (Miami 50: the attachment says 49). The manifest's number is the id; the number on the page is only kept as a field.
- **Articles.** 42 distinct article ids in 111 decisions. The most common are `ISC:12.2.1.i` (19), `F1-B:1.8.5` (16) and `ISC-L:IV.2.d` (13). All 111 Infringement fields gave at least one id. A Race Director's note is often cited beside an article ("item 5.7, document 34"); those numbers are not articles and are skipped.
- **Penalties.** `pit_lane_start` was added as a type (9 of 111); it is not in the list in `01-system-design.md` section 3.2, which has not been edited. "No penalty is applied" is counted as `no_further_action`. A fine with a suspended part is recorded as the whole amount. Penalty points are not recorded. One decision is `other` (Miami 28: lap times deleted).
- **Kinds** are assigned from a table of article prefixes in `parse/labels.py`, read off the Facts: judgment incident 55, procedural or technical 40, component allowance 10, pit lane speeding 6. The table will need new rows as other events arrive.
- **Fact as the question.** Median 12 words. Three things to handle in step 2: (1) in 10 places two or three decisions of the same event share an identical Fact, one decision per car in the same incident, so one question text can have several gold answers; (2) the Fact of a `car_table` decision says "the cars below" and means nothing without the table; (3) one Fact quotes article numbers (Mexico City 57). Pit lane speeding Facts are six words and all alike.
- **Second download, same day: 103 more files, then 429 again.** 227 of 359 are now on disk (twelve events complete, Belgian 13 of 14, eight events untouched). The two runs got 124 and 103 files before the block, so it looks like a limit on requests in some period, not a ban; how long the period is has not been measured. `fetch` used to keep asking for every remaining file after the first 429; it now stops at the first one, says how many files are left and exits with an error, and the next run continues from there (3 tests).
- **What the 103 new files changed.** (1) Session is not always there: Belgian 13 is about a press conference and has none, so Session is no longer required. (2) Barcelona-Catalunya 66 is a list of deleted lap times published under an ordinary title; it is recognised by its Decision field and left out as `lap_deletion_list`. (3) Canadian 64 cites points of a tyre procedure document, not an article, so it has no article id. (4) British 83 is a "penalty lap", counted as `other`. Counts over the 227: parsed 213 (198 `single_car`, 15 `car_table`), left out 14, failed 0. The counts in the bullets above are from the first 124 and were not redone.
- **All 359 are on disk since 2026-11-15 19:49.** The last 132 were downloaded by hand in a browser. Every file was then checked: it is a PDF, its first lines name its event, the document number printed in it equals the manifest's number, and its sha256 is in the manifest. The limit that stopped `fetch` let through about 100 files and then refused for a while; how long was not established.
- **Final counts over the season.** Parsed 342 (320 `single_car`, 22 `car_table`). Left out 17: 13 permissions, 2 Technical Delegate's reports, 1 list of deleted lap times, 1 ruling on the running of the event (Spanish 31, a stopped practice session). Failed 0. Kinds: judgment incident 164, procedural or technical 109, component allowance 36, pit lane speeding 33. 67 distinct article ids; the most common are `ISC:12.2.1.i` (63), `F1-B:8.2.3` (36), `F1-B:1.8.5` (33), `ISC-L:IV.2.d` (32). One decision has no article id (Canadian 64) and two have penalty `other` (Miami 28, British 83). Four have no Session. Per event: 6 to 32 parsed decisions.
- **Fact as the question, over the season.** Median 12 words. 23 groups of decisions (52 decisions) share an identical Fact inside one event. Two Facts quote an article number (British 83, Mexico City 57). 22 are `car_table` Facts that point at a table.
- **Five decisions were compared with their page images** (São Paulo 79, Miami 50, Canadian 47, Belgian 13, British 83; Claude did it at the user's request, reading the rendered pages, not the extracted text). Every field, article id and penalty matched, with one bug and one known blemish. The bug: the label "The Stewards" under the signatures comes out of pypdf as the first line of page 2, so in 34 decisions whose Reason crosses the page break it sat inside the Reason (21 in the middle, 13 at the end). The parser now drops a line that is only those two words; after the fix exactly those 34 Reasons changed and no label did. The blemish: the broken word in `car_table` attachments ("Regula tions") is still in the stored Infringement text; the article ids are right.
- **Still not done:** the 30-decision sample check of the labels in `01-system-design.md` section 4.1. Five is too few to say how many labels are wrong. "0 failed" means every required field was found, not that every label is right.
- **Decided 2026-11-15: the question is Session + Fact** (for São Paulo 79: "Race. Car 16 made contact with Car 30 in turn 12."). The four decisions with no Session use the Fact alone. The three problems above (identical Facts in one event, `car_table` Facts, two Facts that quote an article number) are for step 2.
- **A second question set, written 2026-11-15: `data/questions/paraphrased.jsonl`.** Questions taken straight from the Fact use the stewards' own wording, so keyword search finds them easily (a rough word-overlap check put the top match under the same article for 65% of questions). To measure search on wording a user would write, each of the 320 `single_car` decisions also has a reworded English question with the same information: no car, corner, speed or part added or dropped, no article, no penalty. The 22 `car_table` decisions have none. Claude wrote all 320 in one sitting, so they share one voice; nobody has reviewed them. Product input is English only (user decision).

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
data/labels/decisions.jsonl        decision id, article ids, penalty, kind, split (no FIA text)  (exists, 342 rows)
scripts/make_events_manifest.py    builds events.yaml from a saved fia.com listing (exists)
src/f1aisteward/
  cli.py            fetch (exists) / build / search / ask / serve / eval
  config.py         paths, settings (exists); later model names and price table
  manifest.py       title filter, read and write the manifest (exists)
  fetch.py          download PDFs, check hashes (exists)
  parse/decisions.py  decision PDF -> its eight fields (exists)
  parse/labels.py     normalise articles, structure penalties, classify kind (exists)
  parse/build.py      run both over the manifest, write records and labels (exists)
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
tests/              test_manifest.py, test_fetch.py, test_parse_decisions.py, test_labels.py, test_build.py (exist)
docs/demo.gif       recorded in step 6
.cache/  runs/      local only, not in git
```

## Steps

### Step 0: project skeleton and fetch (done)

- **Built**: `pyproject.toml`, `.gitignore`, `config.py`, `manifest.py`, `fetch.py`, `cli.py`, `scripts/make_events_manifest.py`, `data/manifest/events.yaml`, 13 tests.
- **Works**: `uv run f1aisteward fetch --event sao-paulo` downloads that event's decisions into `.cache/pdf/sao-paulo/`. A second run downloads nothing. A file whose hash contradicts the manifest is not saved.
- **Not done here**: fetching the rule documents. That is part of step 3.

### Step 1: parse decisions and build labels (done)

- **Build**: `parse/decisions.py`, `parse/labels.py`, tests, CLI `build --decisions`.
- **How**: extract text with `pypdf`, then cut it at the field names (No / Driver, Competitor, Time, Session, Fact, Infringement, Decision, Reason). Infringement becomes article ids such as `ISC-L:IV.2.d` and `F1-B:8.2.2`. Decision becomes `{type, value, unit}`. Tests use decision text we write ourselves, never FIA text.
- **Learn**: getting text out of a PDF, regular expressions, why one notation matters, unit tests.
- **Check**: `uv run f1aisteward build --decisions` prints parsed and failed counts and counts by kind. Compare three decisions with their PDFs by eye.
- **Done when**: every 2026 decision has been parsed and the failure count is known. `pytest` passes.
- **Decide here**: whether the Fact field alone works as the question. In the two documents read so far (São Paulo 79 and 43) Fact was one sentence saying which car did what where, or a list of parts.
- **Built (2026-11-15)**: `parse/decisions.py`, `parse/labels.py`, `parse/build.py`, CLI `build --decisions`, 112 new tests for the parser, labels and build (128 in all, with 3 added for `fetch`), `pypdf` added. Full records go to `.cache/text/decisions.jsonl` (local), labels to `data/labels/decisions.jsonl`.
- **Left**: nothing. The check by eye and the question decision are recorded under "Found along the way".

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
| Is the Fact field enough as the question | Decided 2026-11-15 | Session + Fact |
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
