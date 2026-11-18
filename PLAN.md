# AI Steward: implementation plan

## Status

| Step | What | State |
|---|---|---|
| Prep | Apply the Codex review to the README draft and the design | Done 2026-11-15 |
| 0 | Project skeleton and `fetch` | Done 2026-11-15 |
| 1 | Parse decisions and build labels | Done 2026-11-15 |
| 2 | Search over past decisions | Done 2026-11-16 |
| 3 | Parse the rules and search them | Done 2026-11-16; articles cited by the decisions found added 2026-11-17 |
| 4 | Generate answers and check citations | Done 2026-11-17 |
| 5 | Evaluate answers | |
| 6 | Product screen and final README | |
| 7 | Optional: compare with the whole rulebook in the prompt | |
| 8 | Optional: photo input | |

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
- **Penalties.** `pit_lane_start` was added as a type (9 of 111); it was added to the list in `01-system-design.md` section 3.2 on 2026-11-17. "No penalty is applied" is counted as `no_further_action`. A fine with a suspended part is recorded as the whole amount. Penalty points are not recorded. One decision is `other` (Miami 28: lap times deleted).
- **Kinds** are assigned from a table of article prefixes in `parse/labels.py`, read off the Facts: judgment incident 55, procedural or technical 40, component allowance 10, pit lane speeding 6. The table will need new rows as other events arrive.
- **Fact as the question.** Median 12 words. Three things to handle in step 2: (1) in 10 places two or three decisions of the same event share an identical Fact, one decision per car in the same incident, so one question text can have several gold answers; (2) the Fact of a `car_table` decision says "the cars below" and means nothing without the table; (3) one Fact quotes article numbers (Mexico City 57). Pit lane speeding Facts are six words and all alike.
- **Second download, same day: 103 more files, then 429 again.** 227 of 359 are now on disk (twelve events complete, Belgian 13 of 14, eight events untouched). The two runs got 124 and 103 files before the block, so it looks like a limit on requests in some period, not a ban; how long the period is has not been measured. `fetch` used to keep asking for every remaining file after the first 429; it now stops at the first one, says how many files are left and exits with an error, and the next run continues from there (3 tests).
- **What the 103 new files changed.** (1) Session is not always there: Belgian 13 is about a press conference and has none, so Session is no longer required. (2) Barcelona-Catalunya 66 is a list of deleted lap times published under an ordinary title; it is recognised by its Decision field and left out as `lap_deletion_list`. (3) Canadian 64 cites points of a tyre procedure document, not an article, so it has no article id. (4) British 83 is a "penalty lap", counted as `other`. Counts over the 227: parsed 213 (198 `single_car`, 15 `car_table`), left out 14, failed 0. The counts in the bullets above are from the first 124 and were not redone.
- **All 359 are on disk since 2026-11-15 19:49.** The last 132 were downloaded by hand in a browser. Every file was then checked: it is a PDF, its first lines name its event, the document number printed in it equals the manifest's number, and its sha256 is in the manifest. The limit that stopped `fetch` let through about 100 files and then refused for a while; how long was not established.
- **Final counts over the season.** Parsed 342 (320 `single_car`, 22 `car_table`). Left out 17: 13 permissions, 2 Technical Delegate's reports, 1 list of deleted lap times, 1 ruling on the running of the event (Spanish 31, a stopped practice session). Failed 0. Kinds: judgment incident 164, procedural or technical 109, component allowance 36, pit lane speeding 33. 67 distinct article ids; the most common are `ISC:12.2.1.i` (63), `F1-B:8.2.3` (36), `F1-B:1.8.5` (33), `ISC-L:IV.2.d` (32). One decision has no article id (Canadian 64) and two have penalty `other` (Miami 28, British 83). Four have no Session. Per event: 6 to 32 parsed decisions.
- **Fact as the question, over the season.** Median 12 words. 23 groups of decisions (52 decisions) share an identical Fact inside one event. Two Facts quote an article number (British 83, Mexico City 57). 22 are `car_table` Facts that point at a table.
- **Five decisions were compared with their page images** (São Paulo 79, Miami 50, Canadian 47, Belgian 13, British 83; Claude did it at the user's request, reading the rendered pages, not the extracted text). Every field, article id and penalty matched, with one bug and one known blemish. The bug: the label "The Stewards" under the signatures comes out of pypdf as the first line of page 2, so in 34 decisions whose Reason crosses the page break it sat inside the Reason (21 in the middle, 13 at the end). The parser now drops a line that is only those two words; after the fix exactly those 34 Reasons changed and no label did. The blemish: the broken word in `car_table` attachments ("Regula tions") is still in the stored Infringement text; the article ids are right.
- **The 30-decision label check of `01-system-design.md` section 4.1, done 2026-11-17: 0 wrong of 30.** Drawn at random by kind in proportion to the season (14 judgment, 10 procedural or technical, 3 component allowance, 3 pit lane speeding; `random.Random(20261117)`, the five above left out): 28 single-car forms and 2 `car_table` decisions, from 13 of the 20 events. Claude rendered every page with macOS PDFKit (`scratch/render_pages/render.swift`) and read the images, not the extracted text, with the labels in view. Checked: article ids, penalty type, value and unit, kind, and the session and Fact that make the question. Ids: australian-046, -066; azerbaijan-040; belgian-023, -030, -033, -034; british-062, -078; canadian-018, -037, -057; chinese-042, -060; dutch-041, -062, -063; hungarian-056, -057, -059; italian-032, -039, -055, -056, -064; mexico-city-068; miami-094; sao-paulo-040, -061; united-states-035. Zero in 30 bounds the error rate at about 10% (one-sided 95%: 9.5%); it does not show it is near zero. What the check met that is a convention, not an error: a fine with a suspended part is the whole amount (italian-032: €30,000, €25,000 of it suspended), "No penalty is applied" is `no_further_action` (dutch-041), penalty points are not kept (dutch-062, -063), and a Race Director's note beside an article is skipped. One boundary to know for the per-kind results of step 5: the kind follows the articles, so ISC 12.2.1.i alone is always procedural (32 decisions) even when it is about driving, such as italian-064, a 5-second penalty for not following the prescribed route at Turns 1 and 2 in the race; next to a driving article it is judgment (28).
- **Decided 2026-11-15: the question is Session + Fact** (for São Paulo 79: "Race. Car 16 made contact with Car 30 in turn 12."). The four decisions with no Session use the Fact alone. The three problems above (identical Facts in one event, `car_table` Facts, two Facts that quote an article number) are for step 2.
- **A second question set, written 2026-11-15: `data/questions/paraphrased.jsonl`.** Questions taken straight from the Fact use the stewards' own wording, so keyword search finds them easily (a rough word-overlap check put the top match under the same article for 65% of questions). To measure search on wording a user would write, each of the 320 `single_car` decisions also has a reworded English question with the same information: no car, corner, speed or part added or dropped, no article, no penalty. The 22 `car_table` decisions have none. Claude wrote all 320 in one sitting, so they share one voice; nobody has reviewed them. Product input is English only (user decision).

**Step 2**

- **Model cutoffs, checked on OpenAI's model pages on 2026-11-16.** `gpt-6.1-terra` 2026-06-01, `gpt-6-luna` 2026-05-18, as ADR-003 says. Step 2 calls no chat model; the cutoff only decides which events questions come from. Five events (83 parsed decisions) are before 2026-06-01 and fifteen (259) after.
- **The embedding model has a cutoff too.** OpenAI's embeddings guide says `text-embedding-3-large` knows nothing after September 2021. An embedding model does not need to know an event, only the words. The words in the Facts that could be new in 2026 are few ("energy" in 17 Facts, "MGU" in 11, both older than 2021). The effect has not been measured.
- **Split, by event date in `config.py`.** Before 2026-06-01: never a question (5 events, 83 decisions). Dev: Monaco to Hungarian (6 events, 99 decisions). Test: Dutch to São Paulo (9 events, 160 decisions). Both boundaries are the user's decision (2026-11-16): questions only after 2026-06-01, and dev/test cut at the summer break (`TEST_FROM = "2026-08-01"`). With about 160 test questions a score near 0.7 has a 95% interval of about ±7 points.
- **Four LangChain defaults did not fit this data.** Each is changed in the code and covered by a test.
  1. `BM25Retriever` splits text with `str.split()`, so "Car", "car" and "car." are three words. On the reworded questions (all rounds) hit@5 was 0.590 with the default and 0.694 with lower case and no punctuation; on the Fact questions it made no difference (0.741 and 0.747), because they share the stewards' capitals. `index.tokenize` is passed as `preprocess_func`.
  2. `EnsembleRetriever` treats documents with equal text as one document. 17 texts are shared by 39 decisions, so hybrid search would have lost 22 decisions that BM25 alone and vector alone return. `id_key="id"` is set.
  3. `BM25Retriever` has no metadata filter. `DecisionSearch` builds one small BM25 index per cut-off round, holding earlier rounds only (all 19 take 0.1 s). One index over everything, filtered afterwards, gave the same hit@5; the per-round index is used so that word rarity is also counted over earlier decisions only. Chroma filters on `round` in metadata.
  4. `BM25Retriever.from_documents([])` raises `ValueError`. The first event has no earlier decisions (13 Australian decisions), so `search` returns an empty list there.
- **`langchain-community` is sunset.** Importing it prints "no longer actively maintained" (GitHub issue 674 of that repository, which names no new home for `BM25Retriever`). 0.4.2 works and is pinned in `uv.lock`. `EnsembleRetriever` is in `langchain_classic.retrievers`. pytest is told to ignore that one warning. If it breaks one day, the replacement is a `BaseRetriever` of about 30 lines over `rank_bm25`.
- **`rank_bm25` misbehaves on a handful of documents.** A word found in more than half of the documents gets a floor value that depends on the average over all words, and on a three-document corpus that average was negative: an exact match ranked last. Seen in a unit test, not in the real data (average over the season is 4.6). It can only touch the first rounds, which are not questions.
- **BM25 always returns k decisions**, also ones that share no word with the question. Over the season this happened for 1 of 328 Fact questions. Not handled.
- **Questions on dev.** 87 in the stewards' words from 99 decisions: 5 `car_table` decisions left out, 1 that names an article (British 83), and decisions of one event with identical text merged into one question whose gold answer is all their articles. 94 reworded questions (their texts are never identical).
- **hit@5 cannot reach 1.** For 14 of the 87 dev questions (16 of the 94 reworded) no earlier decision has the same article, so the best possible hit@5 is 0.839 (0.830). Over the season, five decisions picked at random give hit@5 0.30. `eval --retrieval` prints the ceiling; it does not print the random baseline.
- **Search on dev, k=5, `text-embedding-3-large`, run 2026-11-16** (hit@5 / precision@5). Stewards' words, 87 questions: BM25 0.770 / 0.480, vector 0.770 / 0.487, hybrid 0.747 / 0.499. Reworded, 94 questions: BM25 0.702 / 0.357, vector 0.745 / 0.479, hybrid 0.734 / 0.447. All 543 searches returned earlier events only.
- **Hybrid is not better than vector on dev.** On the reworded questions vector beats BM25 clearly on precision@5 (0.479 against 0.357) and hybrid lands between the two. On the stewards' wording the three are level. One question is 1.1 points of hit@5, so the hit@5 gaps here are one to four questions and say little; the precision gap on reworded questions is the only large one. The first hybrid settings were 20 candidates from each search and equal weights.
- **Tuning the fusion did not make hybrid better than vector (dev, 2026-11-16).** Tried: vector weight 0.3, 0.5, 0.6, 0.7, 0.8, 0.9 with 10, 20 and 50 candidates, 18 settings. Reworded questions: vector alone has precision@5 0.479 and hit@5 70 of 94; the best hybrid (50 candidates, vector weight 0.9) has 0.474 and 71 of 94; equal weights give 0.440 to 0.453. Precision rises as the vector weight rises, which is hybrid turning into vector. Stewards' wording: hybrid precision@5 is 0.483 to 0.499 against 0.487 for vector, with hit@5 one or two questions lower (65 or 66 of 87 against 67). Every gap between vector and the better hybrid settings is one or two questions. `VECTOR_WEIGHT` and `CANDIDATES` in `config.py` were left at 0.5 and 20: no setting earned a change. The sweep was a throwaway script, not a command. **Decided by the user, 2026-11-16: search defaults to vector** (`SEARCH_METHOD` in `config.py`). BM25 and hybrid stay in the code and in the comparison table. `README-draft.md`, `01-system-design.md` section 3.5 and ADR-004 were rewritten the same day: the method is chosen by comparing the three on dev, and the dev numbers and the decision are recorded there. The rules search of step 3 is measured separately.
- **What RRF does, seen on one search.** For "car 16 made contact with car 30 at turn 12" before São Paulo, hybrid put first a practice-session decision that BM25 had fourth and vector had outside its top five: being in the middle of both lists beat being at the top of one.
- **Cost and time.** `build --index` embeds the 342 decisions in one run of 5 seconds; the index is 7 MB. `eval --retrieval` takes under 4 seconds, with one embedding request for all questions. The cost was not read from the OpenAI dashboard; by token count it is far below one cent.
- **What was seen of the test events.** The checks before step 2 printed BM25 numbers over all rounds, test events included (by kind and by round range). The tokenizer is the only setting chosen with those numbers in view. `eval --retrieval` uses dev unless `--split test` is given.
- **The searched text is the session and the Fact only.** The findings-of-fact part of Reason is not included and has not been tried. `01-system-design.md` section 3.3 and ADR-004 said it was included; both were corrected on 2026-11-16, together with ADR-009's mention of a masked Reason and of mask positions in the repository.
- **Chroma's usage reporting is switched off** (`anonymized_telemetry=False`); its default is on.

**Step 3**

- **Four labels were wrong, and are fixed.** `2026-bahrain-057` had `ISC:1.8.5` for "Article 1.8.5 of the FIA F1 Regulations"; `belgian-043` and `canadian-106` had `ISC:1.8.4.b` ("Article 1.8.4.b of the FIA F1 Regulations", "Article B 1.8.4b"); `british-058` had `ISC:2.5.5.b` for "Article 2.5.5 b) of Appendix H". The normaliser read a bare number as the body of the Code before it saw the book named after it. A bare number now waits for the next "of ..."; "of the FIA F1 Regulations" without a section letter is taken as Section B, which is a guess (every other section was cited with its letter). 10 tests added. Exactly those four rows of `data/labels/decisions.jsonl` changed, and no kind.
- **The fix moved the step 2 numbers a little** (dev, k=5, run 2026-11-16). Stewards' words: BM25 0.782 / 0.490, vector 0.782 / 0.499, hybrid 0.759 / 0.508; 13 questions out of reach (best hit@5 0.851). Reworded: BM25 0.713 / 0.360, vector 0.755 / 0.483, hybrid 0.745 / 0.451; 15 out of reach (0.840). Vector is still level with or ahead of the other two. The step 2 bullets above keep the old numbers as a record. On 2026-11-17 the 18-setting hybrid sweep was run again on the fixed labels (throwaway script): the best setting is still 50 candidates and vector weight 0.9, with 72 of 94 / 0.479 on the reworded questions against vector's 71 / 0.483, and equal to vector on the stewards' words (68 of 87 / 0.499); the others are at most 0.508 on precision and one or two questions lower on hit. The reading did not change. `README-draft.md`, `01-system-design.md` and ADR-004 now show these numbers.
- **Rule documents, decided by the user 2026-11-16: Section B, the ISC body, Appendix L and Appendix H.** Of the decisions with an article, 98 of 99 dev and 158 of 160 test cite at least one article in these four. Section B alone would have been 72 and 101, and would have lost the collision article (Appendix L IV.2.d) and "failure to follow instructions" (ISC 12.2.1.i). Section C is left out: 7 decisions cite it. The Driving Standards Guidelines that `01-system-design.md` section 3.4 lists are not cited as an article by any decision and are not included.
- **Eleven issues were in force during the season** (`data/manifest/regulations.yaml`): Section B issues 5 to 9, two of the ISC, two of Appendix L, two of Appendix H. Each issue's start date is the one the document gives itself: Section B the later of its issue date and its WMSC approval date (they differ by up to four days, and no event falls between them), the ISC "Application from", the appendices "Published on". fia.com's own "Published on" dates were not used. Some are later uploads: Section A issue 3, dated 25 June, is listed on 19 October. Using them would have moved Miami (4 May) and Bahrain and Singapore (4 and 11 October) to an older Section B issue.
- **No Appendix H was in force before 12 March** in the files fia.com has now, so the Australian Grand Prix (8 March) is searched without it. Australian is never a question. Whether an earlier 2026 Appendix L or H existed and was replaced on fia.com is not known.
- **Appendix H "2025" (published 12 March 2026) ends with "MODIFICATIONS FOR 2026"**: pieces of clauses that replace the main text (2.5.5 g, the green flag; medical services; rally parts), with the unchanged text cut out as "…/…". They are not merged in; the index holds the main text. No decision cites a clause they touch (the cited ones are 2.5.5 b and e). Both Appendix L issues and Appendix H 2026 end with modifications for 2027, which are not indexed. Section B's appendices (definitions, forms, changes for later years) are not indexed either.
- **pdfplumber reads the rule documents; pypdf still reads the decisions.** The ISC and its appendices print French on the left and English on the right. pypdf reads the two in an order that changes within a page (a French paragraph then its English one, or a whole French article then the English article). pdfplumber can crop a page; the crop line is the empty band between the columns, found on each page from the words' positions. It also gets the ligatures right that pypdf breaks in Section B ("O=icials"). `pdfplumber` 0.11.10 was added. All 11 issues take 78 seconds.
- **Pages without a column gap.** The cover and contents pages at the start are skipped. Later ones have a table across the page and are cut where the columns usually meet. A first version skipped those as well and lost the heading of Appendix L chapter III, which sits on a page with a table (page 47), so the helmet articles were filed under chapter II.
- **How each book numbers its text.** Section B: only three-level paragraphs (B1.8.5); two headings (B5.12, B5.13) have text of their own; contents lines end with a page number. ISC: "ARTICLE 12.2" headings, some with no title ("ARTICLE 16.1"); paragraphs to four levels with a letter (12.2.1.i); Articles 13 and 14 use two-level paragraphs with no "ARTICLE" ("14.2 A review ..."). Appendix L: articles "1." to "6." start again in each chapter, so the chapter is part of the id (`ISC-L:IV.2`); points a) to e) stay inside the article. Appendix H: like the ISC, with "2.4. MARSHAL POSTS" written with a full stop.
- **A number at the start of a line followed by a small letter is a wrapped cross-reference** ("B5.15.2 shall remain unchanged ..."), not a new paragraph. A paragraph starts with a capital.
- **The FIA numbering is not clean.** Section B issue 5 uses B1.1.1 to B1.1.3, B1.4.1 to B1.4.3 and B5.1.8 twice for different paragraphs; issue 6 B3.5.7; issue 9 B1.5.11. Both paragraphs are kept, under one article id with "#2" in the key. Numbers also go backwards (B1.4.1 after B1.4.3; B5.14.3 in the middle of B5.15), so their order is not checked.
- **Counts.** 3,630 articles: Section B 306 to 314 per issue, ISC 634, Appendix L 199 and 200, Appendix H 209 and 214. Median length: Section B 64 to 69 words, ISC 28, L 51, H 95. The longest are ISC Article 20, the definitions (3,050 words), Appendix L VI.1.3 (1,800) and Appendix H 2.5.5, every flag signal in one article (1,170). Nothing is split further.
- **Every cited article is in the issue in force on its decision's date.** Over all 342 decisions: 279 citations match an article id exactly, 170 are a point inside an article (IV.2.d inside IV.2, 2.5.5.b inside 2.5.5, 1.6.3.a.iii inside 1.6.3; checked that only letters are dropped, never a number), 1 is broader than the paragraphs (B5.11), 7 are in Section C. None is missing. `eval --retrieval` prints the count of cited articles not found in their issue; it is 0.
- **Rule search on dev, k=8, run 2026-11-16** (recall@8: the share of a question's cited articles held by one of the 8 retrieved articles, averaged over questions). Stewards' words, 87 questions citing 104 articles: BM25 0.607, vector 0.699, hybrid 0.734. Reworded, 94 questions citing 113: BM25 0.518, vector 0.644, hybrid 0.635. Best possible 0.989 for both (the one Section C citation). All 543 rule searches returned articles of the issues in force only.
- **Two articles explain most misses** (vector). Appendix L IV.2 (overtaking, track limits, causing a collision) was found for 1 of 13 questions in the stewards' words and 0 of 13 reworded; ISC 12.2.1 (12.2.1.i, failure to follow the officials' instructions) 0 of 12 and 0 of 14. Most Section B articles are found (B1.6.3 pit lane 14 of 14, B1.8.4 yellow flags 8 of 8, B1.8.6 track limits 8 of 9). Many of the 8 places go to text F1 does not use: Appendix L chapter V (offroad circuits, 34 results) and Appendix H 2.10 (safety car procedures "except for FIA championships ... with specific regulations"; F1 has B5.13). Example: for "car 16 made contact with car 30 at turn 12" before São Paulo, IV.2 is not among the 8.
- **Hybrid against vector for rules is not settled.** +3.5 points on the stewards' words, -0.9 on the reworded questions: three questions and one. **Decided by the user, 2026-11-17: rule search defaults to vector** (`RULES_SEARCH_METHOD` in `config.py`), the same method as decision search. No fusion weights were tried for rules.
- **Cost and size.** `build --index` now also embeds the 3,630 articles (608,000 tokens by tiktoken count, about $0.08; not read from the dashboard) in 23 seconds together with the decisions. The Chroma folder grew from 7 MB to 127 MB. `eval --retrieval` takes 5 seconds.
- **Decided by the user, 2026-11-17: raise rule recall before step 4.** First idea, measured on dev with a throwaway script (vector for both searches): add to the rule results the articles cited by the 5 retrieved decisions, looked up in the issues in force (`holding`, so IV.2.d becomes IV.2). Recall, stewards' words / reworded: vector, 8 articles, 0.699 / 0.644; the linked articles alone 0.820 / 0.794 (2.7 articles on average); the 8 plus the linked ones 0.933 / 0.924 (9.6 and 9.7 articles on average, at most 14); linked first, filled to 8 by vector, 0.875 / 0.892. The gain is not from showing more articles: vector alone gives 0.728 / 0.676 at k=10 and 0.762 / 0.702 at k=14. The linked articles can find a cited article where decision search scores no hit, because a decision under IV.2.b and a question under IV.2.d share the chunk IV.2.
- **Built the same day, the user's choice: the 8 plus the linked ones.** `RuleSearch.search(..., decisions=...)` adds `cited_by(decisions, date)` after the 8; `holding` moved from `eval/retrieval.py` to `search.py`. `search --rules` now also runs decision search and prints the two parts apart, with the decisions that cite each article. `eval --retrieval` adds a row "vector + cited": 0.933 / 0.924, 9.6 / 9.7 articles on average, at most 15 / 14 (the throwaway script counted an id once; two paragraphs the FIA numbered alike are two articles here). Example: for "Car 27 ran into car 55 at turn 8 in the race." before Monaco, IV.2 is not among vector's 14 closest, and all 5 decisions found cite IV.2.d, so it comes 9th. 7 tests added (218 in all).
- **Rule hit@8 is reported nowhere, on purpose.** 73 of the 87 dev questions cite one article, and for them hit and recall are the same. For the 14 that cite more, hit hides the missing ones: vector hit@8 is 0.724 / 0.681 against recall@8 0.699 / 0.644. Decision search has no recall for the opposite reason: the number of right earlier decisions runs from 0 to 26 per question (median 5), so recall@5 would mostly measure how common an article is.

**Step 4**

- **What LangChain returns, read in the installed source** (`langchain-openai` 1.8.0, so above 1.3.5). `with_structured_output(..., include_raw=True)` returns a dict with `raw` (the `AIMessage`), `parsed` and `parsing_error`. Token counts are in `raw.usage_metadata`: `input_tokens`, `output_tokens`, `input_token_details.cache_read`, and the reasoning tokens in `output_token_details.reasoning`. A refusal, or a content filter, comes back as a `ModelRefusalError` in `parsing_error`. An answer cut off at the token limit has `response_metadata["status"] == "incomplete"`. `max_tokens` is sent as `max_output_tokens`. A timeout raises `ModelTimeoutError`. Refusal, truncation and timeout have not happened on a real call; only unit tests cover them.
- **Output tokens include the reasoning tokens.** The first real answer had 605 output tokens, 494 of them reasoning, which leaves about 110 for the JSON answer. So the cost counts output tokens once and never adds reasoning on top.
- **The prompt is far smaller than estimated.** Three real questions: 2,170, 2,646 and 3,007 input tokens (9, 8 and 11 articles, 5 decisions); 236 to 605 output tokens. `01-system-design.md` section 5.2 and ADR-003 assume 8,000 in and 1,500 out. On `gpt-6-luna` the three cost $0.0004 to $0.0005 each against $0.0016 estimated. Three questions are not a measurement for step 5, which still measures ten dev questions first.
- **Time.** Search 1.1 to 1.4 s, the question's embedding request included. The model 4.0 to 8.2 s at reasoning effort medium.
- **Three real incidents, dev events, in the stewards' words (session and Fact):**

  | Decision | Stewards | Answer | Earlier decisions under the answer's article (of the 20 closest) |
  |---|---|---|---|
  | `2026-hungarian-054`, a collision in the race | ISC-L:IV.2.d, 5 s | ISC-L:IV.2, no further action | 15: 8 no further action, 6 × 10 s, 1 × 5 s |
  | `2026-hungarian-036`, impeding in qualifying | F1-B:4.1.1, 3 places | F1-B:4.1.1, 3 places | 11: 5 warning, 4 no further action, 1 × 3 places, 1 × €5,000 |
  | `2026-british-062`, an unsafe release in qualifying | F1-B:1.6.2.b.i, €5,000 | F1-B:1.6.2.b.i, €5,000 | 3: 2 × €7,500, 1 × €5,000 |

  All three are well formed and passed the citation check. The article was right three times (the first at paragraph level, which is how the rules are cut), the penalty twice. For the collision the model said the Fact does not establish who caused it. For impeding it followed the one qualifying precedent it cited, not the majority of the 11; which sessions those 11 come from was not looked at. No real answer has failed the citation check yet; the failing path is covered by unit tests only.
- **The counts can disagree with the answer**, as for impeding. They are printed side by side and neither is changed to fit the other.
- **The model also wrote ids inside the rationale** ("[2026-british-060]"). The check reads only `articles` and `precedents_used`.
- **Dev events were used, not São Paulo.** The step's check named `--event sao-paulo`, a test event. The prompt is still being written, so its questions came from dev, to keep the test events unseen.
- **`ask` searches decisions twice:** k=5 for the prompt, the same 5 that step 2 measured, and k=20 for the counts. The question's vector is fetched once and reused.
- **LangSmith is not set up.** `.env` holds `OPENAI_API_KEY` only (the names were checked, not the values). Tracing attaches without code once `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` are added there.
- **Taken as Claude suggested, 2026-11-17** (the user said to start without changing them): `ask` uses `gpt-6-luna`; the citation check counts an article as shown when it is one of the articles or decisions shown, or lies inside one or holds one (the rule of `search.holding`, as `answer.related`); `penalty_type` is an enum of the step 1 labels (`labels.PENALTY_TYPES`). Also Claude's first values, untuned: reasoning effort medium, 4,000 output tokens at most, 120-second timeout, 20 decisions for the counts.

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
| `interview-prep.md` | Interview questions with model answers, every step so far (local, not in git) |

## How we work

Claude writes the code. The user must understand all of it. **One step at a time**, and each step follows this order:

1. Explain what this step builds and why, with a diagram.
2. Write the code. Explain a new concept the first time it appears. Install a library in the step that first needs it.
3. Give the commands the user runs and the output to expect.
4. Ask one or two questions an interviewer might ask, to check understanding. When the step is finished, add the ones worth keeping, with model answers, to `interview-prep.md`.
5. Move on when the user says so. Update "Status" and "Found along the way" in this file first.

Commit only when the user asks.

## Layout

```
pyproject.toml  .gitignore  .env.example
data/manifest/events.yaml          events, dates, decision links and sha256      (exists)
data/manifest/regulations.yaml     rule document issues, date in force, link, sha256    (exists, 11 issues)
data/labels/decisions.jsonl        decision id, article ids, penalty, kind, split (no FIA text)  (exists, 342 rows)
scripts/make_events_manifest.py    builds events.yaml from a saved fia.com listing (exists)
src/f1aisteward/
  cli.py            fetch [--rules], build --decisions/--rules/--index, search [--rules], eval --retrieval, ask (exist) / serve
  config.py         paths, settings, model settings and price table (exists)
  manifest.py       title filter, read and write the manifests, issues in force on a date (exists)
  fetch.py          download PDFs, check hashes (exists)
  parse/decisions.py  decision PDF -> its eight fields (exists)
  parse/labels.py     normalise articles, structure penalties, classify kind (exists)
  parse/build.py      run both over the manifest, write records and labels (exists)
  parse/rules.py      rules PDF -> articles with heading paths, with pdfplumber (exists)
  index.py          decisions and articles -> documents, BM25, Chroma collections `decisions` and `rules` (exists)
  search.py         bm25, vector and hybrid (RRF): decisions of earlier events, articles of the issues in force, plus the articles the decisions found cite (exists)
  llm/client.py     the one place ChatOpenAI is called; records tokens and cost (exists)
  answer.py         prompt, Answer schema, citation check, outcome counts (exists)
  eval/retrieval.py search evaluation (exists)
  eval/answers.py   answer evaluation runner (three configurations)
  eval/score.py     scoring rules
  eval/report.py    results/summary.json and the README tables
  app/server.py     FastAPI
  app/static/index.html
tests/              manifest, fetch, parse_decisions, labels, build, questions, index, search, eval_retrieval, rules, llm_client, answer (exist)
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
- **Built (2026-11-16)**: `index.py`, `search.py`, `eval/retrieval.py`, CLI `build --index`, `search`, `eval --retrieval`, the split in `config.py` and in the labels file, 38 new tests (168 in all). The same-event test asks every made-up decision as a question, by all three methods; `eval --retrieval` repeats the check on every real question and stops if it fails.
- **Left**: nothing that blocks step 3. Not done: the test-split run, which waits until the settings are final.

### Step 3: parse the rules and search them

- **Build**: `parse/rules.py`, `regulations.yaml`, the Chroma collection `rules`, fetching of rule documents.
- **How**: one article is one chunk with its heading path in front. Search only the issue in force on the question's event date.
- **Learn**: chunking that follows document structure, handling a document with several issues.
- **Check**: `uv run f1aisteward search "..." --rules` returns eight articles. The search evaluation gains article recall@8 and the number of questions whose article is outside the included documents.
- **Done when**: recall@8 exists.
- **Risk**: extracting articles from the rules PDFs has never been tried. The product works on decision search alone, so if this stalls, cut down to the Sporting Regulations and move on.
- **Decide first**: which rule documents to include.
- **Built (2026-11-16)**: `data/manifest/regulations.yaml` (11 issues), `fetch --rules`, `parse/rules.py`, `build --rules` (articles to `.cache/text/rules.jsonl`), the Chroma collection `rules` in `build --index`, `RuleSearch` in `search.py`, `search --rules`, recall@8 in `eval --retrieval`, `manifest.issues_in_force`. The label fix in `parse/labels.py`. `pdfplumber` added. 43 new tests (211 in all).
- **Built (2026-11-17)**: the articles cited by the decisions found, added to rule search (`RuleSearch.cited_by`), in `search --rules` and as "vector + cited" in `eval --retrieval`. 7 new tests (218 in all).
- **Docs brought up to date (2026-11-17)**: `01-system-design.md` (sections 1.3, 2, 3.2, 3.4, 3.5, 4.1 to 4.3, 5.1, 6 and 8), ADR-004 and ADR-010 in `02-tech-stack-adr.md` (the pdfplumber change belongs to ADR-010, not ADR-005 as this file used to say), and `README-draft.md`.
- **Left**: nothing that blocks step 4. Not done: the test-split run, which waits until the settings are final. The 30-decision label check from step 1 is done (0 wrong; under step 1 above).

### Step 4: generate answers and check citations

- **Build**: `llm/client.py`, `answer.py`, CLI `ask`.
- **How**: the prompt is instructions, then retrieved articles, then retrieved past decisions, then the question. `ChatOpenAI` structured output returns `Answer` (articles, penalty type, value and unit, reason, ids of the decisions relied on). Code then checks that every cited article and decision id was actually retrieved. Counts such as "5 of 8 got 10 seconds" are computed in code, never written by the model.
- **Learn**: building a prompt, structured output, checking grounding, tokens and cost, reading a call in LangSmith.
- **Check**: `uv run f1aisteward ask "..." --event sao-paulo` prints the answer, the outcome counts, the time and the cost.
- **Done when**: three real incidents give well-formed answers and the citation check works.
- **Verify while building**: `langchain-openai` is 1.3.5 or later; `with_structured_output(..., include_raw=True)` returns token usage; which field carries reasoning tokens. All three checked (under "Found along the way", step 4).
- **Built (2026-11-17)**: `llm/client.py` (`ask`, `read`, `Usage`, `Reply`), `answer.py` (`Answer`, `messages`, `check`, `outcomes`, `answer`, `report`), CLI `ask`, the model settings and price table in `config.py`. 25 new tests (243 in all).
- **Left**: nothing that blocks step 5. Not done: reading a call in LangSmith (no LangSmith key in `.env` yet); `REASONING_EFFORT` and `OUTCOME_POOL` are untuned first values. `01-system-design.md` sections 3.6 and 5.2 and ADR-002 and ADR-003 still carry the pre-step-4 notes ("verify during implementation", the 8,000-token prompt estimate).

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
| Which events are dev and which are test | Decided 2026-11-16 | Before 2026-06-01 never a question; dev Monaco to Hungarian (99 decisions); test Dutch to São Paulo (160) |
| Which rule documents to include | Decided 2026-11-16 | Section B, ISC body, Appendix L and H (11 issues) |
| Default rule search method | Decided 2026-11-17 | Vector, as for decisions |
| Try to raise rule recall before step 4 | Decided 2026-11-17 | Yes. First idea: add the articles cited by the retrieved decisions |
| How many articles go into the prompt | Decided 2026-11-17 | The 8 found by search plus the articles the decisions found cite (9.6 on average) |
| Model for `ask` while building | Taken 2026-11-17 | `gpt-6-luna` |
| When does a cited article count as shown | Taken 2026-11-17 | Same id, or one inside the other (`answer.related`) |
| Reasoning effort | Step 5, on dev | Medium for now, untuned |
| Also run the final evaluation on `gpt-6-luna` | Step 5 | Yes, it costs about $1 |
| Code licence | Before pushing to GitHub | The user decides |

## Verification

- Every step: `uv run pytest -q`, plus that step's "Check" commands and expected output.
- Search: the search numbers, and the "never retrieves its own event" test run over every question.
- Answers: all four checks in step 5 must pass before any number goes into the README.
- Screen: after `uv run f1aisteward serve`, click through a real incident where the outcome differs (São Paulo 79), one fixed by the rules (São Paulo 43) and a typed incident.
- No FIA text in git: `git status` must show `.cache/`, `documents/` and `mockup-*` as untracked and ignored.
