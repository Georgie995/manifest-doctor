"""Acceptance test: the generated sample delivery contains one deliberate example of
every finding code and every probable cause. The tool must find exactly those, nothing else.
"""

import unicodedata

from delivery_verify import hashing
from delivery_verify.findings import DEFAULT_SEVERITY
from delivery_verify.verify import verify
from tools.make_fixtures import build_fixtures

NFD_CAFE = unicodedata.normalize("NFD", "ShowA/Audio/Café_stem.wav")

EXPECTED_FINDINGS = sorted([
    ("CASE_ONLY_MATCH", "ShowA/Audio/Dialogue_Stem.wav"),
    ("CROSS_SET_CONFLICT", "ShowA/Reel01/clip_0001.mov"),
    ("DUPLICATE_ENTRY", "ShowA/Reel01/clip_0004.mov"),
    ("DUPLICATE_SAME_HASH", "ShowA/Reel01/clip_0005.mov"),
    ("EXTRA", "ShowA/Reel01/extra_0007.mov"),
    ("HASH_MISMATCH", "ShowA/Reel01/clip_0001.mov"),   # against the second set's entry
    ("HASH_MISMATCH", "ShowA/Reel01/clip_0002.mov"),   # changed after the manifest was made
    ("HASH_MISMATCH", "ShowA/Reel01/clip_0004.mov"),   # matches the newer duplicate, not the older
    ("HIDDEN_FILE", "ShowA/Reel01/.DS_Store"),
    ("MANIFEST_LINE_UNREADABLE", None),
    ("MISSING", "ShowA/Reel01/clip_0006.mov"),
    ("NAME_HYGIENE", "ShowA/Docs/ notes.txt"),
    ("PREFIX_OFFSET_MATCH", "Wrapper_Folder/Reel09/clip_0009.mov"),
    ("UNICODE_ONLY_MATCH", NFD_CAFE),
    ("UNREADABLE", "ShowA/Reel01/locked.mov"),
    ("ZERO_BYTE", "ShowA/Reel01/clip_0003.mov"),
], key=str)

EXPECTED_CAUSES = ["CAUSE_DUPLICATE_LISTING", "CAUSE_WRAPPER_FOLDER", "CAUSE_UNICODE_FORM",
                   "CAUSE_CASE_ONLY", "CAUSE_HIDDEN_NOISE"]

# Covered elsewhere because the command line stops before a report is made (test_cli.py).
TESTED_ELSEWHERE = {"ABSOLUTE_PATHS_DETECTED"}


def run_on_fixtures(tmp_path, monkeypatch):
    fixtures = build_fixtures(tmp_path)
    real_hash_file = hashing.hash_file

    def locked_file_cannot_be_read(path, algorithm, chunk_size=hashing.CHUNK_SIZE):
        # A real locked file behaves differently on each OS, so the lock is simulated.
        if path.name == "locked.mov":
            raise PermissionError(13, "Permission denied")
        return real_hash_file(path, algorithm, chunk_size)

    monkeypatch.setattr(hashing, "hash_file", locked_file_cannot_be_read)
    return verify(fixtures["tree"], fixtures["manifests"])


def test_every_planted_problem_is_found_and_nothing_else(tmp_path, monkeypatch):
    result = run_on_fixtures(tmp_path, monkeypatch)
    assert sorted(((f.code, f.path) for f in result.findings), key=str) == EXPECTED_FINDINGS


def test_every_planted_cause_is_found_in_order(tmp_path, monkeypatch):
    result = run_on_fixtures(tmp_path, monkeypatch)
    assert [c.code for c in result.causes] == EXPECTED_CAUSES


def test_the_fixtures_cover_every_finding_code_the_tool_has(tmp_path, monkeypatch):
    # If someone adds a new finding code, this fails until the fixtures include an example of it.
    found = {f.code for f in run_on_fixtures(tmp_path, monkeypatch).findings}
    assert found | TESTED_ELSEWHERE == set(DEFAULT_SEVERITY)


def test_a_clean_copy_of_the_fixtures_has_no_findings(tmp_path):
    fixtures = build_fixtures(tmp_path, clean=True)
    result = verify(fixtures["tree"], fixtures["manifests"])
    assert result.findings == [] and result.causes == []
