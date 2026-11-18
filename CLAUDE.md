# AI Steward

A local RAG app for Formula 1 racing incidents: describe an incident, get the rule in question, the usual penalty and similar past stewards' decisions.

## Before you work

- Read `PLAN.md`. It holds the plan, what is done, and what earlier steps found in the real data.
- Do one step at a time. When a step is finished, update "Status" and "Found along the way" in `PLAN.md`, then stop and wait for the user.

## How we work

- Claude writes the code. The user must understand all of it.
- For each step: explain what it builds and why, with a diagram; write the code; give the commands the user runs and the output to expect; ask one or two questions an interviewer might ask. When the step is finished, add the questions worth keeping, with model answers, to `interview-prep.md` (local, not in git).
- Explain a new concept the first time it appears. Install a library in the step that first needs it.
- Add a tool or a method only when the product needs it, never to cover a keyword.

## Rules

- No FIA document text or PDFs in git. `.cache/`, `documents/` and `scratch/` stay on this machine. The one exception is `docs/demo.gif`.
- Commit only when the user asks.
- Claude does not handle API keys. The user puts them in `.env`.
- Tests never use the network or real FIA text.

## Commands

```bash
uv run f1aisteward --help
uv run pytest -q
```
