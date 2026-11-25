# AI Steward: UI/UX design

Written 2026-11-14 · Revised 2026-11-15 · Built 2026-11-24 as `src/f1aisteward/app/static/index.html` (section 9) · Mockup: `mockup-v4.html`

The audience is English-speaking recruiters and interviewers (engineers). They arrive from the README, skim for about 30 seconds and, if interested, clone the repository and run it locally.

The screen is one thing: a product where you enter an incident and an answer comes out. How the product was evaluated is in the README (`README.md`), not on the screen.

---

## 1. Screen structure

```
AI Steward                                   Unofficial. Not affiliated with the FIA or Formula 1.
Describe a racing incident. AI Steward finds the rule in question and similar past incidents,
and says how stewards usually deal with it.

The incident                     │  AI Steward's answer            [Placeholder answer]
  Session        [Race ▾]        │  10 second time penalty                    ← large type
  Race weekend   [São Paulo ▾]   │  [Usual outcome. The stewards can go higher or lower.]
  Rules in force: Issue 09       │  ─────────────────────────────────────────
  What happened                  │  Rule in question   ISC App. L Ch. IV Art. 2 d)  Causing a collision
  [ textarea                 ]   │  Why                …
  [ Ask AI Steward ]             │  Similar past incidents   (section 4)
                                 │  Rules it relied on [chip] [chip]
Or start from a real incident    │  Answered in 6.8 s for about $0.02 · model · engine
  Passed off the track at Turn 1 │
  Contact at Turn 12             │  What the stewards decided            [Real document · 79]
  … (9 in all)                   │  This incident is real … AI Steward was not shown this document.
                                 │              AI Steward            The stewards
                                 │  Rule        … ✓ Matches           …
                                 │  Outcome     … ✕ Differs           …
                                 │  [one line explaining the difference]
                                 │  Fact / Infringement / Decision / Reason   │  [page image of the original document]
```

Below 960px it stacks into one column, and asking scrolls to where the answer is.

## 2. Flow and states

| State | Screen |
|---|---|
| Initial | "No answer yet" and one line of guidance on the right |
| Real incident selected | The input and the session are filled with that incident. No answer yet |
| Asking | The button changes to "Searching past decisions…" and is disabled. Three stages run in turn (finding similar past incidents, finding the rules that apply, writing the answer) |
| Answer | Expected outcome (large type), the basis of the penalty, the article, the reason, similar past incidents, the articles relied on, time taken and cost. The button reads "Ask again" |
| Stewards' decision | For a real incident it follows about 0.7 seconds after the answer, **without a button**. It sits side by side with the AI's answer, marked Matches / Differs / Partly matches |
| Incident written by the user | No decision area. In the mockup a note under the button says it cannot answer |
| No input | "Describe what happened first." and focus moves to the input |
| Document not on this machine | Guidance on the download command in place of the image |

## 3. Decided

- **The decision is shown automatically** (user decision, 2026-11-15). At first there was a "Show what the stewards decided" button, which was removed. The order is kept, with the answer first and the decision after, so that the AI does not appear to have answered after reading the decision. The first line of the area reads "AI Steward was not shown this document when it answered".
- **The original document is shown as page images.** Embedding the browser's PDF viewer left the box (620px high) taller than the document, with about 200px of empty viewer background under the document [verified: reproduced in real Chrome]. The PDF is rendered as page images, the blank part at the bottom of each page is trimmed, and it is displayed to fit the document size exactly. The original PDF opens through the "Open the PDF" link.
- **The largest type is the expected outcome.** Under it goes "Usual outcome. The stewards can go higher or lower." or "Fixed by the rules. No discretion.", which separates penalties that involve discretion from penalties computed from the rules.
- **When the answer differs from the decision, the reason is given in one line.** Example: the stewards took the wet track into account and halved the penalty. This keeps the product from looking simply wrong, and it shows the limit of an AI that reads text only.
- **There is no comparison screen.** The footer points to the README for how it was evaluated.

## 4. Similar past incidents

The centre of the product is searching past decisions (system design, section 1.3), so the answer area has a block for them. In `mockup-v4.html` the similar incidents and counts are values made up to show the layout.

**Position.** In the answer area, under "Why" and above "Rules it relied on".

```
AI Steward's answer
10 second time penalty                                         ← large type
Usual outcome. The stewards can go higher or lower.
──────────────────────────────────────────────────────
Rule in question   ISC App. L Ch. IV Art. 2 d)  Causing a collision
Why                …
Similar past incidents              8 under this rule, from earlier race weekends
  10 second time penalty  █████ 5
  5 second time penalty   ██ 2
  No further action       █ 1
  Miami GP · Race · Doc 41     Contact at Turn 11 …        10 second time penalty
  Monaco GP · Race · Doc 23    Contact at the chicane …    5 second time penalty
  Show all 8
Rules it relied on [chip] [chip]
```

**Decided.**
- The counts and the distribution are not written by the model; code counts them from the labels of the retrieved decisions. Only decisions under the same article as the answer are counted.
- Only decisions from events earlier than the question's event appear. Decisions from the same event do not appear.
- Each incident shows the event, session, document number, one line of fact and the penalty, and links to the original on fia.com. The one line of fact is FIA original text. In the README capture it is left as it is, not masked (user decision, 2026-11-15).
- If there is no similar incident, show "No similar incident in earlier race weekends." and change the basis-of-penalty line to "Based on the rules only."
- The bars of the distribution are not told apart by colour alone; the penalty name and the count are written as text alongside.

## 5. Copy

**Tone**: facts only, briefly. A technical reader is assumed, but no F1 knowledge. No exclamations, no marketing copy, no emoji.

| Location | Copy |
|---|---|
| Top banner | **Mockup.** The AI answers, times and costs are placeholders written by hand. No model has been run. The stewards' documents are real, from the 2026 São Paulo GP. |
| Intro sentence | Describe a racing incident. AI Steward finds the rule in question and similar past incidents, and says how stewards usually deal with it. |
| Input | The incident · Session · Race weekend · What happened |
| Rules issue | Rules in force that weekend: Sporting Regulations, Issue 09. |
| Button | Ask AI Steward → Searching past decisions… → Ask again |
| Incident list | Or start from a real incident |
| Empty state | No answer yet · Describe an incident on the left, or start from a real one, then ask. |
| Progress stages | Finding similar past incidents · Finding the rules that apply · Writing the answer |
| Answer fields | Rule in question · Why · Working (only when the answer has one) · Similar past incidents · Rules it relied on |
| Basis of the penalty | Usual outcome. The stewards can go higher or lower. / Fixed by the rules. No discretion. / Based on the rules only. |
| Similar past incidents | 8 under this rule, from earlier race weekends · Show all 8 · No similar incident in earlier race weekends. |
| Decision area | What the stewards decided · This incident is real: document 79 of the 2026 São Paulo GP. AI Steward was not shown this document when it answered. |
| Comparison table | AI Steward · The stewards · Rule · Outcome |
| Match marks | Matches · Differs · Partly matches |
| Document | Original document, from your local copy · Open the PDF · fia.com |
| No input | Describe what happened first. |
| Footer | AI Steward answers from the rules and from earlier stewards' decisions only. It has no video, no telemetry and no hearing, so it gives the usual outcome and the stewards may decide otherwise. |

**Terms.** On the screen the article is called "Rule" and the penalty is called "Outcome". For someone using the product these are easier than the document's field names, Article and Decision. The result of comparing the answer with the stewards' decision is Matches / Differs / Partly matches, never "correct", "wrong" or a ✓ on its own.

## 6. Accessibility

- The answer and the decision are each announced through a live region when they appear. Examples: "AI Steward's answer: 10 second time penalty. Rule in question: …", "The stewards decided: 5 second time penalty. Rule matches. Outcome differs."
- The document image has alt text, and the same content (Fact, Infringement, Decision, Reason) sits next to it as text.
- Match marks use a symbol, a word and a colour together.
- Colour tokens and contrast are in section 7.

## 7. Design tokens

Text contrast was calculated by hand.

| Token | Light | Contrast (background `#f9f9f7`) | Dark | Contrast (background `#0d0d0d`) | Use |
|---|---|---|---|---|---|
| `--page` | `#f9f9f7` | – | `#0d0d0d` | – | Page background |
| `--wash` | `#f0efec` | – | `#242422` | – | Selected row, quoted input block |
| `--ink` | `#0b0b0b` | 18.7 | `#f0efec` | 16.9 | Body text, figures |
| `--ink-2` | `#52514e` | 7.5 | `#c3c2b7` | 10.9 | Secondary text |
| `--muted` | `#6b6a65` | 5.1 | `#9c9a92` | 6.9 | Units, annotations |
| `--rule` | `#c3c2b7` | decorative | `#383835` | decorative | Rules |
| `--rule-strong` | `#8a8982` | 3.3 | `#77756e` | 4.2 | Input and button borders, the line under table headers |
| `--accent` | `#1c5cab` | 6.3 | `#86b6ef` | 9.2 | Links, focus ring |
| `--match` | `#0b6e4f` | 5.9 | `#4cc79a` | 9.2 | Matches |
| `--differ` | `#a8431a` | 5.7 | `#f08a5d` | 7.9 | Differs |
| `--partial` | `#7a5a00` | 6.1 | `#e0b84a` | 10.3 | Partly matches |
| `--mock-bg` / `--mock-ink` | `#fff4d6` / `#6b4e00` | 7.1 | `#3a2e0c` / `#fbe6a8` | 10.8 | Placeholder marker |

Differs uses a reddish brown instead of red for two reasons: a wrong answer is not a "danger", and red calls a particular brand to mind in this subject.

Nothing that calls the FIA or F1 to mind is used in the screen's own design: no logos, red brand colours, chequered-flag patterns or official typefaces. The page image of a decision is the FIA's own document and does carry the FIA and F1 logos.

**Fonts**: headings are `"Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif`. Body text is `system-ui`. Article numbers, figures and commands are `ui-monospace, "SF Mono", Menlo, Consolas, monospace`. No web fonts are downloaded.

**Spacing**: multiples of 4 (4, 8, 12, 16, 24, 40, 64).

## 8. Verification record (2026-11-15)

| What was checked | How | Result |
|---|---|---|
| Select an incident → ask → answer → decision shown automatically | Clicking in real Chrome | Works. No console errors |
| Blank space under the document image | Real Chrome, documents 71 (1 page) and 79 (2 pages) | The image fits the document size with no blank space underneath |
| Guidance text for an incident written by the user | Typed and clicked in real Chrome | Works |
| 1280px light, 390px | Headless Chrome screenshots | Works |
| The similar past incidents block, documents 79 and 43 | Headless Chrome at 1280px and 520px | Works. 390px could not be checked because of headless Chrome's minimum window width |

Not checked: Safari and Firefox, screen readers, keyboard-only operation.

**Worth knowing.** In the two-column layout the document image is about 300px wide, so its text looks small. The content is read from the text fields beside it; the image is there to show that this is the original. To see it larger, press "Open the PDF". A layout that enlarges the image to the full width of the answer area is also possible.

Shortcuts: `mockup-v4.html#case=79&ask=1` (an example where the answer and the decision differ), `#case=43&ask=1` (an example computed from the rules).


## 9. As built (2026-11-24)

The page is `src/f1aisteward/app/static/index.html`: one file, inline CSS and plain JavaScript, no libraries, served with a JSON API by `src/f1aisteward/app/server.py` (`uv run f1aisteward serve`). It keeps the mockup's layout, copy, tokens and accessibility features. What changed from the mockup:

| Mockup | Built |
|---|---|
| Top banner "Mockup ..." and "Placeholder answer" badges | Removed: every value on the page comes from the API |
| Nine São Paulo incidents written into the page | The race weekend drop-down lists all 20 weekends, newest first; the list under it holds that weekend's decisions (title from fia.com's listing, session, document number). The first option, "After the São Paulo GP", searches every decision and the latest rules, for typed incidents |
| "Rules in force: Sporting Regulations, Issue 09" | All four books in force that weekend, e.g. "Sporting Regulations, Issue 09; International Sporting Code of June 2026; Appendix L of June 2026; Appendix H of October 2026" |
| Typed incident: a note that the mockup cannot answer | Answered like any other; there is no stewards' area, because there is no decision to compare with |
| Three progress stages, timed | Still timed: the API has no progress events. The first two advance after about 0.6 s each; "Writing the answer" stays until the reply arrives |
| One generated line explaining why the stewards differed | Not built. Writing it would need a second model call that reads the stewards' decision, the one document the answer must never see. The stewards' own Reason field is shown in full instead, and usually says why (São Paulo 79: the wet track and the minor contact halved the penalty) |
| "Working" row for penalties computed from a table | Not built: the `Answer` format has no field for the arithmetic |
| "Rules it relied on" chips | Kept, plus "Decisions it relied on" (the precedents that passed the citation check, linked to fia.com) and, when a citation failed the check, a note "Left out after the citation check" |
| Matches / Differs written by hand | Computed in `app/view.py` with the scoring rules of the evaluation (`eval/score.py`): rule "Matches" when the article numbers are the same, "Partly matches" when some are; outcome "Matches" on type, value and unit, "Partly matches" on type alone |

Deep links for screenshots and the demo: `/#event=sao-paulo&case=2026-sao-paulo-079&ask=1`.

**Verified 2026-11-24** (headless Chrome 158 driven by Playwright, against the real server and `gpt-6-luna`): the São Paulo 79 deep link at 1280 px (dark) and 390 px; the empty state; light theme; an empty incident gives "Describe what happened first." and focuses the text box; picking an incident fills the text and session, and typing detaches it; changing the weekend replaces the list; a typed incident under "After the São Paulo GP" is answered with no stewards' area; "Show all" and "Show fewer"; no horizontal scroll at 390 px; no console errors once an empty favicon was added. Not checked: Safari and Firefox, screen readers, keyboard-only use, the non-ok statuses (refused, truncated, timeout, rate limited) on the real page; they are covered by API tests only.
