"""Making a checksum list from the source, before a copy (approved by Georgi 2026-10-20).

When the copy method writes no list of its own, the list must come from the SOURCE: a list made from
the copy after it lands can never catch a bad copy (it only proves nothing changed afterwards).
Georgi's answers Q3 and Q4 in his automation research. Every folder here is synthetic.
"""

import hashlib
import os
import shutil
import sys

import pytest

from manifest_doctor import hashing, make
from manifest_doctor.cli import main
from manifest_doctor.findings import make_finding
from manifest_doctor.scan import ScanResult


def md5(data):
    return hashlib.md5(data).hexdigest()


@pytest.fixture
def source(tmp_path):
    """A small source with folders, a non-English name and some system clutter."""
    root = tmp_path / "source"
    (root / "Reel01").mkdir(parents=True)
    (root / "Reel02").mkdir()
    (root / "Reel01" / "a.mov").write_bytes(b"picture a")
    (root / "Reel01" / "b.mov").write_bytes(b"picture b")
    (root / "Reel02" / "café.wav").write_bytes(b"sound")
    (root / "Reel01" / ".DS_Store").write_bytes(b"clutter")
    (root / "Thumbs.db").write_bytes(b"clutter")
    return root


def snapshot(root):
    return sorted((str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*"))


# --- The list ------------------------------------------------------------------------------------

def test_writes_an_md5sum_style_list_of_every_file_sorted(source, tmp_path, capsys):
    out = tmp_path / "lists" / "source.md5"
    assert main(["make", str(source), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").splitlines() == [
        f"{md5(b'picture a')}  Reel01/a.mov",
        f"{md5(b'picture b')}  Reel01/b.mov",
        f"{md5(b'sound')}  Reel02/café.wav",
    ]
    printed = capsys.readouterr().out
    assert "LIST WRITTEN: 3 files" in printed and "2 system files left out" in printed


def test_sha256_when_asked(source, tmp_path):
    out = tmp_path / "source.sha256"
    assert main(["make", str(source), "--out", str(out), "--algorithm", "sha256"]) == 0
    assert out.read_text(encoding="utf-8").splitlines()[0] == \
        f"{hashlib.sha256(b'picture a').hexdigest()}  Reel01/a.mov"


def test_says_what_the_list_proves_and_what_it_does_not(source, tmp_path, capsys):
    main(["make", str(source), "--out", str(tmp_path / "s.md5")])
    printed = capsys.readouterr().out
    assert "made from the source" in printed
    assert "not that any copy matches" in printed


def test_the_source_is_never_changed(source, tmp_path):
    before = snapshot(source)
    main(["make", str(source), "--out", str(tmp_path / "s.md5")])
    assert snapshot(source) == before


# --- The point of it: the list catches a bad copy ------------------------------------------------

def test_a_good_copy_checks_clean_against_the_source_list(source, tmp_path):
    out = tmp_path / "source.md5"
    main(["make", str(source), "--out", str(out)])
    copy = tmp_path / "copy"
    shutil.copytree(source, copy)
    assert main(["check", str(copy), "--manifest", str(out), "--out", str(tmp_path / "reports")]) == 0


def test_a_bad_copy_is_caught_by_the_source_list(source, tmp_path):
    out = tmp_path / "source.md5"
    main(["make", str(source), "--out", str(out)])
    copy = tmp_path / "copy"
    shutil.copytree(source, copy)
    (copy / "Reel01" / "b.mov").write_bytes(b"picture B")   # same size, different content
    (copy / "Reel02" / "café.wav").unlink()
    assert main(["check", str(copy), "--manifest", str(out), "--out", str(tmp_path / "reports")]) == 1


# --- Never a partial or misleading list ----------------------------------------------------------

def test_an_unreadable_source_file_means_no_list(source, tmp_path, monkeypatch, capsys):
    real = hashing.hash_file

    def flaky(path, *args, **kwargs):
        if path.name == "b.mov":
            raise PermissionError(13, "Permission denied")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(hashing, "hash_file", flaky)
    out = tmp_path / "source.md5"
    assert main(["make", str(source), "--out", str(out)]) == 2
    assert not out.exists()
    err = capsys.readouterr().err
    assert "Reel01/b.mov" in err and "Permission denied" in err and "no list was written" in err


def test_an_unreadable_source_folder_means_no_list(source, tmp_path, monkeypatch, capsys):
    finding = make_finding("UNREADABLE", path="Reel03", detail="folder could not be listed: Permission denied")
    monkeypatch.setattr(make, "scan_tree", lambda root: ScanResult([], [], [finding]))
    out = tmp_path / "source.md5"
    assert main(["make", str(source), "--out", str(out)]) == 2
    assert not out.exists()
    assert "Reel03" in capsys.readouterr().err


def test_an_empty_source_means_no_list(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / ".DS_Store").write_bytes(b"clutter")   # clutter alone is still "nothing to copy"
    out = tmp_path / "source.md5"
    assert main(["make", str(empty), "--out", str(out)]) == 2
    assert not out.exists()
    assert "no files" in capsys.readouterr().err


def test_a_missing_source_means_no_list(tmp_path):
    out = tmp_path / "source.md5"
    assert main(["make", str(tmp_path / "nowhere"), "--out", str(out)]) == 2
    assert not out.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows file names can't contain a line break")
def test_a_name_with_a_line_break_means_no_list(source, tmp_path, capsys):
    (source / "Reel01" / "two\nlines.mov").write_bytes(b"x")
    out = tmp_path / "source.md5"
    assert main(["make", str(source), "--out", str(out)]) == 2
    assert not out.exists()
    assert "line break" in capsys.readouterr().err


# --- Where the list goes -------------------------------------------------------------------------

def test_never_overwrites_an_existing_list(source, tmp_path, capsys):
    out = tmp_path / "source.md5"
    out.write_text("an earlier list\n", encoding="utf-8")
    assert main(["make", str(source), "--out", str(out)]) == 2
    assert out.read_text(encoding="utf-8") == "an earlier list\n"
    assert "already exists" in capsys.readouterr().err


def test_an_existing_list_stops_it_before_any_checksumming(source, tmp_path, monkeypatch):
    # Checksumming a large source can take hours: find out first, not afterwards.
    out = tmp_path / "source.md5"
    out.write_text("an earlier list\n", encoding="utf-8")
    monkeypatch.setattr(hashing, "hash_files", lambda *a, **k: pytest.fail("checksummed before refusing"))
    assert main(["make", str(source), "--out", str(out)]) == 2


def test_a_list_that_appears_while_checksumming_is_not_overwritten(source, tmp_path, monkeypatch):
    out = tmp_path / "source.md5"
    real = hashing.hash_files

    def someone_else_writes_it(*args, **kwargs):
        out.write_text("written meanwhile\n", encoding="utf-8")
        return real(*args, **kwargs)

    monkeypatch.setattr(hashing, "hash_files", someone_else_writes_it)
    assert main(["make", str(source), "--out", str(out)]) == 2
    assert out.read_text(encoding="utf-8") == "written meanwhile\n"


def test_never_writes_the_list_inside_the_source(source, capsys):
    before = snapshot(source)
    assert main(["make", str(source), "--out", str(source / "Reel01" / "list.md5")]) == 2
    assert snapshot(source) == before
    assert "inside the source" in capsys.readouterr().err


def test_a_failed_write_leaves_no_half_written_list(source, tmp_path, monkeypatch):
    out = tmp_path / "source.md5"
    real_open = open

    class BreaksHalfway:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.handle.close()
            return False

        def write(self, text):
            self.handle.write(text[:10])
            raise OSError(28, "No space left on device")

    def fake_open(path, mode="r", *args, **kwargs):
        handle = real_open(path, mode, *args, **kwargs)
        return BreaksHalfway(handle) if os.fspath(path) == os.fspath(out) else handle

    monkeypatch.setattr(make, "open", fake_open, raising=False)
    assert main(["make", str(source), "--out", str(out)]) == 2
    assert not out.exists()
