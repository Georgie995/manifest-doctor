"""Comparing two versions of a delivery's checksum list (design section 13, approved by Georgi 2026-10-14).

Files are paired by exact name, then by a checksum that appears exactly once on each side. Never by
similar-looking names. Every list here is synthetic.
"""

import hashlib
import json
import unicodedata
from datetime import datetime, timezone

from manifest_doctor.cli import main
from manifest_doctor.compare import compare_lists, write_comparison

EMPTY = hashlib.md5(b"").hexdigest()
FIXED_TIME = datetime(2026, 10, 14, 18, 30, 0, tzinfo=timezone.utc)


def md5(text):
    return hashlib.md5(text.encode()).hexdigest()


def write_list(tmp_path, name, entries, extra_lines=()):
    """A pipe-style list ("path|checksum"), like the lists in Georgi's workflow."""
    path = tmp_path / name
    lines = [f"{p}|{h}" for p, h in entries] + list(extra_lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def compare(tmp_path, earlier, later, earlier_lines=(), later_lines=()):
    return compare_lists(write_list(tmp_path, "earlier.md5", earlier, earlier_lines),
                         write_list(tmp_path, "later.md5", later, later_lines))


A, B, C = ("Reel01/a.mov", md5("a")), ("Reel01/b.mov", md5("b")), ("Reel01/c.mov", md5("c"))


# --- The groups ------------------------------------------------------------------------------------

def test_identical_lists_are_all_unchanged(tmp_path):
    c = compare(tmp_path, [A, B, C], [C, A, B])
    assert [u["path"] for u in c.unchanged] == ["Reel01/a.mov", "Reel01/b.mov", "Reel01/c.mov"]
    assert c.identical is True
    assert not (c.changed or c.renamed or c.only_earlier or c.only_later or c.cannot_tell)


def test_same_name_with_a_different_checksum_is_changed(tmp_path):
    c = compare(tmp_path, [A, B], [A, ("Reel01/b.mov", md5("b, re-delivered"))])
    assert c.changed == [{"path": "Reel01/b.mov", "earlier_checksum": md5("b"),
                          "later_checksum": md5("b, re-delivered"), "earlier_content_now_at": []}]
    assert c.identical is False


def test_the_same_checksum_under_a_new_name_is_renamed_or_moved(tmp_path):
    c = compare(tmp_path, [("Day 1 – Interviews/clip 1.mov", md5("x"))],
                [("Day_1_-_Interviews/clip_1.mov", md5("x"))])
    assert c.renamed == [{"earlier_path": "Day 1 – Interviews/clip 1.mov",
                          "later_path": "Day_1_-_Interviews/clip_1.mov", "checksum": md5("x")}]


def test_files_in_only_one_list(tmp_path):
    c = compare(tmp_path, [A, B], [A, C])
    assert c.only_earlier == [{"path": "Reel01/b.mov", "checksum": md5("b")}]
    assert c.only_later == [{"path": "Reel01/c.mov", "checksum": md5("c")}]


def test_a_checksum_shared_by_several_files_is_never_guessed(tmp_path):
    same = md5("duplicate take")
    c = compare(tmp_path, [("Day1/take.wav", same), ("Day1/take copy.wav", same)],
                [("Day1/take_final.wav", same)])
    assert c.renamed == [] and c.only_earlier == [] and c.only_later == []
    assert c.cannot_tell == [{"reason": "same checksum", "checksum": same,
                              "earlier": ["Day1/take copy.wav", "Day1/take.wav"],
                              "later": ["Day1/take_final.wav"]}]


def test_empty_files_are_their_own_group_and_never_paired(tmp_path):
    # Every empty file has the same checksum, so even one-to-one says nothing about which became which.
    c = compare(tmp_path, [A, ("Reel01/notes.txt", EMPTY), ("Reel01/placeholder", EMPTY)],
                [A, ("Reel01/notes_v2.txt", EMPTY)])
    assert c.empty_earlier == ["Reel01/notes.txt", "Reel01/placeholder"]
    assert c.empty_later == ["Reel01/notes_v2.txt"]
    assert c.renamed == [] and c.cannot_tell == [] and c.only_earlier == [] and c.only_later == []


def test_an_empty_file_with_the_same_name_in_both_is_simply_unchanged(tmp_path):
    c = compare(tmp_path, [("Reel01/notes.txt", EMPTY)], [("Reel01/notes.txt", EMPTY)])
    assert [u["path"] for u in c.unchanged] == ["Reel01/notes.txt"] and c.empty_earlier == []


def test_a_changed_files_earlier_content_found_under_another_name_is_pointed_out(tmp_path):
    # The re-delivery pattern behind Georgi's S3-overwrite case.
    c = compare(tmp_path, [("Reel01/clip_0004.mov", md5("first version"))],
                [("Reel01/clip_0004.mov", md5("second version")), ("Reel01/clip_0004_v1.mov", md5("first version"))])
    assert c.changed[0]["earlier_content_now_at"] == ["Reel01/clip_0004_v1.mov"]
    assert c.only_later == [{"path": "Reel01/clip_0004_v1.mov", "checksum": md5("first version")}]


# --- Names -----------------------------------------------------------------------------------------

def test_the_same_name_written_in_a_different_accent_form_is_the_same_name(tmp_path):
    nfd, nfc = unicodedata.normalize("NFD", "Reel01/Café.mov"), unicodedata.normalize("NFC", "Reel01/Café.mov")
    c = compare(tmp_path, [(nfd, md5("cafe"))], [(nfc, md5("cafe"))])
    assert len(c.unchanged) == 1 and c.renamed == []


def test_names_that_differ_only_in_case_are_different_names(tmp_path):
    # They are different files on S3, so this is a rename, not "unchanged".
    c = compare(tmp_path, [("Reel01/clip.mov", md5("c"))], [("Reel01/CLIP.mov", md5("c"))])
    assert c.unchanged == [] and len(c.renamed) == 1


def test_backslashes_and_a_leading_dot_slash_are_tidied_as_usual(tmp_path):
    c = compare(tmp_path, [("./Reel01\\a.mov", md5("a"))], [A])
    assert len(c.unchanged) == 1


def test_a_name_listed_twice_in_one_list_cant_be_paired_by_name(tmp_path):
    c = compare(tmp_path, [("Reel01/b.mov", md5("v1")), ("Reel01/b.mov", md5("v2"))], [("Reel01/b.mov", md5("v2"))])
    assert c.changed == [] and c.unchanged == [] and c.renamed == []
    # Each version's checksum is shown, so a person can see which earlier version matches the later one.
    assert c.cannot_tell == [{"reason": "same name listed more than once", "name": "Reel01/b.mov",
                              "earlier": ["Reel01/b.mov", "Reel01/b.mov"], "later": ["Reel01/b.mov"],
                              "earlier_checksums": [md5("v1"), md5("v2")], "later_checksums": [md5("v2")]}]
    assert [(p["list"], p["code"]) for p in c.problems] == [("earlier", "DUPLICATE_ENTRY")]


def test_lists_that_start_from_different_folders_get_a_hint_and_still_pair_by_checksum(tmp_path):
    c = compare(tmp_path, [("/Volumes/RAID/SHOW/Reel01/a.mov", md5("a")), ("/Volumes/RAID/SHOW/Reel02/b.mov", md5("b"))],
                [("Reel01/a.mov", md5("a")), ("Reel02/b.mov", md5("b"))])
    assert len(c.renamed) == 2
    assert c.hint == ("Every renamed file's earlier name is its later name with \"/Volumes/RAID/SHOW/\" in front: "
                      "the two lists probably start from different folders.")


def test_no_hint_when_the_renames_are_ordinary(tmp_path):
    c = compare(tmp_path, [("Reel01/clip 1.mov", md5("x")), A], [("Reel01/clip_1.mov", md5("x")), A])
    assert c.hint is None


# --- What couldn't be compared ---------------------------------------------------------------------

def test_lines_that_couldnt_be_read_are_counted_per_list_and_explained(tmp_path):
    c = compare(tmp_path, [A, B], [A, B, C], earlier_lines=["Reel01/c.mov|0123456789"])   # cut off
    assert (c.unreadable_earlier, c.unreadable_later) == (1, 0)
    assert c.notes == ["1 line in the earlier list couldn't be read, so the file it describes may wrongly "
                       "show as only in the later list."]
    assert c.identical is False


def test_what_a_comparison_can_and_cant_tell(tmp_path):
    c = compare(tmp_path, [A], [A])
    assert c.cannot_tell_sentence == ("This compares the names and checksums written in the two lists. It doesn't "
                                      "read any files, so it can't tell whether either list was right.")


def test_full_path_and_md5sum_style_lists_are_read_too(tmp_path):
    earlier = tmp_path / "yoyotta.md5"
    earlier.write_text(f"/Volumes/RAID/SHOW/Reel01/a.mov|{md5('a')}\n", encoding="utf-8")
    later = tmp_path / "later.md5"
    later.write_text(f"{md5('a')}  Reel01/a.mov\n", encoding="utf-8")
    c = compare_lists(earlier, later)
    assert c.renamed == [{"earlier_path": "/Volumes/RAID/SHOW/Reel01/a.mov", "later_path": "Reel01/a.mov",
                          "checksum": md5("a")}]


# --- The saved comparison --------------------------------------------------------------------------

def test_each_comparison_gets_its_own_dated_folder_with_three_files(tmp_path):
    c = compare(tmp_path, [A, B], [A, ("Reel01/b.mov", md5("new"))])
    first = write_comparison(c, tmp_path / "out", now=FIXED_TIME)
    second = write_comparison(c, tmp_path / "out", now=FIXED_TIME)
    assert first.name == "compare-2026-10-14_183000" and second.name == "compare-2026-10-14_183000-2"
    assert sorted(p.name for p in first.iterdir()) == ["comparison.csv", "comparison.json", "summary.md"]


def test_comparison_json_has_the_header_counts_and_every_group(tmp_path):
    c = compare(tmp_path, [A, B], [A, ("Reel01/b.mov", md5("new")), C])
    data = json.loads((write_comparison(c, tmp_path / "out", now=FIXED_TIME) / "comparison.json")
                      .read_text(encoding="utf-8"))
    header = data["header"]
    assert header["tool"] == "manifest-doctor" and header["kind"] == "comparison"
    assert header["identical"] is False and header["checksum"] == "MD5"
    assert header["counts"]["changed"] == 1 and header["counts"]["only_later"] == 1 and header["counts"]["unchanged"] == 1
    assert header["earlier"]["path"].endswith("earlier.md5") and header["later"]["entries"] == 3
    assert data["changed"][0]["path"] == "Reel01/b.mov"
    assert set(data) >= {"changed", "renamed", "only_earlier", "only_later", "cannot_tell", "empty", "unchanged",
                         "list_problems"}


def test_comparison_csv_has_one_row_per_file_with_its_group(tmp_path):
    import csv
    c = compare(tmp_path, [A, ("Reel01/old name.mov", md5("x"))], [A, ("Reel01/new_name.mov", md5("x"))])
    folder = write_comparison(c, tmp_path / "out", now=FIXED_TIME)
    with open(folder / "comparison.csv", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [(r["group"], r["earlier_path"], r["later_path"]) for r in rows] == [
        ("renamed or moved", "Reel01/old name.mov", "Reel01/new_name.mov"),
        ("unchanged", "Reel01/a.mov", "Reel01/a.mov")]


def test_summary_puts_changed_first_and_says_what_the_comparison_can_tell(tmp_path):
    c = compare(tmp_path, [A, B], [A, ("Reel01/b.mov", md5("new")), C])
    text = (write_comparison(c, tmp_path / "out", now=FIXED_TIME) / "summary.md").read_text(encoding="utf-8")
    assert "**RESULT: THE LISTS DIFFER**" in text
    assert text.index("## Changed") < text.index("## Only in the later list")
    assert "This compares the names and checksums written in the two lists." in text


# --- The command -----------------------------------------------------------------------------------

def test_the_command_exits_0_when_identical_1_when_different_and_says_where_the_results_are(tmp_path, capsys):
    same = write_list(tmp_path, "same.md5", [A, B])
    different = write_list(tmp_path, "different.md5", [A])
    assert main(["compare", str(same), str(same), "--out", str(tmp_path / "out")]) == 0
    assert main(["compare", str(same), str(different), "--out", str(tmp_path / "out")]) == 1
    out = capsys.readouterr().out
    assert "RESULT: IDENTICAL" in out and "RESULT: THE LISTS DIFFER" in out and "Results:" in out


def test_the_command_exits_2_when_a_list_cant_be_used(tmp_path, capsys):
    good = write_list(tmp_path, "good.md5", [A])
    assert main(["compare", str(good), str(tmp_path / "missing.md5"), "--out", str(tmp_path / "out")]) == 2
    sha = tmp_path / "sha.md5"
    sha.write_text(f"Reel01/a.mov|{hashlib.sha256(b'a').hexdigest()}\n", encoding="utf-8")
    assert main(["compare", str(good), str(sha), "--out", str(tmp_path / "out")]) == 2   # a different checksum type
    assert not (tmp_path / "out").exists()


def test_the_command_never_writes_its_results_next_to_nothing_it_shouldnt(tmp_path):
    # Only the two lists are read; the results go only into --out.
    earlier = write_list(tmp_path, "e.md5", [A])
    later = write_list(tmp_path, "l.md5", [B])
    before = sorted(p.name for p in tmp_path.iterdir())
    main(["compare", str(earlier), str(later), "--out", str(tmp_path / "out")])
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(before + ["out"])


def test_a_line_that_couldnt_be_read_alone_stops_the_lists_being_called_identical(tmp_path):
    c = compare(tmp_path, [A], [A], later_lines=["Reel01/b.mov|cut-off"])
    assert c.unchanged and not (c.changed or c.renamed or c.only_earlier or c.only_later)
    assert c.identical is False


def test_no_hint_when_one_file_moved_into_a_folder_and_the_rest_are_unchanged(tmp_path):
    # Same starting folder (A is unchanged); one file simply moved into Archive/. Not a different start.
    c = compare(tmp_path, [A, ("b.mov", md5("b"))], [A, ("Archive/b.mov", md5("b"))])
    assert len(c.renamed) == 1 and c.hint is None


def test_the_summary_shows_each_versions_checksum_and_counts_groups_in_plain_english(tmp_path):
    c = compare(tmp_path, [("Reel01/b.mov", md5("v1")), ("Reel01/b.mov", md5("v2"))], [("Reel01/b.mov", md5("v2"))])
    text = (write_comparison(c, tmp_path / "out", now=FIXED_TIME) / "summary.md").read_text(encoding="utf-8")
    assert f"`Reel01/b.mov` is listed more than once: earlier `{md5('v1')}`, `{md5('v2')}`; later `{md5('v2')}`" in text
    assert "| Can't tell which became which | 3 files in 1 group |" in text
