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


def test_fetch_stops_at_the_first_429(tmp_path):
    # The site answers the second request with 429 "Too Many Requests".
    event, calls = make_event(), []
    event["docs"].append({"number": 3, "url": "https://example.test/c.pdf", "sha256": None})

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) >= 2:
            return httpx.Response(429, content=b"<html>Just a moment...</html>")
        return httpx.Response(200, content=PDF_A)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = fetch.fetch_event(event, client, pdf_dir=tmp_path, delay=0)

    assert result.rate_limited
    assert result.downloaded == 1
    assert result.failed == []  # a refused request is not a broken document
    assert calls == ["https://example.test/a.pdf", "https://example.test/b.pdf"]  # the third was never asked for
    assert event["docs"][1]["sha256"] is None


def test_a_run_after_a_429_continues_where_it_stopped(tmp_path):
    event, calls = make_event(), []
    refuse_everything = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(429)))
    assert fetch.fetch_event(event, refuse_everything, pdf_dir=tmp_path, delay=0).rate_limited

    result = fetch.fetch_event(event, client_serving(PAGES, calls), pdf_dir=tmp_path, delay=0)

    assert (result.downloaded, result.rate_limited) == (2, False)


def test_the_command_stops_at_a_429_and_says_how_many_are_left(monkeypatch):
    from typer.testing import CliRunner

    from f1aisteward import cli, manifest

    def docs(*numbers):
        return [{"number": n, "url": f"https://example.test/{n}.pdf", "sha256": None} for n in numbers]

    data = {
        "season": 2031,
        "events": [{"slug": "made-up-event-a", "docs": docs(1, 2)}, {"slug": "made-up-event-b", "docs": docs(3)}],
    }
    calls = []

    def refuse(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(429)

    monkeypatch.setattr(manifest, "load", lambda: data)
    monkeypatch.setattr(manifest, "save", lambda manifest_data: None)
    monkeypatch.setattr(fetch.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(fetch, "make_client", lambda: httpx.Client(transport=httpx.MockTransport(refuse)))

    result = CliRunner().invoke(cli.app, ["fetch"])

    assert result.exit_code == 1
    assert calls == ["https://example.test/1.pdf"]  # one refusal, then nothing: not the second event either
    assert "3 decisions are still to download" in result.output
