"""Module 3a: pair each manifest entry with a real file, in three passes.

It works the way a person troubleshoots: first the obvious (exact names), then
"same name, written differently" (Unicode form or case), then "everything
shifted by a folder" (wrapper folder). Each pass only sees what earlier passes
couldn't pair, so every file ends up with one clear explanation.

When a match would be a guess (two equally good candidates), nothing is paired
and both sides are left as missing/extra for a person to look at.
"""

import unicodedata
from dataclasses import dataclass, field

from .findings import make_finding


@dataclass
class Pair:
    entries: list           # every manifest entry for this path (usually one)
    file: object            # the FileInfo on disk
    kinds: list             # "exact", or any of "unicode", "case", "prefix"
    prefix: str | None = None
    direction: str | None = None  # "extra_folder_on_disk" or "extra_folder_in_manifest"


@dataclass
class MatchResult:
    pairs: list
    missing: list           # manifest entries with no file
    extra: list             # files with no manifest entry
    findings: list = field(default_factory=list)


def match_files(entries, files):
    # Entries are grouped by path: one path can have several entries
    # (listed twice, or present in more than one manifest).
    expected = {}
    for entry in entries:
        expected.setdefault(entry.path, []).append(entry)
    actual = {f.path: f for f in files}
    result = MatchResult(pairs=[], missing=[], extra=[])

    _pass_exact(expected, actual, result)
    _pass_written_differently(expected, actual, result)
    _pass_shifted_by_folder(expected, actual, result)

    result.missing = [e for group in expected.values() for e in group]
    result.extra = sorted(actual.values(), key=lambda f: f.path)
    return result


# --- Pass 1 ----------------------------------------------------------------------

def _pass_exact(expected, actual, result):
    for path in list(expected):
        if path in actual:
            result.pairs.append(Pair(expected.pop(path), actual.pop(path), ["exact"]))


# --- Pass 2 ----------------------------------------------------------------------

def _loose_key(path):
    """The name with Unicode form and upper/lower case both ignored."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", path).casefold())


def _pass_written_differently(expected, actual, result):
    expected_by_key, actual_by_key = {}, {}
    for path in expected:
        expected_by_key.setdefault(_loose_key(path), []).append(path)
    for path in actual:
        actual_by_key.setdefault(_loose_key(path), []).append(path)

    for key, expected_paths in expected_by_key.items():
        actual_paths = actual_by_key.get(key, [])
        if len(expected_paths) != 1 or len(actual_paths) != 1:
            continue  # nothing to pair, or more than one candidate: don't guess
        manifest_path, disk_path = expected_paths[0], actual_paths[0]
        kinds = _how_they_differ(manifest_path, disk_path)
        result.pairs.append(Pair(expected.pop(manifest_path), actual.pop(disk_path), kinds))
        if "unicode" in kinds:
            result.findings.append(make_finding(
                "UNICODE_ONLY_MATCH", path=disk_path, detail=_unicode_explanation(manifest_path, disk_path)))
        if "case" in kinds:
            result.findings.append(make_finding(
                "CASE_ONLY_MATCH", path=disk_path,
                detail=f"manifest has {manifest_path!r}, disk has {disk_path!r} (differs only in upper/lower case)"))


def _unicode_explanation(manifest_path, disk_path):
    """Explain in words, because the two names look identical on screen (Georgi's review)."""
    nfc = lambda p: unicodedata.normalize("NFC", p)
    decomposed = lambda p: nfc(p) != p
    accented = sorted({c for c in nfc(manifest_path + disk_path) if unicodedata.normalize("NFD", c) != c})
    letters = ", ".join(accented)
    pronoun = "it" if len(accented) == 1 else "them"
    if decomposed(disk_path) and not decomposed(manifest_path):
        one, split = "manifest", "disk"
    elif decomposed(manifest_path) and not decomposed(disk_path):
        one, split = "disk", "manifest"
    else:
        return "the names use the same letters stored in different Unicode forms"
    return (f"the {one} writes {letters} as one character; the {split} writes {pronoun} as a letter "
            "plus a separate accent mark (typical of macOS). The names look identical but are stored differently.")


def _how_they_differ(manifest_path, disk_path):
    nfc = lambda p: unicodedata.normalize("NFC", p)
    if nfc(manifest_path) == nfc(disk_path):
        return ["unicode"]
    if manifest_path.casefold() == disk_path.casefold():
        return ["case"]
    return ["unicode", "case"]


# --- Pass 3 ----------------------------------------------------------------------

def _tails(path):
    """Every shorter path made by dropping leading folders: 'A/B/c.mov' -> 'B/c.mov', 'c.mov'."""
    parts = path.split("/")
    return ["/".join(parts[i:]) for i in range(1, len(parts))]


def _pass_shifted_by_folder(expected, actual, result):
    # Direction 1: the disk has extra folder(s) in front, e.g. disk JobX/Reel01/a.mov, manifest Reel01/a.mov
    disk_tails = {}
    for disk_path in actual:
        for tail in _tails(disk_path):
            disk_tails.setdefault(tail, []).append(disk_path)
    # Longer (more specific) paths first, so they get first claim on a file.
    for manifest_path in sorted(expected, key=len, reverse=True):
        candidates = [d for d in disk_tails.get(manifest_path, []) if d in actual]
        if len(candidates) == 1:
            disk_path = candidates[0]
            _pair_shifted(expected, actual, result, manifest_path, disk_path,
                          prefix=disk_path[:-len(manifest_path)], direction="extra_folder_on_disk")

    # Direction 2: the manifest has extra folder(s) in front, e.g. manifest JobX/Reel01/a.mov, disk Reel01/a.mov
    manifest_tails = {}
    for manifest_path in expected:
        for tail in _tails(manifest_path):
            manifest_tails.setdefault(tail, []).append(manifest_path)
    for disk_path in sorted(actual, key=len, reverse=True):
        candidates = [m for m in manifest_tails.get(disk_path, []) if m in expected]
        if len(candidates) == 1:
            manifest_path = candidates[0]
            _pair_shifted(expected, actual, result, manifest_path, disk_path,
                          prefix=manifest_path[:-len(disk_path)], direction="extra_folder_in_manifest")


def _pair_shifted(expected, actual, result, manifest_path, disk_path, prefix, direction):
    result.pairs.append(Pair(expected.pop(manifest_path), actual.pop(disk_path), ["prefix"],
                             prefix=prefix, direction=direction))
    where = "on disk" if direction == "extra_folder_on_disk" else "in the manifest"
    result.findings.append(make_finding(
        "PREFIX_OFFSET_MATCH", path=disk_path,
        detail=f"matches manifest path {manifest_path!r} once the folder {prefix!r} {where} is ignored"))
