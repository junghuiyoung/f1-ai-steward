"""Paths and settings used by every command. Change a value here, not where it is used."""

from pathlib import Path

# This file is <project>/src/f1aisteward/config.py, so the project root is two folders up.
ROOT = Path(__file__).resolve().parents[2]

# In the repository: links and labels only, no FIA text.
EVENTS_MANIFEST = ROOT / "data" / "manifest" / "events.yaml"
REGULATIONS_MANIFEST = ROOT / "data" / "manifest" / "regulations.yaml"
DECISION_LABELS = ROOT / "data" / "labels" / "decisions.jsonl"

# On this machine only (listed in .gitignore): the downloaded documents and their text.
CACHE_DIR = ROOT / ".cache"
PDF_DIR = CACHE_DIR / "pdf"
RULES_PDF_DIR = PDF_DIR / "rules"
PARSED_DECISIONS = CACHE_DIR / "text" / "decisions.jsonl"
PARSED_RULES = CACHE_DIR / "text" / "rules.jsonl"
INDEX_DIR = CACHE_DIR / "index"  # the Chroma files; they hold the decisions' and the rules' text

# Reworded questions for the search evaluation. Written for this project, no FIA text.
PARAPHRASED_QUESTIONS = ROOT / "data" / "questions" / "paraphrased.jsonl"

FIA_BASE_URL = "https://www.fia.com"

# Be a polite client: wait between requests, and say what we are without naming the user.
REQUEST_DELAY_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 30.0
USER_AGENT = "f1aisteward/0.1 (local research tool)"

# Search.
# Measured on the dev questions, hybrid did not beat vector search alone at any weight
# tried (PLAN.md, step 2), so the simpler method is the default. All three stay available.
SEARCH_METHOD = "vector"
EMBEDDING_MODEL = "text-embedding-3-large"  # after changing it, run `build --index` again
DECISIONS_COLLECTION = "decisions"
TOP_K = 5  # decisions a search returns
CANDIDATES = 20  # hybrid search: how many results each of the two searches hands to the fusion
VECTOR_WEIGHT = 0.5  # hybrid search: the vector ranking's share in the fusion; BM25 gets the rest

# Rule search: the articles of the rule documents in force on the question's event date.
RULES_COLLECTION = "rules"
RULES_SEARCH_METHOD = "vector"  # not measured yet; step 3 compares the three methods on dev
TOP_K_RULES = 8  # articles a rule search returns

# Which events are used for what, by event date (ISO dates compare correctly as strings).
#   before DEV_FROM            never a question. The answering model may have seen these in training.
#   DEV_FROM up to TEST_FROM   dev: questions used to tune search settings and the prompt.
#   TEST_FROM onwards          test: questions that produce the reported numbers.
# Every decision is in the search corpus whatever its split; a split only says which
# decisions are asked as questions.
DEV_FROM = "2026-06-01"  # the training cutoff of gpt-6.1-terra
TEST_FROM = "2026-08-01"  # the summer break: Hungarian (26 July) is dev, Dutch (23 August) is test
