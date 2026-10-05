"""Tests for module 3a: pairing manifest entries with real files.

Matching only compares names, so these tests use plain lists. No files on
disk are needed. That is how case-only differences can be tested on Windows,
whose filesystem can't hold two names that differ only by case.
"""

import unicodedata

from delivery_verify.manifest import Entry
from delivery_verify.match import match_files
from delivery_verify.scan import FileInfo

H1 = "0" * 32
H2 = "1" * 32


def entry(path, digest=H1, line=1, manifest="m.txt"):
    return Entry(path, path, digest, None, manifest, line)


def file(path, size=10):
    return FileInfo(path, size)


def summary(result):
    """Pairs as (manifest path, disk path, kinds), plus what is left over."""
    return (
        sorted((p.entries[0].path, p.file.path, tuple(p.kinds)) for p in result.pairs),
        sorted(e.path for e in result.missing),
        sorted(f.path for f in result.extra),
    )


def codes(result):
    return sorted(f.code for f in result.findings)


# --- Pass 1: exact ------------------------------------------------------------

def test_exact_names_are_paired():
    result = match_files([entry("ShowA/a.mov"), entry("ShowA/b.mov")],
                         [file("ShowA/a.mov"), file("ShowA/b.mov")])
    assert summary(result) == (
        [("ShowA/a.mov", "ShowA/a.mov", ("exact",)), ("ShowA/b.mov", "ShowA/b.mov", ("exact",))],
        [], [],
    )
    assert result.findings == []


def test_what_cannot_be_paired_is_missing_or_extra():
    result = match_files([entry("ShowA/a.mov"), entry("ShowA/gone.mov")],
                         [file("ShowA/a.mov"), file("ShowA/surprise.mov")])
    assert summary(result)[1:] == (["ShowA/gone.mov"], ["ShowA/surprise.mov"])


# --- Pass 2: same name, written differently --------------------------------------

CAFE_NFC = unicodedata.normalize("NFC", "ShowA/Café.mov")  # é as one character
CAFE_NFD = unicodedata.normalize("NFD", "ShowA/Café.mov")  # e + combining accent (typical of macOS)


def test_unicode_form_difference_is_paired_and_flagged():
    assert CAFE_NFC != CAFE_NFD  # same look, different characters
    result = match_files([entry(CAFE_NFC)], [file(CAFE_NFD)])
    assert summary(result) == ([(CAFE_NFC, CAFE_NFD, ("unicode",))], [], [])
    assert codes(result) == ["UNICODE_ONLY_MATCH"]
    assert result.findings[0].path == CAFE_NFD
    # Georgi's review: explain the difference in words, since the two names look identical.
    detail = result.findings[0].detail
    assert "manifest writes é as one character" in detail
    assert "disk writes it as a letter plus a separate accent mark" in detail


def test_unicode_wording_follows_the_direction_of_the_difference():
    result = match_files([entry(CAFE_NFD)], [file(CAFE_NFC)])
    detail = result.findings[0].detail
    assert "disk writes é as one character" in detail
    assert "manifest writes it as a letter plus a separate accent mark" in detail


def test_case_only_difference_is_paired_and_flagged():
    result = match_files([entry("ShowA/Clip_0001.MOV")], [file("ShowA/clip_0001.mov")])
    assert summary(result) == ([("ShowA/Clip_0001.MOV", "ShowA/clip_0001.mov", ("case",))], [], [])
    assert codes(result) == ["CASE_ONLY_MATCH"]


def test_unicode_and_case_difference_together_gives_both_findings():
    upper_nfc = unicodedata.normalize("NFC", "ShowA/CAFÉ.mov")
    result = match_files([entry(upper_nfc)], [file(CAFE_NFD)])
    assert summary(result) == ([(upper_nfc, CAFE_NFD, ("unicode", "case"))], [], [])
    assert codes(result) == ["CASE_ONLY_MATCH", "UNICODE_ONLY_MATCH"]


def test_ambiguous_case_match_is_not_guessed():
    # Two files on a case-sensitive disk, and the manifest matches neither exactly.
    # Picking one would be a guess, so all three are left for a person to look at.
    result = match_files([entry("ShowA/CLIP.mov")], [file("ShowA/Clip.mov"), file("ShowA/clip.mov")])
    assert summary(result) == ([], ["ShowA/CLIP.mov"], ["ShowA/Clip.mov", "ShowA/clip.mov"])


# --- Pass 3: shifted by a folder (wrapper folder) ----------------------------------

def test_extra_wrapper_folder_on_disk_is_paired_and_flagged():
    result = match_files(
        [entry("Reel01/a.mov"), entry("Reel01/b.mov")],
        [file("JobX/Reel01/a.mov"), file("JobX/Reel01/b.mov")])
    assert summary(result) == (
        [("Reel01/a.mov", "JobX/Reel01/a.mov", ("prefix",)),
         ("Reel01/b.mov", "JobX/Reel01/b.mov", ("prefix",))],
        [], [],
    )
    assert codes(result) == ["PREFIX_OFFSET_MATCH", "PREFIX_OFFSET_MATCH"]
    pair = result.pairs[0]
    assert (pair.prefix, pair.direction) == ("JobX/", "extra_folder_on_disk")


def test_extra_folder_in_the_manifest_is_paired_and_flagged():
    result = match_files([entry("JobX/Reel01/a.mov")], [file("Reel01/a.mov")])
    assert summary(result) == ([("JobX/Reel01/a.mov", "Reel01/a.mov", ("prefix",))], [], [])
    pair = result.pairs[0]
    assert (pair.prefix, pair.direction) == ("JobX/", "extra_folder_in_manifest")


def test_ambiguous_folder_shift_is_not_guessed():
    # "a.mov" could be either file, so it isn't paired with either.
    result = match_files([entry("a.mov")], [file("Reel01/a.mov"), file("Reel02/a.mov")])
    assert summary(result) == ([], ["a.mov"], ["Reel01/a.mov", "Reel02/a.mov"])


def test_exact_match_wins_before_any_folder_shift_is_tried():
    result = match_files([entry("a.mov")], [file("a.mov"), file("JobX/a.mov")])
    assert summary(result) == ([("a.mov", "a.mov", ("exact",))], [], ["JobX/a.mov"])


def test_each_file_is_paired_at_most_once():
    # Both manifest entries could end with this disk path; the more specific one wins.
    result = match_files([entry("Reel01/a.mov"), entry("a.mov")], [file("JobX/Reel01/a.mov")])
    assert summary(result) == (
        [("Reel01/a.mov", "JobX/Reel01/a.mov", ("prefix",))], ["a.mov"], [])


# --- Several entries for one path ------------------------------------------------

def test_all_entries_for_the_same_path_share_one_pair():
    # e.g. the same path listed with two hashes (DUPLICATE_ENTRY) or in two manifests
    result = match_files([entry("ShowA/a.mov", H1, line=1), entry("ShowA/a.mov", H2, line=2)],
                         [file("ShowA/a.mov")])
    assert len(result.pairs) == 1
    assert [e.hash for e in result.pairs[0].entries] == [H1, H2]
