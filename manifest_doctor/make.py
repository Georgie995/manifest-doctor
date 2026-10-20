"""Make a checksum list from the source, before a copy (approved by Georgi 2026-10-20).

Some copy methods write no checksum list. Then the list must come from the SOURCE: a list made from
the copy after it lands can never catch a bad copy, it only proves nothing changed afterwards.

Read-only on the source. The list is all or nothing: if any file or folder can't be read, no list
is written, because a list with gaps would make a later check look cleaner than the copy really is.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from . import hashing
from .scan import ScanError, scan_tree


@dataclass
class MadeList:
    path: Path
    files: int
    left_out: int   # system clutter (.DS_Store and similar), as `check` sets aside


def make_list(source, out, algorithm="md5"):
    """Write an md5sum-style list ("<checksum>  <path>") of every file under source to out.

    Raises ScanError, with every reason, if a complete list can't be made; nothing is written then.
    """
    source, out = Path(source), Path(out)
    if out.resolve().is_relative_to(source.resolve()):
        # It would change the source, and turn up as an extra file in every check of a copy.
        raise ScanError(f"{out} is inside the source; choose another --out")
    if out.exists():
        raise ScanError(f"{out} already exists; it is never overwritten")

    scanned = scan_tree(source)
    problems = [f"{f.path}: {f.detail}" for f in scanned.findings if f.code == "UNREADABLE"]
    paths = [f.path for f in scanned.files]
    # One line per file: a name containing a line break would split into two broken lines.
    problems += [f"{p!r}: the name contains a line break" for p in paths if "\n" in p or "\r" in p]
    if not problems and not paths:
        raise ScanError(f"{source} has no files to list; no list was written")

    if not problems:
        hashes, findings = hashing.hash_files(source, paths, algorithm)
        problems = [f"{f.path}: {f.detail}" for f in findings]
    if problems:
        raise ScanError("a complete list can't be made, so no list was written:\n  " + "\n  ".join(problems))

    text = "".join(f"{hashes[p]}  {p}\n" for p in paths)   # scan_tree's order: sorted by path
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        # "x": create only, so a list that appeared meanwhile is still never overwritten.
        with open(out, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except FileExistsError:
        raise ScanError(f"{out} already exists; it is never overwritten") from None
    except OSError as error:
        # Never leave half a list behind: it would look like a complete one.
        try:
            os.remove(out)
        except OSError:
            pass
        raise ScanError(f"the list couldn't be written to {out}: {error.strerror}; no list was kept") from None
    return MadeList(out, len(paths), len(scanned.hidden))
