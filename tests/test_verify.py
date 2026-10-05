"""End-to-end tests for verify(): manifests + folder in, all findings out."""

import hashlib

from delivery_verify.verify import verify


def md5(data):
    return hashlib.md5(data).hexdigest()


def build(tmp_path, files, manifest_lines, manifest_name="manifest.md5"):
    tree = tmp_path / "delivery"
    for relative, content in files.items():
        path = tree / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest = tmp_path / manifest_name
    manifest.write_text("".join(f"{line}\n" for line in manifest_lines), encoding="utf-8")
    return tree, manifest


def test_clean_delivery_has_no_findings(tmp_path):
    files = {"ShowA/Reel01/a.mov": b"aaa", "ShowA/Reel01/b.mov": b"bbb"}
    tree, manifest = build(tmp_path, files, [f"{md5(c)}  {p}" for p, c in files.items()])
    result = verify(tree, [manifest])
    assert result.findings == []


def test_problems_from_every_step_are_collected(tmp_path):
    files = {
        "ShowA/a.mov": b"aaa",
        "ShowA/b.mov": b"changed",       # hash mismatch
        "ShowA/empty.mov": b"",          # zero-byte
        "ShowA/surprise.mov": b"zzz",    # extra
        "ShowA/.DS_Store": b"junk",      # hidden, set aside
    }
    tree, manifest = build(tmp_path, files, [
        f"{md5(b'aaa')}  ShowA/a.mov",
        f"{md5(b'original')}  ShowA/b.mov",
        f"{md5(b'')}  ShowA/empty.mov",
        f"{md5(b'ccc')}  ShowA/gone.mov",  # missing
        "not a manifest line",             # unreadable line
    ])
    result = verify(tree, [manifest])
    assert sorted((f.code, f.path) for f in result.findings) == [
        ("EXTRA", "ShowA/surprise.mov"),
        ("HASH_MISMATCH", "ShowA/b.mov"),
        ("HIDDEN_FILE", "ShowA/.DS_Store"),
        ("MANIFEST_LINE_UNREADABLE", None),
        ("MISSING", "ShowA/gone.mov"),
        ("ZERO_BYTE", "ShowA/empty.mov"),
    ]


def test_wrapper_folder_delivery_matches_by_prefix_and_checks_hashes(tmp_path):
    files = {"JobX/Reel01/a.mov": b"aaa", "JobX/Reel01/b.mov": b"bbb"}
    tree, manifest = build(tmp_path, files, [f"{md5(b'aaa')}  Reel01/a.mov", f"{md5(b'bbb')}  Reel01/b.mov"])
    result = verify(tree, [manifest])
    assert sorted(f.code for f in result.findings) == ["PREFIX_OFFSET_MATCH", "PREFIX_OFFSET_MATCH"]


def test_extras_are_hashed_only_when_asked(tmp_path):
    tree, manifest = build(tmp_path, {"a.mov": b"aaa", "extra.mov": b"zzz"}, [f"{md5(b'aaa')}  a.mov"])
    [plain] = [f for f in verify(tree, [manifest]).findings if f.code == "EXTRA"]
    [hashed] = [f for f in verify(tree, [manifest], hash_extras=True).findings if f.code == "EXTRA"]
    assert plain.actual_hash is None
    assert hashed.actual_hash == md5(b"zzz")


def test_two_manifests_are_compared_against_each_other(tmp_path):
    tree, first = build(tmp_path, {"a.mov": b"new"}, [f"{md5(b'old')}  a.mov"], "first.md5")
    second = tmp_path / "second.md5"
    second.write_text(f"{md5(b'new')}  a.mov\n", encoding="utf-8")
    result = verify(tree, [first, second])
    assert result.cross_set == {"a.mov": "conflicting"}
    assert sorted(f.code for f in result.findings) == ["CROSS_SET_CONFLICT", "HASH_MISMATCH"]
