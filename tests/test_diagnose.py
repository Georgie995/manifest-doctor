"""Tests for module 4: grouping findings into probable causes."""

import hashlib

from delivery_verify.diagnose import diagnose
from delivery_verify.findings import make_finding
from delivery_verify.manifest import Entry
from delivery_verify.match import MatchResult, Pair
from delivery_verify.scan import FileInfo, ScanResult
from delivery_verify.verify import verify

H1 = "0" * 32


def pair(manifest_path, disk_path, kinds, prefix=None, direction=None):
    return Pair([Entry(manifest_path, manifest_path, H1, None, "m.txt", 1)],
                FileInfo(disk_path, 1), kinds, prefix, direction)


def run(pairs=(), hidden=(), findings=()):
    match = MatchResult(pairs=list(pairs), missing=[], extra=[])
    scan = ScanResult(files=[], hidden=[FileInfo(p, 1) for p in hidden], findings=[])
    return diagnose(match, scan, list(findings))


def test_clean_result_has_no_causes():
    assert run(pairs=[pair("a.mov", "a.mov", ["exact"])]) == []


def test_files_shifted_by_the_same_folder_become_one_wrapper_cause():
    pairs = [pair(f"Reel01/clip_{n}.mov", f"JobX/Reel01/clip_{n}.mov", ["prefix"], "JobX/", "extra_folder_on_disk")
             for n in range(1, 6)]
    [cause] = run(pairs=pairs)
    assert cause.code == "CAUSE_WRAPPER_FOLDER"
    assert cause.severity == "WARNING"
    assert cause.paths == [f"JobX/Reel01/clip_{n}.mov" for n in range(1, 6)]
    assert "5 files" in cause.summary
    assert "'JobX/'" in cause.summary
    assert "extra top-level folder" in cause.summary


def test_extra_folder_in_the_manifest_is_described_the_other_way_round():
    [cause] = run(pairs=[pair("JobX/a.mov", "a.mov", ["prefix"], "JobX/", "extra_folder_in_manifest")])
    assert "1 file " in cause.summary
    assert "manifest" in cause.summary


def test_different_folders_give_separate_causes():
    causes = run(pairs=[
        pair("a.mov", "JobX/a.mov", ["prefix"], "JobX/", "extra_folder_on_disk"),
        pair("b.mov", "JobY/b.mov", ["prefix"], "JobY/", "extra_folder_on_disk"),
    ])
    assert sorted(c.summary.split("'")[1] for c in causes) == ["JobX/", "JobY/"]


def test_unicode_and_case_differences_each_become_one_cause():
    causes = run(pairs=[
        pair("Café.mov", "Café.mov", ["unicode"]),
        pair("Résumé.wav", "Résumé.wav", ["unicode"]),
        pair("Clip.mov", "clip.mov", ["case"]),
    ])
    by_code = {c.code: c for c in causes}
    assert set(by_code) == {"CAUSE_UNICODE_FORM", "CAUSE_CASE_ONLY"}
    assert len(by_code["CAUSE_UNICODE_FORM"].paths) == 2
    assert "macOS" in by_code["CAUSE_UNICODE_FORM"].summary
    assert by_code["CAUSE_CASE_ONLY"].paths == ["clip.mov"]


def test_wording_is_grammatical_for_a_single_file():
    causes = run(pairs=[pair("Café.mov", "Café.mov", ["unicode"]), pair("Clip.mov", "clip.mov", ["case"])])
    assert all("1 file name differs" in c.summary for c in causes)
    for direction in ("extra_folder_on_disk", "extra_folder_in_manifest"):
        [wrapper] = run(pairs=[pair("a.mov", "JobX/a.mov", ["prefix"], "JobX/", direction)])
        assert wrapper.summary.startswith("1 file only matches once")
    [hidden] = run(hidden=["ShowA/.DS_Store"])
    assert hidden.summary.startswith("1 system file was set aside (it would otherwise have counted as an extra file)")


def test_a_name_with_both_differences_appears_in_both_causes():
    causes = run(pairs=[pair("CAFÉ.mov", "café.mov", ["unicode", "case"])])
    assert sorted(c.code for c in causes) == ["CAUSE_CASE_ONLY", "CAUSE_UNICODE_FORM"]


def test_hidden_files_become_one_noise_cause():
    [cause] = run(hidden=["ShowA/.DS_Store", "ShowA/Thumbs.db"])
    assert (cause.code, cause.severity) == ("CAUSE_HIDDEN_NOISE", "INFO")
    assert "2 system files" in cause.summary


def test_duplicate_listings_become_one_error_cause():
    findings = [make_finding("DUPLICATE_ENTRY", path="a.mov"), make_finding("DUPLICATE_ENTRY", path="b.mov")]
    [cause] = run(findings=findings)
    assert (cause.code, cause.severity) == ("CAUSE_DUPLICATE_LISTING", "ERROR")
    assert cause.paths == ["a.mov", "b.mov"]
    assert "Check which version was intended" in cause.summary


def test_every_cause_is_labelled_a_hint_not_a_verdict():
    causes = run(
        pairs=[pair("a.mov", "JobX/a.mov", ["prefix"], "JobX/", "extra_folder_on_disk"),
               pair("Café.mov", "Café.mov", ["unicode"])],
        hidden=["ShowA/.DS_Store"],
        findings=[make_finding("DUPLICATE_ENTRY", path="b.mov")])
    assert len(causes) == 4
    assert all(c.note == "Probable cause, not a verdict." for c in causes)


def test_causes_are_ordered_most_serious_first():
    causes = run(
        pairs=[pair("a.mov", "JobX/a.mov", ["prefix"], "JobX/", "extra_folder_on_disk")],
        hidden=["ShowA/.DS_Store"],
        findings=[make_finding("DUPLICATE_ENTRY", path="b.mov")])
    assert [c.severity for c in causes] == ["ERROR", "WARNING", "INFO"]


def test_verify_attaches_causes_for_a_wrapped_delivery(tmp_path):
    tree = tmp_path / "delivery"
    lines = []
    for n in range(1, 4):
        content = f"clip {n}".encode()
        path = tree / "JobX_Delivery" / "ShowA" / f"clip_{n}.mov"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        lines.append(f"{hashlib.md5(content).hexdigest()}  ShowA/clip_{n}.mov\n")
    manifest = tmp_path / "m.md5"
    manifest.write_text("".join(lines), encoding="utf-8")
    [cause] = verify(tree, [manifest]).causes
    assert cause.code == "CAUSE_WRAPPER_FOLDER"
    assert "3 files" in cause.summary
