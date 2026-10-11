"""Module 3b: turn the matching results into findings.

Each check is a small function with one job, so it can be tested and explained alone.
"""

import hashlib
import unicodedata
from pathlib import Path

from .findings import make_finding

# --- Name rules ------------------------------------------------------------------------
# "windows" profile. Source: Microsoft, "Naming Files, Paths, and Namespaces",
# https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file (accessed 2026-10-05).
# "/" is not listed because it is the folder separator in our paths.
WINDOWS_CHARS = set('<>:"\\|?*')
WINDOWS_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL",
                          *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}

# "strict" profile adds the characters listed in Netflix's public guide
# "Footage Ingest - Preparing Your Media For Upload",
# https://studiopartner.netflix.net/studio/footageingest-prep (accessed 2026-10-05).
# This is a lint profile. It does not certify that a delivery meets any platform's requirements.
STRICT_CHARS = WINDOWS_CHARS | set("@#$%^&*()`;:<>?,[]{}\\'\"”|~=")

NAME_RULES = {"windows": WINDOWS_CHARS, "strict": STRICT_CHARS}


# --- Missing / extra ---------------------------------------------------------------------

def check_missing(missing_entries):
    return [make_finding("MISSING", path=e.path, manifest=e.manifest, line=e.line,
                         expected_hash=e.hash, detail="listed in the manifest but not found on disk")
            for e in missing_entries]


def check_extra(extra_files, hashes):
    return [make_finding("EXTRA", path=f.path, size=f.size, actual_hash=hashes.get(f.path),
                         detail="on disk but not listed in any manifest")
            for f in extra_files]


# --- Hash mismatch -----------------------------------------------------------------------

def check_pairs(pairs, hashes):
    findings = []
    for pair in pairs:
        actual = hashes.get(pair.file.path)
        if actual is None:
            continue  # couldn't be read: already reported as UNREADABLE
        # Entries the file does match. With a duplicated path, this says which version is on disk.
        matching = [e for e in pair.entries
                    if e.hash == actual and (e.size is None or e.size == pair.file.size)]
        for entry in pair.entries:
            if entry.size is not None and entry.size != pair.file.size:
                detail = f"size differs: manifest says {entry.size} bytes, disk has {pair.file.size} bytes"
            elif entry.hash != actual:
                detail = "checksum differs from the manifest"
                if matching:
                    # Georgi's review: without this, a good file reads as a bad one.
                    other = matching[0]
                    if other.manifest == entry.manifest:
                        detail = f"the file matches line {other.line}, not line {entry.line}"
                    else:
                        # Different manifests: name both, or "not line 1" is ambiguous.
                        detail = (f"the file matches line {other.line} of {Path(other.manifest).name}, "
                                  f"not line {entry.line} of {Path(entry.manifest).name}")
            else:
                continue
            findings.append(make_finding(
                "HASH_MISMATCH", path=pair.file.path, manifest=entry.manifest, line=entry.line,
                expected_hash=entry.hash, actual_hash=actual, size=pair.file.size, detail=detail))
    return findings


# --- Zero-byte -----------------------------------------------------------------------------

def check_zero_byte(files, pairs, algorithm):
    empty_hash = hashlib.new(algorithm).hexdigest()  # the checksum of "no data at all"
    entries_by_disk_path = {p.file.path: p.entries for p in pairs}
    findings = []
    for f in files:
        if f.size != 0:
            continue
        detail = "file is 0 bytes"
        if any(e.hash == empty_hash for e in entries_by_disk_path.get(f.path, [])):
            # Georgi's F3: empty files arrived on media that was written that way.
            detail += ("; the manifest checksum is also that of an empty file, "
                       "so it was probably already empty when the manifest was made")
        findings.append(make_finding("ZERO_BYTE", path=f.path, size=0, detail=detail))
    return findings


# --- Name hygiene ----------------------------------------------------------------------------

def check_names(files, rules="windows", unicode_matched_paths=frozenset()):
    """Check each folder and file name once. Report problems and a proposed clean name.

    unicode_matched_paths: disk paths already reported as UNICODE_ONLY_MATCH. Their
    Unicode form isn't repeated here (Georgi's review: one issue, one finding).
    """
    bad_chars = NAME_RULES[rules]
    already_explained = {"/".join(p.split("/")[:i + 1])
                         for p in unicode_matched_paths for i in range(p.count("/") + 1)}
    findings, seen = [], set()
    for f in files:
        parts = f.path.split("/")
        for depth, name in enumerate(parts):
            partial_path = "/".join(parts[:depth + 1])
            if partial_path in seen:
                continue  # a bad folder is reported once, not for every file inside it
            seen.add(partial_path)
            problems = _name_problems(name, bad_chars,
                                      check_unicode=partial_path not in already_explained)
            if problems:
                findings.append(make_finding(
                    "NAME_HYGIENE", path=partial_path, proposed_name=_clean_name(name, bad_chars),
                    detail="; ".join(problems)))
    return findings


def _name_problems(name, bad_chars, check_unicode=True):
    problems = []
    found = sorted({c for c in name if c in bad_chars})
    if found:
        problems.append("contains " + " ".join(repr(c) for c in found))
    if any(ord(c) < 32 for c in name):
        problems.append("contains control characters (e.g. tab or newline)")
    if name.startswith(" "):
        problems.append("starts with a space")
    if name.endswith(" "):
        problems.append("ends with a space")
    if "  " in name:
        problems.append("contains double spaces")
    if name.endswith("."):
        problems.append("ends with a full stop")
    if name.split(".")[0].upper() in WINDOWS_RESERVED_NAMES:
        problems.append("uses a name reserved by Windows")
    if check_unicode and unicodedata.normalize("NFC", name) != name:
        problems.append("uses decomposed Unicode (NFD, typical of macOS)")
    return problems


def _clean_name(name, bad_chars):
    """A suggested name only. The tool never renames anything."""
    clean = unicodedata.normalize("NFC", name)
    clean = "".join("_" if (c in bad_chars or ord(c) < 32) else c for c in clean)
    while "  " in clean:
        clean = clean.replace("  ", " ")
    clean = clean.strip(" ").rstrip(". ")
    stem, dot, rest = clean.partition(".")
    if stem.upper() in WINDOWS_RESERVED_NAMES:
        clean = stem + "_" + dot + rest
    return clean


# --- Cross-set comparison ------------------------------------------------------------------

def check_cross_sets(manifests):
    """Compare several manifests: is each path identical everywhere, conflicting, or in one set only?"""
    if len(manifests) < 2:
        return {}, []
    hashes_by_path = {}  # path -> {manifest name: set of hashes}
    for m in manifests:
        for e in m.entries:
            hashes_by_path.setdefault(e.path, {}).setdefault(m.manifest, set()).add(e.hash)

    status, findings = {}, []
    for path, per_manifest in sorted(hashes_by_path.items()):
        if len(per_manifest) == 1:
            status[path] = "unique"
            continue
        all_hashes = set().union(*per_manifest.values())
        if len(all_hashes) == 1:
            status[path] = "identical"
            continue
        status[path] = "conflicting"
        listing = "; ".join(f"{name}: {', '.join(sorted(h))}" for name, h in sorted(per_manifest.items()))
        findings.append(make_finding(
            "CROSS_SET_CONFLICT", path=path,
            detail=f"different checksums in different sets ({listing}). "
                   "This is a finding, not a verdict: the tool cannot tell which version "
                   "is correct or when they diverged."))
    return status, findings
