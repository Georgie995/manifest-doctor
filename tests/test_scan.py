"""Tests for module 2, part 1: scanning the folder ("what is here")."""

import pytest

from delivery_verify import scan
from delivery_verify.scan import ScanError, scan_tree


def make(tmp_path, relative, content=b"data"):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_lists_every_file_with_relative_path_and_size_in_sorted_order(tmp_path):
    make(tmp_path, "ShowA/Reel02/clip_0003.mov", b"12345")
    make(tmp_path, "ShowA/Reel01/clip_0001.mov", b"1")
    make(tmp_path, "ShowA/Reel01/clip_0002.mov", b"12")
    result = scan_tree(tmp_path)
    assert [(f.path, f.size) for f in result.files] == [
        ("ShowA/Reel01/clip_0001.mov", 1),
        ("ShowA/Reel01/clip_0002.mov", 2),
        ("ShowA/Reel02/clip_0003.mov", 5),
    ]
    assert result.findings == []


def test_paths_use_forward_slashes_on_every_system(tmp_path):
    make(tmp_path, "ShowA/Reel01/clip.mov")
    assert scan_tree(tmp_path).files[0].path == "ShowA/Reel01/clip.mov"


def test_zero_byte_files_are_listed_with_size_zero(tmp_path):
    # Flagging them is a check (module 3). The scan must just not lose them.
    make(tmp_path, "ShowA/empty.mov", b"")
    assert [(f.path, f.size) for f in scan_tree(tmp_path).files] == [("ShowA/empty.mov", 0)]


@pytest.mark.parametrize("hidden_path", [
    "ShowA/.DS_Store",
    "ShowA/Thumbs.db",
    "ShowA/desktop.ini",
    "ShowA/._clip_0001.mov",              # macOS AppleDouble companion file
    ".Spotlight-V100/Store-V2/index",     # anything inside a system folder
    ".Trashes/501/old.mov",
    ".fseventsd/0000001",
])
def test_system_and_hidden_files_are_set_aside_and_noted(tmp_path, hidden_path):
    make(tmp_path, "ShowA/clip_0001.mov")
    make(tmp_path, hidden_path)
    result = scan_tree(tmp_path)
    assert [f.path for f in result.files] == ["ShowA/clip_0001.mov"]
    assert [f.path for f in result.hidden] == [hidden_path]
    assert [(f.code, f.severity, f.path) for f in result.findings] == [
        ("HIDDEN_FILE", "INFO", hidden_path)
    ]


def test_hidden_file_list_can_be_changed(tmp_path):
    make(tmp_path, "ShowA/clip.mov")
    make(tmp_path, "ShowA/notes.tmp")
    result = scan_tree(tmp_path, hidden_names=("notes.tmp",), hidden_prefixes=(), hidden_folders=())
    assert [f.path for f in result.files] == ["ShowA/clip.mov"]
    assert [f.path for f in result.hidden] == ["ShowA/notes.tmp"]


def test_an_ordinary_dot_file_is_not_treated_as_a_system_file(tmp_path):
    # Only the configured list is set aside. Anything else must be checked like a normal file.
    make(tmp_path, "ShowA/.hidden_clip.mov")
    assert [f.path for f in scan_tree(tmp_path).files] == ["ShowA/.hidden_clip.mov"]


def test_folder_that_cannot_be_listed_is_reported_and_the_scan_continues(tmp_path, monkeypatch):
    make(tmp_path, "ShowA/clip.mov")
    real_walk = scan.os.walk

    def walk_with_a_locked_folder(top, onerror=None, **kwargs):
        # Pretend one folder refused to open, then carry on with the real walk.
        error = PermissionError(13, "Permission denied", str(tmp_path / "Locked"))
        onerror(error)
        yield from real_walk(top, onerror=onerror, **kwargs)

    monkeypatch.setattr(scan.os, "walk", walk_with_a_locked_folder)
    result = scan_tree(tmp_path)
    assert [f.path for f in result.files] == ["ShowA/clip.mov"]
    assert [(f.code, f.path) for f in result.findings] == [("UNREADABLE", "Locked")]
    assert "Permission denied" in result.findings[0].detail


def test_file_whose_size_cannot_be_read_is_reported_and_the_scan_continues(tmp_path, monkeypatch):
    make(tmp_path, "ShowA/a.mov")
    make(tmp_path, "ShowA/b.mov")
    real_size = scan._file_size

    def size_fails_for_b(path):
        if path.name == "b.mov":
            raise PermissionError(13, "Permission denied")
        return real_size(path)

    monkeypatch.setattr(scan, "_file_size", size_fails_for_b)
    result = scan_tree(tmp_path)
    assert [f.path for f in result.files] == ["ShowA/a.mov"]
    assert [(f.code, f.path) for f in result.findings] == [("UNREADABLE", "ShowA/b.mov")]


def test_missing_folder_is_a_tool_error(tmp_path):
    with pytest.raises(ScanError):
        scan_tree(tmp_path / "does_not_exist")


def test_a_file_instead_of_a_folder_is_a_tool_error(tmp_path):
    with pytest.raises(ScanError):
        scan_tree(make(tmp_path, "clip.mov"))
