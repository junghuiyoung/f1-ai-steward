"""Paths and settings used by every command. Change a value here, not where it is used."""

from pathlib import Path

# This file is <project>/src/f1aisteward/config.py, so the project root is two folders up.
ROOT = Path(__file__).resolve().parents[2]

# In the repository: links and labels only, no FIA text.
EVENTS_MANIFEST = ROOT / "data" / "manifest" / "events.yaml"
DECISION_LABELS = ROOT / "data" / "labels" / "decisions.jsonl"

# On this machine only (listed in .gitignore): the downloaded documents and their text.
CACHE_DIR = ROOT / ".cache"
PDF_DIR = CACHE_DIR / "pdf"
PARSED_DECISIONS = CACHE_DIR / "text" / "decisions.jsonl"

FIA_BASE_URL = "https://www.fia.com"

# Be a polite client: wait between requests, and say what we are without naming the user.
REQUEST_DELAY_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 30.0
USER_AGENT = "f1aisteward/0.1 (local research tool)"
