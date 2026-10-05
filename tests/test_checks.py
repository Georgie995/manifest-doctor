"""Tests for module 3b: the individual checks."""

import unicodedata

import pytest

from delivery_verify.checks import (check_cross_sets, check_extra, check_missing, check_names,
                                    check_pairs, check_zero_byte)
from delivery_verify.manifest import Entry, ManifestResult
from delivery_verify.match import Pair
from delivery_verify.scan import FileInfo

H1 = "0" * 32
H2 = "1" * 32
EMPTY_MD5 = "d41d8cd98f00b204e9800998ecf8427e"


def entry(path, digest=H1, size=None, manifest="m.txt", line=1):
    return Entry(path, path, digest, size, manifest, line)


def codes(findings):
    return [f.code for f in findings]


# --- Missing / extra ---------------------------------------------------------------

def test_missing_entries_are_errors_with_manifest_and_line():
    findings = check_missing([entry("ShowA/gone.mov", line=7)])
    assert [(f.code, f.severity, f.path, f.manifest, f.line) for f in findings] == [
        ("MISSING", "ERROR", "ShowA/gone.mov", "m.txt", 7)]


def test_extra_files_are_warnings():
    findings = check_extra([FileInfo("ShowA/surprise.mov", 5)], hashes={})
    assert [(f.code, f.severity, f.path) for f in findings] == [("EXTRA", "WARNING", "ShowA/surprise.mov")]


def test_extra_file_shows_its_hash_when_it_was_hashed():
    findings = check_extra([FileInfo("ShowA/surprise.mov", 5)], hashes={"ShowA/surprise.mov": H2})
    assert findings[0].actual_hash == H2


# --- Hash mismatch -------------------------------------------------------------------

def test_matching_hash_gives_no_finding():
    pair = Pair([entry("a.mov", H1)], FileInfo("a.mov", 10), ["exact"])
    assert check_pairs([pair], {"a.mov": H1}) == []


def test_different_hash_is_an_error_showing_both_hashes_and_size():
    pair = Pair([entry("a.mov", H1, line=3)], FileInfo("a.mov", 10), ["exact"])
    [finding] = check_pairs([pair], {"a.mov": H2})
    assert (finding.code, finding.severity, finding.path) == ("HASH_MISMATCH", "ERROR", "a.mov")
    assert (finding.expected_hash, finding.actual_hash, finding.size) == (H1, H2, 10)
    assert (finding.manifest, finding.line) == ("m.txt", 3)


def test_size_difference_is_reported_as_a_mismatch_even_if_hashes_were_equal():
    pair = Pair([entry("a.mov", H1, size=999)], FileInfo("a.mov", 10), ["exact"])
    [finding] = check_pairs([pair], {"a.mov": H1})
    assert finding.code == "HASH_MISMATCH"
    assert "999" in finding.detail and "10" in finding.detail


def test_file_that_could_not_be_hashed_is_not_also_called_a_mismatch():
    # It already has an UNREADABLE finding; a mismatch would be a second, wrong explanation.
    pair = Pair([entry("a.mov", H1)], FileInfo("a.mov", 10), ["exact"])
    assert check_pairs([pair], hashes={}) == []


def test_each_entry_of_a_duplicated_path_is_checked_separately():
    # The cloud-overwrite case: two entries for one path. The file matches the
    # newer entry, so verification against the older entry fails, as it did for the client.
    pair = Pair([entry("a.mov", H1, line=1), entry("a.mov", H2, line=2)], FileInfo("a.mov", 10), ["exact"])
    findings = check_pairs([pair], {"a.mov": H2})
    assert [(f.code, f.line, f.expected_hash) for f in findings] == [("HASH_MISMATCH", 1, H1)]


# --- Zero-byte -------------------------------------------------------------------------

def test_zero_byte_files_are_errors():
    findings = check_zero_byte([FileInfo("a.mov", 10), FileInfo("empty.mov", 0)], [], "md5")
    assert [(f.code, f.severity, f.path) for f in findings] == [("ZERO_BYTE", "ERROR", "empty.mov")]


def test_zero_byte_detail_says_when_the_manifest_also_expected_an_empty_file():
    # Points at the source: the file was probably already empty when the manifest was made.
    pair = Pair([entry("empty.mov", EMPTY_MD5)], FileInfo("empty.mov", 0), ["exact"])
    [finding] = check_zero_byte([FileInfo("empty.mov", 0)], [pair], "md5")
    assert "already empty" in finding.detail


# --- Name hygiene -------------------------------------------------------------------

def hygiene(paths, rules="windows"):
    return {f.path: f for f in check_names([FileInfo(p, 1) for p in paths], rules)}


def test_clean_names_give_no_findings():
    assert hygiene(["ShowA/Reel01/clip_0001.mov"]) == {}


@pytest.mark.parametrize("bad_name, proposed", [
    ("clip?.mov", "clip_.mov"),          # reserved character
    ("clip*.mov", "clip_.mov"),
    ("clip:01.mov", "clip_01.mov"),
    (" clip.mov", "clip.mov"),           # leading space
    ("clip  01.mov", "clip 01.mov"),     # double space
    ("clip.mov ", "clip.mov"),           # trailing space
    ("clip.", "clip"),                   # trailing full stop
    ("clip\t01.mov", "clip_01.mov"),     # control character (tab)
    ("CON.mov", "CON_.mov"),             # reserved device name
])
def test_bad_names_are_reported_with_a_proposed_clean_name(bad_name, proposed):
    findings = hygiene([f"ShowA/{bad_name}"])
    finding = findings[f"ShowA/{bad_name}"]
    assert (finding.code, finding.severity) == ("NAME_HYGIENE", "WARNING")
    assert finding.proposed_name == proposed


def test_decomposed_unicode_name_is_reported_and_normalised_in_the_proposal():
    nfd = unicodedata.normalize("NFD", "Café.mov")
    finding = hygiene([f"ShowA/{nfd}"])[f"ShowA/{nfd}"]
    assert finding.proposed_name == unicodedata.normalize("NFC", "Café.mov")


def test_a_bad_folder_name_is_reported_once_not_for_every_file_inside():
    findings = hygiene(["Show A /a.mov", "Show A /b.mov"])
    assert list(findings) == ["Show A "]


def test_strict_rules_add_characters_the_windows_rules_allow():
    assert hygiene(["ShowA/clip#01.mov"], rules="windows") == {}
    assert hygiene(["ShowA/clip#01.mov"], rules="strict")["ShowA/clip#01.mov"].proposed_name == "clip_01.mov"


def test_nothing_is_renamed_only_reported(tmp_path):
    bad = tmp_path / "clip  01.mov"
    bad.write_bytes(b"x")
    check_names([FileInfo("clip  01.mov", 1)], "windows")
    assert bad.exists()


# --- Cross-set comparison ------------------------------------------------------------

def manifest(name, *entries):
    return ManifestResult(name, "md5sum", [Entry(p, p, h, None, name, i) for i, (p, h) in enumerate(entries, 1)], [])


def test_paths_are_classified_identical_conflicting_or_unique():
    status, findings = check_cross_sets([
        manifest("tape1.md5", ("a.mov", H1), ("b.mov", H1), ("c.mov", H1)),
        manifest("tape2.md5", ("a.mov", H1), ("b.mov", H2)),
    ])
    assert status == {"a.mov": "identical", "b.mov": "conflicting", "c.mov": "unique"}
    [finding] = findings
    assert (finding.code, finding.severity, finding.path) == ("CROSS_SET_CONFLICT", "ERROR", "b.mov")
    assert "tape1.md5" in finding.detail and "tape2.md5" in finding.detail
    # A finding, not a verdict: the wording must not claim which version is right.
    assert "cannot tell which" in finding.detail


def test_cross_set_check_does_nothing_for_a_single_manifest():
    assert check_cross_sets([manifest("only.md5", ("a.mov", H1))]) == ({}, [])
