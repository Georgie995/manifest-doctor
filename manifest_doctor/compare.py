"""Compare two versions of a delivery's checksum list: the earlier one and the later one.

Georgi works backwards through a delivery's versions, two lists at a time, to find where a problem
started (design section 13, approved 2026-10-14). Read-only: only the two lists are read, never a
folder or any file's contents, and nothing goes over the network.

Files are paired by exact name, then by a checksum that appears exactly once on each side, and
never by similar-looking names. Whatever can't be told apart is shown as a group, not guessed.
"""

import csv
import hashlib
import json
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import __version__
from .coverage import CHECKSUM_NAMES
from .manifest import ManifestError, read_manifest  # noqa: F401  (ManifestError: for callers)
from .report import new_folder

LIMITS = ("This compares the names and checksums written in the two lists. It doesn't read any files, "
          "so it can't tell whether either list was right.")
SUMMARY_GROUP_LIMIT = 50     # files shown per group in summary.md; the CSV always has every one
CSV_COLUMNS = ["group", "earlier_path", "later_path", "earlier_checksum", "later_checksum", "note"]


@dataclass
class Comparison:
    earlier: object                  # the earlier list, as read (ManifestResult)
    later: object
    algorithm: str
    unchanged: list = field(default_factory=list)
    changed: list = field(default_factory=list)
    renamed: list = field(default_factory=list)
    only_earlier: list = field(default_factory=list)
    only_later: list = field(default_factory=list)
    cannot_tell: list = field(default_factory=list)
    empty_earlier: list = field(default_factory=list)
    empty_later: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    hint: str | None = None
    cannot_tell_sentence: str = LIMITS

    @property
    def unreadable_earlier(self):
        return sum(1 for f in self.earlier.findings if f.code == "MANIFEST_LINE_UNREADABLE")

    @property
    def unreadable_later(self):
        return sum(1 for f in self.later.findings if f.code == "MANIFEST_LINE_UNREADABLE")

    @property
    def identical(self):
        return not (self.changed or self.renamed or self.only_earlier or self.only_later or self.cannot_tell
                    or self.empty_earlier or self.empty_later or self.unreadable_earlier or self.unreadable_later)

    @property
    def notes(self):
        """Unreadable lines first: a cut-off list makes files wrongly look as if they're only in the other list."""
        notes = []
        for side, other, n in (("earlier", "later", self.unreadable_earlier), ("later", "earlier", self.unreadable_later)):
            if n == 1:
                notes.append(f"1 line in the {side} list couldn't be read, so the file it describes may wrongly "
                             f"show as only in the {other} list.")
            elif n:
                notes.append(f"{n:,} lines in the {side} list couldn't be read, so the files they describe may "
                             f"wrongly show as only in the {other} list.")
        return notes


def compare_lists(earlier_path, later_path, algorithm="md5"):
    # prefix_mode "off": names are compared as written. Lists that start from different folders still
    # pair by checksum, and a hint says so; nothing is stripped behind the person's back.
    earlier = read_manifest(earlier_path, algorithm, prefix_mode="off")
    later = read_manifest(later_path, algorithm, prefix_mode="off")
    c = Comparison(earlier, later, algorithm)
    c.problems = [{"list": side, "code": f.code, "line": f.line, "detail": f.detail}
                  for side, result in (("earlier", earlier), ("later", later)) for f in result.findings]

    # 1. The same name in both lists, each listed once: unchanged or changed.
    earlier_names, later_names = _by_name(earlier.entries), _by_name(later.entries)
    left_earlier, left_later = [], []
    for key in sorted(set(earlier_names) | set(later_names)):
        es, ls = earlier_names.get(key, []), later_names.get(key, [])
        if len(es) == 1 and len(ls) == 1:
            e, l = es[0], ls[0]
            if e.hash == l.hash:
                c.unchanged.append({"path": l.path, "checksum": l.hash})
            else:
                elsewhere = sorted(x.path for x in later.entries if x.hash == e.hash and x.path != l.path)
                c.changed.append({"path": l.path, "earlier_checksum": e.hash, "later_checksum": l.hash,
                                  "earlier_content_now_at": [] if e.hash == _empty(algorithm) else elsewhere})
        elif es and ls:
            # Listed more than once on a side: which version became which can't be told by name.
            c.cannot_tell.append({"reason": "same name listed more than once", "name": (ls or es)[0].path,
                                  "earlier": [e.path for e in es], "later": [l.path for l in ls],
                                  "earlier_checksums": [e.hash for e in es], "later_checksums": [l.hash for l in ls]})
        else:
            left_earlier += es
            left_later += ls

    # 2-4. The rest, by checksum: once on each side means renamed or moved; more than that can't be
    # told apart; on one side only means only in that list. Empty files all share one checksum, so
    # they say nothing about which became which: always their own group.
    empty = _empty(algorithm)
    earlier_sums, later_sums = _by_hash(left_earlier), _by_hash(left_later)
    for checksum in sorted(set(earlier_sums) | set(later_sums)):
        es, ls = earlier_sums.get(checksum, []), later_sums.get(checksum, [])
        if checksum == empty:
            c.empty_earlier += [e.path for e in es]
            c.empty_later += [l.path for l in ls]
        elif len(es) == 1 and len(ls) == 1:
            c.renamed.append({"earlier_path": es[0].path, "later_path": ls[0].path, "checksum": checksum})
        elif es and ls:
            c.cannot_tell.append({"reason": "same checksum", "checksum": checksum,
                                  "earlier": sorted(e.path for e in es), "later": sorted(l.path for l in ls)})
        else:
            c.only_earlier += [{"path": e.path, "checksum": checksum} for e in es]
            c.only_later += [{"path": l.path, "checksum": checksum} for l in ls]

    for group, key in ((c.unchanged, "path"), (c.changed, "path"), (c.renamed, "earlier_path"),
                       (c.only_earlier, "path"), (c.only_later, "path")):
        group.sort(key=lambda item: item[key])
    c.cannot_tell.sort(key=lambda g: (g["earlier"] or g["later"])[0])
    c.empty_earlier.sort()
    c.empty_later.sort()
    c.hint = _hint(c)
    return c


def _key(path):
    # The reader has already tidied slashes and a leading "./". The same accent written two ways is
    # the same name; upper and lower case are not (they are different files on S3).
    return unicodedata.normalize("NFC", path)


def _by_name(entries):
    names = {}
    for e in entries:
        names.setdefault(_key(e.path), []).append(e)
    return names


def _by_hash(entries):
    sums = {}
    for e in entries:
        sums.setdefault(e.hash, []).append(e)
    return sums


def _empty(algorithm):
    return hashlib.new(algorithm).hexdigest()   # the checksum of a file with nothing in it


def _hint(c):
    """If every rename is just a folder added or removed at the start, the lists probably start from
    different folders. Said as a hint; nothing is stripped."""
    if not c.renamed or c.unchanged or c.changed:
        return None
    found = set()
    for r in c.renamed:
        e, l = r["earlier_path"], r["later_path"]
        if e.endswith("/" + l):
            found.add(("earlier", e[:len(e) - len(l)]))
        elif l.endswith("/" + e):
            found.add(("later", l[:len(l) - len(e)]))
        else:
            return None
    if len(found) != 1:
        return None
    side, prefix = found.pop()
    longer, shorter = ("earlier", "later") if side == "earlier" else ("later", "earlier")
    return (f"Every renamed file's {longer} name is its {shorter} name with \"{prefix}\" in front: "
            "the two lists probably start from different folders.")


# --- The saved comparison ----------------------------------------------------------------------------

def write_comparison(c, out_dir, now=None):
    now = now or datetime.now().astimezone()
    folder = new_folder(Path(out_dir), now, kind="compare")
    header = _header(c, now)
    data = {"header": header, "changed": c.changed, "renamed": c.renamed, "only_earlier": c.only_earlier,
            "only_later": c.only_later, "cannot_tell": c.cannot_tell,
            "empty": {"earlier": c.empty_earlier, "later": c.empty_later},
            "unchanged": c.unchanged, "list_problems": c.problems}
    (folder / "comparison.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(folder / "comparison.csv", c)
    _write_summary(folder / "summary.md", c, header)
    return folder


def _header(c, now):
    def about(result):
        return {"path": result.manifest, "format": result.format, "entries": len(result.entries)}

    return {
        "tool": "manifest-doctor", "version": __version__, "kind": "comparison",
        "run_at": now.isoformat(timespec="seconds"),
        "result": result_text(c), "identical": c.identical,
        "checksum": CHECKSUM_NAMES.get(c.algorithm, c.algorithm.upper()),
        "earlier": about(c.earlier), "later": about(c.later),
        "counts": {"changed": len(c.changed), "renamed": len(c.renamed), "only_earlier": len(c.only_earlier),
                   "only_later": len(c.only_later), "cannot_tell_groups": len(c.cannot_tell),
                   "cannot_tell_files": sum(len(g["earlier"]) + len(g["later"]) for g in c.cannot_tell),
                   "empty_earlier": len(c.empty_earlier), "empty_later": len(c.empty_later),
                   "unchanged": len(c.unchanged), "unreadable_earlier": c.unreadable_earlier,
                   "unreadable_later": c.unreadable_later},
        "notes": c.notes, "hint": c.hint, "limits": LIMITS,
    }


def _plural(n, word):
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def _group_line(g):
    def codes(items):
        return ", ".join(f"`{x}`" for x in items)

    if "name" in g:      # one name, several versions: show each version's checksum
        return (f"- `{g['name']}` is listed more than once: earlier {codes(g['earlier_checksums']) or 'none'}; "
                f"later {codes(g['later_checksums']) or 'none'}")
    return f"- checksum `{g['checksum']}` is shared by: earlier {codes(g['earlier'])}; later {codes(g['later'])}"


def result_text(c):
    return "IDENTICAL" if c.identical else "THE LISTS DIFFER"


def _rows(c):
    for x in c.changed:
        note = ("earlier content now at: " + "; ".join(x["earlier_content_now_at"])) if x["earlier_content_now_at"] else ""
        yield ["changed", x["path"], x["path"], x["earlier_checksum"], x["later_checksum"], note]
    for x in c.renamed:
        yield ["renamed or moved", x["earlier_path"], x["later_path"], x["checksum"], x["checksum"], ""]
    for x in c.only_earlier:
        yield ["only in the earlier list", x["path"], "", x["checksum"], "", ""]
    for x in c.only_later:
        yield ["only in the later list", "", x["path"], "", x["checksum"], ""]
    for g in c.cannot_tell:
        earlier_sums = g.get("earlier_checksums") or [g["checksum"]] * len(g["earlier"])
        later_sums = g.get("later_checksums") or [g["checksum"]] * len(g["later"])
        for p, checksum in zip(g["earlier"], earlier_sums):
            yield ["can't tell which became which", p, "", checksum, "", g["reason"]]
        for p, checksum in zip(g["later"], later_sums):
            yield ["can't tell which became which", "", p, "", checksum, g["reason"]]
    empty = _empty(c.algorithm)
    for p in c.empty_earlier:
        yield ["empty file", p, "", empty, "", "all empty files share one checksum"]
    for p in c.empty_later:
        yield ["empty file", "", p, "", empty, "all empty files share one checksum"]
    for x in c.unchanged:
        yield ["unchanged", x["path"], x["path"], x["checksum"], x["checksum"], ""]


def _write_csv(path, c):
    # "utf-8-sig" adds the marker Excel needs to show accented names correctly.
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(_rows(c))


def _write_summary(path, c, header):
    counts = header["counts"]
    lines = ["# List comparison", "", f"**RESULT: {header['result']}**", "",
             f"- Earlier list: `{c.earlier.manifest}` ({c.earlier.format}, {len(c.earlier.entries)} entries)",
             f"- Later list: `{c.later.manifest}` ({c.later.format}, {len(c.later.entries)} entries)",
             f"- Compared at: {header['run_at']}", f"- Checksums: {header['checksum']}", "",
             "| Group | Files |", "|---|---|",
             f"| Changed (same name, different checksum) | {counts['changed']} |",
             f"| Renamed or moved (same checksum, different name) | {counts['renamed']} |",
             f"| Only in the earlier list | {counts['only_earlier']} |",
             f"| Only in the later list | {counts['only_later']} |",
             f"| Can't tell which became which | {_plural(counts['cannot_tell_files'], 'file')} in "
             f"{_plural(counts['cannot_tell_groups'], 'group')} |",
             f"| Empty files (never paired) | {counts['empty_earlier']} earlier, {counts['empty_later']} later |",
             f"| Unchanged | {counts['unchanged']} |"]
    for note in c.notes + ([c.hint] if c.hint else []):
        lines += ["", f"**Note:** {note}"]

    def section(title, items):
        lines.extend(["", f"## {title}", ""])
        lines.extend(items[:SUMMARY_GROUP_LIMIT] or ["None."])
        if len(items) > SUMMARY_GROUP_LIMIT:
            lines.append(f"- … and {len(items) - SUMMARY_GROUP_LIMIT} more (full list in comparison.csv)")

    section("Changed: same name, different checksum",
            [f"- `{x['path']}`: earlier `{x['earlier_checksum']}`, later `{x['later_checksum']}`"
             + (f"; its earlier content is now at {', '.join(f'`{p}`' for p in x['earlier_content_now_at'])}"
                if x["earlier_content_now_at"] else "") for x in c.changed])
    section("Renamed or moved: same checksum, different name",
            [f"- `{x['earlier_path']}` → `{x['later_path']}`" for x in c.renamed])
    section("Only in the earlier list", [f"- `{x['path']}`" for x in c.only_earlier])
    section("Only in the later list", [f"- `{x['path']}`" for x in c.only_later])
    section("Can't tell which became which", [_group_line(g) for g in c.cannot_tell])
    section("Empty files (all share one checksum, so never paired)",
            [f"- earlier: `{p}`" for p in c.empty_earlier] + [f"- later: `{p}`" for p in c.empty_later])
    lines += ["", "## Unchanged", "", f"{counts['unchanged']} files (full list in comparison.csv)."]
    lines += ["", "## What this comparison can tell you", "", LIMITS]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
