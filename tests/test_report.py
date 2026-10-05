"""Tests for module 5: writing the reports."""

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from manifest_doctor.report import write_reports
from manifest_doctor.verify import verify

FIXED_TIME = datetime(2026, 10, 5, 18, 32, 5, tzinfo=timezone.utc)
SETTINGS = {"algorithm": "md5", "prefix_mode": "suggest", "name_rules": "windows",
            "hash_extras": False, "fail_on": "error", "severity": {}}
SOURCES = {key: "default" for key in SETTINGS}


def md5(data):
    return hashlib.md5(data).hexdigest()


def sample_result(tmp_path):
    tree = tmp_path / "delivery"
    (tree / "ShowA").mkdir(parents=True)
    (tree / "ShowA" / "a.mov").write_bytes(b"aaa")
    (tree / "ShowA" / "Café.mov").write_bytes(b"ccc")
    (tree / "ShowA" / ".DS_Store").write_bytes(b"x")
    manifest = tmp_path / "m.md5"
    manifest.write_text(f"{md5(b'aaa')}  ShowA/a.mov\n{md5(b'gone')}  ShowA/gone.mov\n"
                        f"{md5(b'ccc')}  ShowA/Café.mov\n", encoding="utf-8")
    return verify(tree, [manifest])


def write(tmp_path, result, sqlite=False, now=FIXED_TIME):
    return write_reports(result, tmp_path / "reports", SETTINGS, SOURCES, exit_code=1, sqlite=sqlite, now=now)


def test_each_run_gets_its_own_dated_folder(tmp_path):
    result = sample_result(tmp_path)
    first = write(tmp_path, result)
    assert first.name == "report-2026-10-05_183205"
    second = write(tmp_path, result)  # same second: must not overwrite the first
    assert second.name == "report-2026-10-05_183205-2"
    assert (first / "report.json").exists() and (second / "report.json").exists()


def test_json_report_has_header_causes_and_findings(tmp_path):
    folder = write(tmp_path, sample_result(tmp_path))
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    header = report["header"]
    assert header["exit_code"] == 1
    assert header["counts"] == {"ERROR": 1, "WARNING": 0, "INFO": 1}
    assert header["settings"]["algorithm"] == {"value": "md5", "source": "default"}
    assert header["manifests"][0]["format"] == "md5sum"
    assert header["run_at"] == "2026-10-05T18:32:05+00:00"
    assert [c["code"] for c in report["causes"]] == ["CAUSE_HIDDEN_NOISE"]
    missing = next(f for f in report["findings"] if f["code"] == "MISSING")
    assert missing["path"] == "ShowA/gone.mov" and missing["line"] == 2


def test_json_keeps_accented_names_readable(tmp_path):
    tree = tmp_path / "delivery"
    tree.mkdir()
    (tree / "Résumé.mov").write_bytes(b"x")  # extra file, so it appears in a finding
    manifest = tmp_path / "m.md5"
    manifest.write_text(f"{md5(b'a')}  a.mov\n", encoding="utf-8")
    folder = write(tmp_path, verify(tree, [manifest]))
    text = (folder / "report.json").read_text(encoding="utf-8")
    assert "Résumé.mov" in text
    assert "\\u00e9" not in text


def test_csv_report_has_one_row_per_finding_and_opens_cleanly_in_excel(tmp_path):
    folder = write(tmp_path, sample_result(tmp_path))
    raw = (folder / "report.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # marker that tells Excel the file is UTF-8
    rows = list(csv.DictReader((folder / "report.csv").read_text(encoding="utf-8-sig").splitlines()))
    assert len(rows) == 2
    assert list(rows[0]) == ["severity", "code", "path", "detail", "manifest", "line",
                             "expected_hash", "actual_hash", "size", "proposed_name"]
    assert rows[0]["severity"] == "ERROR"  # most serious first


def test_markdown_summary_puts_the_result_and_causes_first(tmp_path):
    text = (write(tmp_path, sample_result(tmp_path)) / "summary.md").read_text(encoding="utf-8")
    assert text.index("PROBLEMS FOUND") < text.index("Probable causes") < text.index("Findings")
    assert "Probable cause, not a verdict." in text
    assert "ShowA/gone.mov" in text


def test_summary_shows_the_proposed_clean_name_for_name_problems(tmp_path):
    # Georgi's request after module 5: the suggestion should be visible without opening the CSV.
    tree = tmp_path / "delivery"
    tree.mkdir()
    (tree / "clip  01.mov").write_bytes(b"x")
    manifest = tmp_path / "m.md5"
    manifest.write_text(f"{md5(b'x')}  clip  01.mov\n", encoding="utf-8")
    text = (write(tmp_path, verify(tree, [manifest])) / "summary.md").read_text(encoding="utf-8")
    assert "contains double spaces → proposed name: `clip 01.mov`" in text


def test_long_lists_in_the_summary_are_shortened_with_a_pointer_to_the_full_report(tmp_path):
    tree = tmp_path / "delivery"
    lines = []
    for n in range(30):
        (tree / "Wrap" / "ShowA").mkdir(parents=True, exist_ok=True)
        (tree / "Wrap" / "ShowA" / f"c{n:02d}.mov").write_bytes(b"x")
        lines.append(f"{md5(b'x')}  ShowA/c{n:02d}.mov\n")
    manifest = tmp_path / "m.md5"
    manifest.write_text("".join(lines), encoding="utf-8")
    text = (write(tmp_path, verify(tree, [manifest])) / "summary.md").read_text(encoding="utf-8")
    assert "and 10 more" in text
    assert "report.csv" in text


def test_sqlite_is_written_only_when_asked_and_can_be_queried(tmp_path):
    result = sample_result(tmp_path)
    assert not (write(tmp_path, result) / "findings.sqlite").exists()
    folder = write(tmp_path, result, sqlite=True)
    with sqlite3.connect(folder / "findings.sqlite") as db:
        counts = dict(db.execute("SELECT code, COUNT(*) FROM findings GROUP BY code").fetchall())
        cause_files = db.execute("SELECT path FROM cause_paths WHERE cause_code = 'CAUSE_HIDDEN_NOISE'").fetchall()
    assert counts == {"HIDDEN_FILE": 1, "MISSING": 1}
    assert cause_files == [("ShowA/.DS_Store",)]
