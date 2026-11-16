"""`build --decisions` counts every document once and keeps FIA text out of the labels file.

No real PDF is read: empty files stand in for the PDFs and a fake `extract_text` returns
made-up text for each of them.
"""

import json

from decision_text import SINGLE_CAR_FIELDS, form, without

from f1aisteward import fetch
from f1aisteward.parse import build

TEXTS = {
    1: form(SINGLE_CAR_FIELDS),
    2: "The Stewards have received a request from Northwind Racing to let car 7 start.\n",
    3: form(without(SINGLE_CAR_FIELDS, "Decision", "Reason")),  # a broken document
    4: "A notice about the paddock opening hours.\n",
    # 5 is in the manifest but was never downloaded
}


def make_manifest():
    docs = [{"number": n, "url": f"https://example.test/{n}.pdf", "sha256": f"hash{n}"} for n in (1, 2, 3, 4, 5)]
    return {"season": 2031, "events": [{"slug": "example", "round": 1, "date": "2031-06-01", "docs": docs}]}


def run_build(tmp_path):
    for number in TEXTS:
        path = fetch.pdf_path("example", number, tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF stand-in")

    def fake_extract_text(path):
        return TEXTS[int(path.stem.removeprefix("doc_"))]

    return build.build_decisions(make_manifest(), pdf_dir=tmp_path, extract_text=fake_extract_text)


def test_every_document_is_counted_exactly_once(tmp_path):
    report = run_build(tmp_path)

    assert report.total == 5
    assert [record["id"] for record in report.records] == ["2031-example-001"]
    assert dict(report.left_out) == {"permission": 1}
    assert report.not_downloaded == ["2031-example-005"]
    assert len(report.failed) == 2
    assert report.failed[0] == "2031-example-003: missing decision"
    assert report.failed[1].startswith("2031-example-004: no fields found")
    assert len(report.records) + sum(report.left_out.values()) + len(report.failed) + len(report.not_downloaded) == report.total


def test_a_pdf_that_cannot_be_read_is_a_failure_not_a_crash(tmp_path):
    path = fetch.pdf_path("example", 1, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a pdf")

    def broken_extract_text(path):
        raise ValueError("damaged file")

    report = build.build_decisions(make_manifest(), pdf_dir=tmp_path, extract_text=broken_extract_text)
    assert report.failed == ["2031-example-001: cannot read the PDF (ValueError)"]


def test_record_and_label_carry_the_same_labels(tmp_path):
    report = run_build(tmp_path)
    record, label = report.records[0], report.labels[0]

    assert record["articles"] == label["articles"] == ["F1-B:1.2.3"]
    assert record["penalty"] == label["penalty"] == {"type": "time_penalty", "value": 5, "unit": "s"}
    assert label["sha256"] == "hash1"
    assert label["split"] is None


def test_labels_file_holds_no_text_from_the_document(tmp_path):
    report = run_build(tmp_path)
    build.write(report, parsed_path=tmp_path / "parsed.jsonl", labels_path=tmp_path / "labels.jsonl")

    parsed_text = (tmp_path / "parsed.jsonl").read_text(encoding="utf-8")
    labels_text = (tmp_path / "labels.jsonl").read_text(encoding="utf-8")
    assert "pushed Car 8 wide" in parsed_text  # the local file has the Fact
    for words in ("pushed Car 8 wide", "Ada Example", "watched the video", "second time penalty"):
        assert words not in labels_text

    label = json.loads(labels_text.splitlines()[0])
    assert set(label) == {"id", "event", "number", "url", "sha256", "articles", "penalty", "kind", "split"}


def test_summary_reports_the_counts(tmp_path):
    text = build.summary(run_build(tmp_path))
    assert "Decisions in the manifest        5" in text
    assert "2031-example-003: missing decision" in text
