"""fetch downloads once, records hashes, and refuses files that contradict the manifest.

No test touches the network: httpx.MockTransport answers the requests instead.
"""

import httpx

from f1aisteward import fetch

PDF_A = b"%PDF-1.7 fake document A"
PDF_B = b"%PDF-1.7 fake document B"


def make_event():
    return {
        "slug": "test",
        "docs": [
            {"number": 1, "url": "https://example.test/a.pdf", "sha256": None},
            {"number": 2, "url": "https://example.test/b.pdf", "sha256": None},
        ],
    }


def client_serving(pages: dict[str, bytes], calls: list[str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url) in pages:
            return httpx.Response(200, content=pages[str(request.url)])
        return httpx.Response(404, content=b"not found")

    return httpx.Client(transport=httpx.MockTransport(handler))


PAGES = {"https://example.test/a.pdf": PDF_A, "https://example.test/b.pdf": PDF_B}


def test_first_run_downloads_and_records_hashes(tmp_path):
    event, calls = make_event(), []
    result = fetch.fetch_event(event, client_serving(PAGES, calls), pdf_dir=tmp_path, delay=0)

    assert (result.downloaded, result.skipped) == (2, 0)
    assert (tmp_path / "test" / "doc_001.pdf").read_bytes() == PDF_A
    assert event["docs"][0]["sha256"] == fetch.sha256_of(PDF_A)
    assert event["docs"][1]["sha256"] == fetch.sha256_of(PDF_B)


def test_second_run_makes_no_requests(tmp_path):
    event, calls = make_event(), []
    client = client_serving(PAGES, calls)
    fetch.fetch_event(event, client, pdf_dir=tmp_path, delay=0)
    calls.clear()

    result = fetch.fetch_event(event, client, pdf_dir=tmp_path, delay=0)

    assert (result.downloaded, result.skipped) == (0, 2)
    assert calls == []


def test_a_document_that_changed_upstream_is_not_saved(tmp_path):
    event, calls = make_event(), []
    event["docs"][0]["sha256"] = fetch.sha256_of(b"%PDF-1.7 the file the labels were made from")

    result = fetch.fetch_event(event, client_serving(PAGES, calls), pdf_dir=tmp_path, delay=0)

    assert result.changed == ["test doc 1"]
    assert not (tmp_path / "test" / "doc_001.pdf").exists()
    assert result.downloaded == 1  # the other document is fine


def test_a_local_file_that_differs_is_reported_and_left_alone(tmp_path):
    event, calls = make_event(), []
    event["docs"][0]["sha256"] = fetch.sha256_of(PDF_A)
    path = tmp_path / "test" / "doc_001.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"%PDF-1.7 edited by hand")

    result = fetch.fetch_event(event, client_serving(PAGES, calls), pdf_dir=tmp_path, delay=0)

    assert result.changed == ["test doc 1"]
    assert path.read_bytes() == b"%PDF-1.7 edited by hand"
    assert "https://example.test/a.pdf" not in calls


def test_a_response_that_is_not_a_pdf_counts_as_failed(tmp_path):
    event, calls = make_event(), []
    pages = {"https://example.test/a.pdf": b"<html>blocked</html>"}

    result = fetch.fetch_event(event, client_serving(pages, calls), pdf_dir=tmp_path, delay=0)

    assert len(result.failed) == 2  # one is HTML, the other is a 404
    assert list(tmp_path.rglob("*.pdf")) == []
    assert event["docs"][0]["sha256"] is None
