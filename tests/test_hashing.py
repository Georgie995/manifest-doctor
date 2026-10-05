"""Tests for module 2, part 2: calculating checksums."""

import hashlib

from delivery_verify import hashing
from delivery_verify.hashing import hash_file, hash_files


def make(tmp_path, relative, content):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_md5_matches_the_standard_answer(tmp_path):
    path = make(tmp_path, "a.mov", b"hello")
    assert hash_file(path, "md5") == "5d41402abc4b2a76b9719d911017c592"


def test_sha256_matches_the_standard_answer(tmp_path):
    path = make(tmp_path, "a.mov", b"hello")
    assert hash_file(path, "sha256") == hashlib.sha256(b"hello").hexdigest()


def test_empty_file_has_the_well_known_empty_md5(tmp_path):
    path = make(tmp_path, "empty.mov", b"")
    assert hash_file(path, "md5") == "d41d8cd98f00b204e9800998ecf8427e"


def test_reading_in_small_pieces_gives_the_same_answer_as_reading_all_at_once(tmp_path):
    content = bytes(range(256)) * 100   # 25,600 bytes
    path = make(tmp_path, "big.mov", content)
    # A tiny chunk size forces thousands of separate reads.
    assert hash_file(path, "md5", chunk_size=7) == hashlib.md5(content).hexdigest()


def test_default_chunk_is_one_mebibyte():
    assert hashing.CHUNK_SIZE == 1024 * 1024


def test_hash_files_returns_a_hash_per_path(tmp_path):
    make(tmp_path, "ShowA/a.mov", b"hello")
    make(tmp_path, "ShowA/b.mov", b"")
    hashes, findings = hash_files(tmp_path, ["ShowA/a.mov", "ShowA/b.mov"], "md5")
    assert hashes == {
        "ShowA/a.mov": "5d41402abc4b2a76b9719d911017c592",
        "ShowA/b.mov": "d41d8cd98f00b204e9800998ecf8427e",
    }
    assert findings == []


def test_files_are_read_in_sorted_path_order(tmp_path, monkeypatch):
    for name in ("c.mov", "a.mov", "b.mov"):
        make(tmp_path, f"ShowA/{name}", b"x")
    order = []
    real_hash_file = hashing.hash_file

    def record_order(path, algorithm, chunk_size=hashing.CHUNK_SIZE):
        order.append(path.name)
        return real_hash_file(path, algorithm, chunk_size)

    monkeypatch.setattr(hashing, "hash_file", record_order)
    hash_files(tmp_path, ["ShowA/c.mov", "ShowA/a.mov", "ShowA/b.mov"], "md5")
    assert order == ["a.mov", "b.mov", "c.mov"]


def test_unreadable_file_is_reported_with_its_reason_and_the_rest_are_still_hashed(tmp_path, monkeypatch):
    make(tmp_path, "ShowA/a.mov", b"hello")
    make(tmp_path, "ShowA/b.mov", b"locked")
    make(tmp_path, "ShowA/c.mov", b"hello")
    real_hash_file = hashing.hash_file

    def b_is_locked(path, algorithm, chunk_size=hashing.CHUNK_SIZE):
        if path.name == "b.mov":
            raise PermissionError(13, "Permission denied")
        return real_hash_file(path, algorithm, chunk_size)

    monkeypatch.setattr(hashing, "hash_file", b_is_locked)
    hashes, findings = hash_files(tmp_path, ["ShowA/a.mov", "ShowA/b.mov", "ShowA/c.mov"], "md5")
    assert sorted(hashes) == ["ShowA/a.mov", "ShowA/c.mov"]
    assert [(f.code, f.severity, f.path) for f in findings] == [("UNREADABLE", "ERROR", "ShowA/b.mov")]
    assert "Permission denied" in findings[0].detail


def test_read_error_partway_through_a_file_is_reported_not_crashed(tmp_path, monkeypatch):
    # Like a bad section on archive media: the read starts, then fails.
    make(tmp_path, "ShowA/bad.mov", b"x" * 100)
    make(tmp_path, "ShowA/good.mov", b"hello")
    real_hash_file = hashing.hash_file

    def fails_midway(path, algorithm, chunk_size=hashing.CHUNK_SIZE):
        if path.name == "bad.mov":
            raise OSError(5, "Input/output error")
        return real_hash_file(path, algorithm, chunk_size)

    monkeypatch.setattr(hashing, "hash_file", fails_midway)
    hashes, findings = hash_files(tmp_path, ["ShowA/bad.mov", "ShowA/good.mov"], "md5")
    assert list(hashes) == ["ShowA/good.mov"]
    assert findings[0].code == "UNREADABLE"
    assert "Input/output error" in findings[0].detail


def test_file_that_disappeared_since_the_scan_is_reported(tmp_path):
    make(tmp_path, "ShowA/a.mov", b"hello")
    hashes, findings = hash_files(tmp_path, ["ShowA/a.mov", "ShowA/gone.mov"], "md5")
    assert list(hashes) == ["ShowA/a.mov"]
    assert [(f.code, f.path) for f in findings] == [("UNREADABLE", "ShowA/gone.mov")]
