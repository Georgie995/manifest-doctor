"""Tests for module 1: reading manifests.

Each test writes a small synthetic manifest into a temporary folder
(pytest's `tmp_path`), reads it, and checks the result.
"""

import pytest

from manifest_doctor.manifest import ManifestError, read_manifest

# A made-up MD5 and SHA-256 value. Only the length and characters matter here.
H1 = "0123456789abcdef0123456789abcdef"
H2 = "fedcba9876543210fedcba9876543210"
SHA = "a" * 64


def write(tmp_path, text, name="manifest.txt", encoding="utf-8"):
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return path


def codes(result):
    return [f.code for f in result.findings]


# --- Format detection -------------------------------------------------------

def test_md5sum_style_is_detected(tmp_path):
    m = write(tmp_path, f"{H1}  ShowA/Reel01/clip_0001.mov\n{H2}  ShowA/Reel01/clip_0002.mov\n")
    result = read_manifest(m)
    assert result.format == "md5sum"
    assert [e.path for e in result.entries] == [
        "ShowA/Reel01/clip_0001.mov",
        "ShowA/Reel01/clip_0002.mov",
    ]
    assert result.entries[0].hash == H1


def test_md5sum_binary_marker_is_accepted(tmp_path):
    # md5sum writes "hash *path" in binary mode
    m = write(tmp_path, f"{H1} *ShowA/clip.mov\n")
    assert read_manifest(m).entries[0].path == "ShowA/clip.mov"


def test_pipe_style_is_detected(tmp_path):
    m = write(tmp_path, f"ShowA/clip_0001.mov|{H1}\n")
    result = read_manifest(m)
    assert result.format == "pipe"
    assert result.entries[0].path == "ShowA/clip_0001.mov"
    assert result.entries[0].hash == H1


def test_csv_with_header_in_any_column_order(tmp_path):
    m = write(tmp_path, f"size,md5,path\n1024,{H1},ShowA/clip_0001.mov\n")
    result = read_manifest(m)
    assert result.format == "csv"
    entry = result.entries[0]
    assert entry.path == "ShowA/clip_0001.mov"
    assert entry.hash == H1
    assert entry.size == 1024


def test_csv_header_names_are_case_insensitive_aliases(tmp_path):
    m = write(tmp_path, f"Checksum,FileName\n{H1},ShowA/clip.mov\n")
    entry = read_manifest(m).entries[0]
    assert (entry.path, entry.hash, entry.size) == ("ShowA/clip.mov", H1, None)


def test_sha256_uses_the_longer_hash_length(tmp_path):
    m = write(tmp_path, f"{SHA}  ShowA/clip.mov\n")
    assert read_manifest(m, algorithm="sha256").entries[0].hash == SHA


# --- Bad lines are reported, never silently skipped -------------------------

def test_unreadable_line_becomes_a_finding_and_the_rest_still_parse(tmp_path):
    m = write(tmp_path, f"{H1}  ShowA/a.mov\nthis is not a manifest line\n{H2}  ShowA/b.mov\n")
    result = read_manifest(m)
    assert [e.path for e in result.entries] == ["ShowA/a.mov", "ShowA/b.mov"]
    assert codes(result) == ["MANIFEST_LINE_UNREADABLE"]
    finding = result.findings[0]
    assert finding.line == 2
    assert finding.severity == "ERROR"


def test_hash_of_wrong_length_is_unreadable(tmp_path):
    m = write(tmp_path, f"{H1}  ShowA/a.mov\nabc123  ShowA/b.mov\n")
    result = read_manifest(m)
    assert [e.path for e in result.entries] == ["ShowA/a.mov"]
    assert codes(result) == ["MANIFEST_LINE_UNREADABLE"]


def test_csv_size_that_is_not_a_number_is_unreadable(tmp_path):
    m = write(tmp_path, f"path,md5,size\nShowA/a.mov,{H1},big\n")
    result = read_manifest(m)
    assert result.entries == []
    assert codes(result) == ["MANIFEST_LINE_UNREADABLE"]


def test_blank_lines_are_ignored(tmp_path):
    m = write(tmp_path, f"\n{H1}  ShowA/a.mov\n\n")
    result = read_manifest(m)
    assert len(result.entries) == 1
    assert result.findings == []


# --- Paths ------------------------------------------------------------------

def test_backslashes_and_leading_dot_slash_are_tidied_but_original_kept(tmp_path):
    m = write(tmp_path, f"{H1}  .\\ShowA\\Reel01\\clip.mov\n")
    entry = read_manifest(m).entries[0]
    assert entry.path == "ShowA/Reel01/clip.mov"
    assert entry.original_path == ".\\ShowA\\Reel01\\clip.mov"


def test_spaces_in_names_are_preserved(tmp_path):
    # Leading and double spaces are a name-hygiene problem to REPORT later,
    # so the reader must not quietly remove them.
    m = write(tmp_path, f"{H1}  ShowA/ clip  0001.mov\n")
    assert read_manifest(m).entries[0].path == "ShowA/ clip  0001.mov"


def test_hash_is_stored_in_lower_case(tmp_path):
    m = write(tmp_path, f"{H1.upper()}  ShowA/a.mov\n")
    assert read_manifest(m).entries[0].hash == H1


# --- Duplicates (Georgi's cloud-overwrite case) ------------------------------

def test_same_path_with_different_hashes_is_a_duplicate_entry_error(tmp_path):
    m = write(tmp_path, f"{H1}  ShowA/a.mov\n{H2}  ShowA/a.mov\n")
    result = read_manifest(m)
    assert codes(result) == ["DUPLICATE_ENTRY"]
    finding = result.findings[0]
    assert finding.severity == "ERROR"
    assert finding.path == "ShowA/a.mov"
    assert H1 in finding.detail and H2 in finding.detail
    # Both versions are kept so later checks can see them
    assert [e.hash for e in result.entries] == [H1, H2]


def test_same_path_with_same_hash_is_collapsed_and_noted(tmp_path):
    m = write(tmp_path, f"{H1}  ShowA/a.mov\n{H1}  ShowA/a.mov\n")
    result = read_manifest(m)
    assert len(result.entries) == 1
    assert codes(result) == ["DUPLICATE_SAME_HASH"]
    assert result.findings[0].severity == "INFO"


# --- Absolute paths ----------------------------------------------------------

ABS = f"{H1}  /Volumes/Drive01/JobX/ShowA/a.mov\n{H2}  /Volumes/Drive01/JobX/ShowA/b.mov\n"


def test_absolute_paths_suggest_mode_reports_the_prefix_and_changes_nothing(tmp_path):
    result = read_manifest(write(tmp_path, ABS), prefix_mode="suggest")
    assert codes(result) == ["ABSOLUTE_PATHS_DETECTED"]
    assert result.suggested_prefix == "/Volumes/Drive01/JobX/ShowA/"
    assert result.entries[0].path == "/Volumes/Drive01/JobX/ShowA/a.mov"
    assert result.stripped_prefix is None


def test_absolute_paths_auto_mode_strips_and_records_it(tmp_path):
    result = read_manifest(write(tmp_path, ABS), prefix_mode="auto")
    assert [e.path for e in result.entries] == ["a.mov", "b.mov"]
    assert result.stripped_prefix == "/Volumes/Drive01/JobX/ShowA/"
    assert codes(result) == []


def test_absolute_paths_off_mode_leaves_them_alone(tmp_path):
    result = read_manifest(write(tmp_path, ABS), prefix_mode="off")
    assert result.entries[0].path == "/Volumes/Drive01/JobX/ShowA/a.mov"
    assert codes(result) == []


def test_explicit_strip_prefix_wins_over_the_mode(tmp_path):
    result = read_manifest(write(tmp_path, ABS), prefix_mode="suggest",
                           strip_prefix="/Volumes/Drive01/JobX/")
    assert [e.path for e in result.entries] == ["ShowA/a.mov", "ShowA/b.mov"]
    assert result.stripped_prefix == "/Volumes/Drive01/JobX/"
    assert codes(result) == []


def test_windows_drive_letter_paths_count_as_absolute(tmp_path):
    m = write(tmp_path, f"{H1}  D:\\Deliveries\\ShowA\\a.mov\n{H2}  D:\\Deliveries\\ShowA\\b.mov\n")
    result = read_manifest(m, prefix_mode="suggest")
    assert result.suggested_prefix == "D:/Deliveries/ShowA/"


# --- Problems with the manifest file itself are tool errors (exit code 2) ----

def test_empty_manifest_is_a_tool_error(tmp_path):
    with pytest.raises(ManifestError):
        read_manifest(write(tmp_path, "\n\n"))


def test_manifest_with_no_recognisable_lines_is_a_tool_error(tmp_path):
    with pytest.raises(ManifestError):
        read_manifest(write(tmp_path, "hello\nworld\n"))


def test_utf8_byte_order_mark_is_handled(tmp_path):
    m = write(tmp_path, f"{H1}  ShowA/a.mov\n", encoding="utf-8-sig")
    assert read_manifest(m).entries[0].hash == H1


def test_non_utf8_manifest_is_a_tool_error(tmp_path):
    m = tmp_path / "manifest.txt"
    m.write_bytes(f"{H1}  ShowA/caf\xe9.mov\n".encode("latin-1"))
    with pytest.raises(ManifestError):
        read_manifest(m)
