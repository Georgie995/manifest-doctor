"""What a check proves, and what it doesn't, in plain sentences (wording approved by Georgi, 2026-10-14).

Each test builds a small synthetic delivery, runs the real check, and reads the sentences back.
"""

import hashlib
import unicodedata

from manifest_doctor import hashing, scan
from manifest_doctor.coverage import coverage
from manifest_doctor.verify import verify

CANNOT_TELL = ("This shows the files match the manifest today. It can't tell you whether the manifest itself was "
               "right, or catch changes made after this check.")
FILES = {"ShowA/clip_0001.mov": b"one", "ShowA/clip_0002.mov": b"two", "ShowA/clip_0003.mov": b"three"}


def md5(data):
    return hashlib.md5(data).hexdigest()


def delivery(tmp_path, on_disk, listed, extra_lines=(), name="m.md5"):
    tree = tmp_path / "delivery"
    tree.mkdir(exist_ok=True)
    for relative, content in on_disk.items():
        path = tree / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest = tmp_path / name
    lines = [f"{digest}  {relative}" for relative, digest in listed.items()] + list(extra_lines)
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tree, manifest


def listed(files):
    return {relative: md5(content) for relative, content in files.items()}


# --- What was read and compared ------------------------------------------------------------------

def test_a_clean_check_says_every_listed_file_was_read_and_matched(tmp_path):
    tree, m = delivery(tmp_path, FILES, listed(FILES))
    c = coverage(verify(tree, [m]))
    assert c["proved"] == "All 3 files listed in the manifest were found and read in full, and every MD5 checksum matched."
    assert c["not_checked"] == []
    assert c["cannot_tell"] == CANNOT_TELL


def test_a_single_file_reads_naturally(tmp_path):
    one = {"ShowA/clip_0001.mov": b"one"}
    tree, m = delivery(tmp_path, one, listed(one))
    assert coverage(verify(tree, [m]))["proved"] == ("The file listed in the manifest was found and read in full, "
                                                    "and its MD5 checksum matched.")


def test_when_every_file_was_read_but_some_didnt_match_both_numbers_are_given(tmp_path):
    wrong = dict(listed(FILES), **{"ShowA/clip_0002.mov": md5(b"not two")})
    tree, m = delivery(tmp_path, FILES, wrong)
    assert coverage(verify(tree, [m]))["proved"] == ("All 3 files listed in the manifest were found and read in full, "
                                                    "and their MD5 checksums compared: 2 matched and 1 didn't.")


def test_the_approved_problems_example_missing_and_mismatched(tmp_path):
    entries = dict(listed(FILES), **{"ShowA/clip_0002.mov": md5(b"not two"), "ShowA/clip_0004.mov": md5(b"four")})
    tree, m = delivery(tmp_path, FILES, entries)
    c = coverage(verify(tree, [m]))
    assert c["proved"] == ("3 of the 4 files listed in the manifest were read in full and their MD5 checksums "
                           "compared: 2 matched and 1 didn't.")
    assert c["not_checked"] == ["1 listed file wasn't found, so it couldn't be compared."]


def test_files_found_under_a_slightly_different_name_are_counted_and_pointed_at(tmp_path):
    on_disk = {unicodedata.normalize("NFD", "ShowA/Café.mov"): b"accent", "ShowA/CLIP.mov": b"case"}
    entries = {unicodedata.normalize("NFC", "ShowA/Café.mov"): md5(b"accent"), "ShowA/clip.mov": md5(b"case")}
    tree, m = delivery(tmp_path, on_disk, entries)
    assert coverage(verify(tree, [m]))["proved"] == (
        "All 2 files listed in the manifest were found and read in full, and every MD5 checksum matched. "
        "2 of them were found under a slightly different name (an accent, upper/lower case or an extra folder); "
        "see the warnings.")


def test_nothing_read_at_all_is_said_plainly(tmp_path):
    tree, m = delivery(tmp_path, {}, listed(FILES))
    c = coverage(verify(tree, [m]))
    assert c["proved"] == "None of the 3 files listed in the manifest could be read and compared."
    assert c["not_checked"] == ["3 listed files weren't found, so they couldn't be compared."]


def test_more_than_one_manifest_is_named_in_the_plural(tmp_path):
    half = {"ShowA/clip_0001.mov": b"one"}
    rest = {k: v for k, v in FILES.items() if k not in half}
    tree, first = delivery(tmp_path, FILES, listed(half), name="set1.md5")
    _, second = delivery(tmp_path, {}, listed(rest), name="set2.md5")
    assert coverage(verify(tree, [first, second]))["proved"] == (
        "All 3 files listed in the manifests were found and read in full, and every MD5 checksum matched.")


def test_the_checksum_type_is_named(tmp_path):
    entries = {relative: hashlib.sha256(content).hexdigest() for relative, content in FILES.items()}
    tree, m = delivery(tmp_path, FILES, entries)
    assert "every SHA-256 checksum matched" in coverage(verify(tree, [m], algorithm="sha256"),
                                                         algorithm="sha256")["proved"]


# --- What wasn't checked, one sentence each, only when it applies ---------------------------------

def test_a_file_that_couldnt_be_read(tmp_path, monkeypatch):
    real = hashing.hash_file

    def fails_for_clip_2(path, algorithm, *args, **kwargs):
        if path.name == "clip_0002.mov":
            raise PermissionError(13, "Permission denied")
        return real(path, algorithm, *args, **kwargs)

    monkeypatch.setattr(hashing, "hash_file", fails_for_clip_2)
    tree, m = delivery(tmp_path, FILES, listed(FILES))
    c = coverage(verify(tree, [m]))
    assert c["proved"] == "2 of the 3 files listed in the manifest were read in full, and every MD5 checksum matched."
    assert c["not_checked"] == ["1 file couldn't be read, so it wasn't compared."]


def test_a_folder_that_couldnt_be_opened(tmp_path, monkeypatch):
    tree, m = delivery(tmp_path, FILES, listed(FILES))
    real_walk = scan.os.walk

    def walk_with_a_locked_folder(top, onerror=None, **kwargs):
        onerror(PermissionError(13, "Permission denied", str(tree / "Locked")))
        yield from real_walk(top, onerror=onerror, **kwargs)

    monkeypatch.setattr(scan.os, "walk", walk_with_a_locked_folder)
    assert coverage(verify(tree, [m]))["not_checked"] == ["1 folder couldn't be opened, so nothing inside it was checked."]


def test_a_manifest_line_that_couldnt_be_read_such_as_a_cut_off_list(tmp_path):
    tree, m = delivery(tmp_path, FILES, listed(FILES), extra_lines=["0123456789abcdef  ShowA/clip_00"])
    assert coverage(verify(tree, [m]))["not_checked"] == [
        "1 line in the manifest couldn't be read, so whatever it lists wasn't checked."]


def test_extra_files_and_system_files_set_aside(tmp_path):
    on_disk = dict(FILES, **{"ShowA/notes.txt": b"x", "ShowA/.DS_Store": b"y"})
    tree, m = delivery(tmp_path, on_disk, listed(FILES))
    assert coverage(verify(tree, [m]))["not_checked"] == [
        "1 file in the folder isn't in the manifest, and wasn't checksummed.",
        "1 system file (such as .DS_Store) was set aside and not checked."]


def test_extra_files_checksummed_on_request_have_nothing_to_be_compared_with(tmp_path):
    on_disk = dict(FILES, **{"ShowA/notes.txt": b"x"})
    tree, m = delivery(tmp_path, on_disk, listed(FILES))
    assert coverage(verify(tree, [m], hash_extras=True), hash_extras=True)["not_checked"] == [
        "1 file in the folder isn't in the manifest, so there was nothing to compare it with "
        "(its checksum is in the report)."]


def test_every_sentence_has_its_plural(tmp_path):
    on_disk = dict(FILES, **{"ShowA/a.txt": b"a", "ShowA/b.txt": b"b", "ShowA/.DS_Store": b"y", "ShowB/.DS_Store": b"z"})
    entries = dict(listed(FILES), **{"ShowA/gone_1.mov": md5(b"1"), "ShowA/gone_2.mov": md5(b"2")})
    tree, m = delivery(tmp_path, on_disk, entries, extra_lines=["not a manifest line", "nor this"])
    assert coverage(verify(tree, [m]))["not_checked"] == [
        "2 listed files weren't found, so they couldn't be compared.",
        "2 lines in the manifest couldn't be read, so whatever they list wasn't checked.",
        "2 files in the folder aren't in the manifest, and weren't checksummed.",
        "2 system files (such as .DS_Store) were set aside and not checked."]


def test_the_numbers_behind_the_sentences_are_kept_too(tmp_path):
    entries = dict(listed(FILES), **{"ShowA/clip_0002.mov": md5(b"not two"), "ShowA/clip_0004.mov": md5(b"four")})
    tree, m = delivery(tmp_path, FILES, entries)
    c = coverage(verify(tree, [m]))
    assert {k: c[k] for k in ("checksum", "listed", "found", "read", "matched", "mismatched", "missing")} == {
        "checksum": "MD5", "listed": 4, "found": 3, "read": 3, "matched": 2, "mismatched": 1, "missing": 1}


def test_a_missing_file_listed_twice_is_one_file_not_found(tmp_path):
    tree, m = delivery(tmp_path, FILES, listed(FILES),
                       extra_lines=[f"{md5(b'v1')}  ShowA/gone.mov", f"{md5(b'v2')}  ShowA/gone.mov"])
    c = coverage(verify(tree, [m]))
    assert c["listed"] == 4
    assert c["not_checked"] == ["1 listed file wasn't found, so it couldn't be compared."]
