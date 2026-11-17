"""Download the PDFs listed in the manifests into .cache/pdf/: stewards' decisions, and
the issues of the rule documents (.cache/pdf/rules/).

Each file is identified by its SHA-256 hash, a fingerprint of its exact bytes.
The hash is stored in the manifest, so anyone who downloads the documents later
can tell whether they got the same files the labels were made from.
"""

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from . import config


@dataclass
class FetchResult:
    downloaded: int = 0
    skipped: int = 0  # already on disk and matching the manifest
    changed: list[str] = field(default_factory=list)  # hash differs from the manifest
    failed: list[str] = field(default_factory=list)  # could not be downloaded
    rate_limited: bool = False  # the site said "too many requests"; nothing after that was asked for


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pdf_path(event_slug: str, doc_number: int, pdf_dir: Path = config.PDF_DIR) -> Path:
    return pdf_dir / event_slug / f"doc_{doc_number:03d}.pdf"


def make_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": config.USER_AGENT},
        timeout=config.REQUEST_TIMEOUT_SECONDS,
        follow_redirects=True,
    )


def rule_pdf_path(issue_id: str, pdf_dir: Path = config.RULES_PDF_DIR) -> Path:
    return pdf_dir / f"{issue_id}.pdf"


def fetch_event(
    event: dict,
    client: httpx.Client,
    pdf_dir: Path = config.PDF_DIR,
    delay: float = config.REQUEST_DELAY_SECONDS,
) -> FetchResult:
    """Download every document of one event that is not on disk yet."""
    files = [
        (f"{event['slug']} doc {doc['number']}", doc, pdf_path(event["slug"], doc["number"], pdf_dir))
        for doc in event["docs"]
    ]
    return fetch_files(files, client, delay)


def fetch_rules(
    regulations: dict,
    client: httpx.Client,
    pdf_dir: Path = config.RULES_PDF_DIR,
    delay: float = config.REQUEST_DELAY_SECONDS,
) -> FetchResult:
    """Download every rule document issue in the regulations manifest that is not on disk yet."""
    files = [(issue["id"], issue, rule_pdf_path(issue["id"], pdf_dir)) for issue in regulations["issues"]]
    return fetch_files(files, client, delay)


def fetch_files(files: list[tuple[str, dict, Path]], client: httpx.Client, delay: float) -> FetchResult:
    """Download each (label, manifest entry, path) whose file is not on disk yet.

    An entry is a dict with `url` and `sha256`; the hash is filled in the first time
    a file is seen. Never overwrites a file, and never saves one whose hash contradicts
    the manifest. Stops at the first HTTP 429 and leaves the rest for a later run.
    """
    result = FetchResult()
    for label, doc, path in files:
        if path.exists():
            digest = sha256_of(path.read_bytes())
            if doc["sha256"] is None:
                doc["sha256"] = digest
            if digest == doc["sha256"]:
                result.skipped += 1
            else:
                result.changed.append(label)
            continue  # a file on disk is never downloaded again

        try:
            response = client.get(doc["url"])
        except httpx.HTTPError as error:
            result.failed.append(f"{label}: {type(error).__name__}")
            continue
        finally:
            time.sleep(delay)

        if response.status_code == 429:
            # 429 means "Too Many Requests": the site counts our requests and has had enough
            # for now. Every further request would be refused too and may keep the count
            # high, so stop here. Files already on disk are skipped on the next run.
            result.rate_limited = True
            break

        data = response.content
        if response.status_code != 200 or not data.startswith(b"%PDF"):
            result.failed.append(f"{label}: HTTP {response.status_code}, not a PDF")
            continue

        digest = sha256_of(data)
        if doc["sha256"] is not None and digest != doc["sha256"]:
            # The FIA replaced this document after the manifest was made. Do not keep it:
            # labels built from the old file would silently stop matching.
            result.changed.append(label)
            continue

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        doc["sha256"] = digest
        result.downloaded += 1
    return result
