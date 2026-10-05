"""Module 1: read a manifest ("what should be here") into a list of entries.

Supports the three formats seen in real work: md5sum style, pipe-delimited,
and CSV with a header row. The format is detected from the file, not assumed.
"""

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from .findings import make_finding

HASH_LENGTH = {"md5": 32, "sha256": 64}

# Configurable defaults: header names accepted for each CSV column (lower case).
CSV_PATH_NAMES = ("path", "file", "filename", "filepath", "file_path", "name")
CSV_HASH_NAMES = ("hash", "checksum", "md5", "md5sum", "sha256")
CSV_SIZE_NAMES = ("size", "bytes", "filesize", "size_bytes")


class ManifestError(Exception):
    """The manifest file itself can't be used. The tool stops (exit code 2)."""


@dataclass
class Entry:
    path: str           # tidied, used for comparison
    original_path: str  # exactly as written in the manifest, for the report
    hash: str
    size: int | None
    manifest: str
    line: int


@dataclass
class ManifestResult:
    manifest: str
    format: str
    entries: list
    findings: list
    suggested_prefix: str | None = None
    stripped_prefix: str | None = None


def read_manifest(path, algorithm="md5", prefix_mode="suggest", strip_prefix=None):
    path = Path(path)
    name = str(path)
    lines = _read_lines(path)
    hash_len = HASH_LENGTH[algorithm]

    fmt, start = _detect_format(lines, hash_len)
    if fmt is None:
        raise ManifestError(f"{name}: no line looks like a supported manifest format")

    entries, findings = [], []
    if fmt == "csv":
        _parse_csv(lines, start, name, hash_len, entries, findings)
    else:
        parse_line = _parse_md5sum_line if fmt == "md5sum" else _parse_pipe_line
        for number, text in enumerate(lines, start=1):
            if text == "":
                continue
            parsed = parse_line(text, hash_len)
            if parsed is None:
                findings.append(_unreadable(name, number, text))
            else:
                original, digest = parsed
                entries.append(Entry(_tidy(original), original, digest.lower(), None, name, number))

    result = ManifestResult(name, fmt, entries, findings)
    _apply_prefix_rules(result, prefix_mode, strip_prefix)
    _handle_duplicates(result)
    return result


# --- Reading the file --------------------------------------------------------

def _read_lines(path):
    try:
        raw = path.read_bytes()
    except OSError as err:
        raise ManifestError(f"{path}: cannot be read ({err.strerror})") from err
    try:
        # utf-8-sig quietly drops the "byte order mark" some Windows tools add.
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as err:
        raise ManifestError(f"{path}: is not UTF-8 text (byte {err.start})") from err
    # Split on newlines only and drop a trailing "\r". Spaces are NOT stripped:
    # leading or trailing spaces in names are a problem to report, not hide.
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    if all(line.strip() == "" for line in lines):
        raise ManifestError(f"{path}: is empty")
    return lines


# --- Recognising the format ----------------------------------------------------

def _detect_format(lines, hash_len):
    """Return (format, index of the first line it was recognised on)."""
    for index, text in enumerate(lines):
        if text.strip() == "":
            continue
        if _csv_columns(text) is not None:
            return "csv", index
        if _parse_md5sum_line(text, hash_len):
            return "md5sum", index
        if _parse_pipe_line(text, hash_len):
            return "pipe", index
    return None, None


def _is_hash(text, hash_len):
    return re.fullmatch(f"[0-9a-fA-F]{{{hash_len}}}", text) is not None


def _parse_md5sum_line(text, hash_len):
    # md5sum writes: hash, a space, then a space (text mode) or "*" (binary mode), then the path.
    match = re.fullmatch(f"([0-9a-fA-F]{{{hash_len}}}) [ *](.+)", text)
    if match is None:
        # Some tools write only one space between hash and path.
        match = re.fullmatch(f"([0-9a-fA-F]{{{hash_len}}}) (.+)", text)
    if match is None:
        return None
    return match.group(2), match.group(1)


def _parse_pipe_line(text, hash_len):
    parts = text.split("|")
    if len(parts) != 2:
        return None
    left, right = parts
    if _is_hash(right.strip(), hash_len):
        return left, right.strip()
    if _is_hash(left.strip(), hash_len):
        return right, left.strip()
    return None


def _csv_columns(header_line):
    """If this line is a CSV header naming a path and a hash column, return their positions."""
    names = [cell.strip().lower() for cell in next(csv.reader([header_line]))]
    columns = {}
    for key, accepted in (("path", CSV_PATH_NAMES), ("hash", CSV_HASH_NAMES), ("size", CSV_SIZE_NAMES)):
        for position, cell in enumerate(names):
            if cell in accepted:
                columns[key] = position
                break
    if "path" in columns and "hash" in columns:
        return columns
    return None


def _parse_csv(lines, header_index, name, hash_len, entries, findings):
    columns = _csv_columns(lines[header_index])
    for number, text in enumerate(lines[header_index + 1:], start=header_index + 2):
        if text.strip() == "":
            continue
        row = next(csv.reader([text]))
        try:
            original = row[columns["path"]]
            digest = row[columns["hash"]].strip()
            size_text = row[columns["size"]].strip() if "size" in columns else ""
            size = int(size_text) if size_text else None
        except (IndexError, ValueError):
            findings.append(_unreadable(name, number, text))
            continue
        if not _is_hash(digest, hash_len) or original == "":
            findings.append(_unreadable(name, number, text))
            continue
        entries.append(Entry(_tidy(original), original, digest.lower(), size, name, number))


def _unreadable(name, number, text):
    return make_finding("MANIFEST_LINE_UNREADABLE", manifest=name, line=number,
                        detail=f"could not understand line: {text!r}")


# --- Paths -------------------------------------------------------------------

def _tidy(original):
    """Make paths comparable: forward slashes, no leading './'. Nothing else changes."""
    tidied = original.replace("\\", "/")
    while tidied.startswith("./"):
        tidied = tidied[2:]
    return tidied


def _is_absolute(tidied):
    # "/..." covers macOS/Linux and "//server/share"; "D:/..." covers Windows drive letters.
    return tidied.startswith("/") or re.match(r"[A-Za-z]:/", tidied) is not None


def _common_folder(paths):
    """The longest folder path that every path starts with, ending in '/'."""
    folders = [p.split("/")[:-1] for p in paths]
    common = []
    for parts in zip(*folders):
        if len(set(parts)) != 1:
            break
        common.append(parts[0])
    return "/".join(common) + "/" if common else None


def _apply_prefix_rules(result, prefix_mode, strip_prefix):
    if strip_prefix is not None:
        prefix = _tidy(strip_prefix)
        prefix = prefix if prefix.endswith("/") else prefix + "/"
        _strip(result, prefix)
        return
    if prefix_mode == "off" or not result.entries:
        return

    absolute = [e for e in result.entries if _is_absolute(e.path)]
    if not absolute:
        return
    if len(absolute) < len(result.entries):
        # A mix of absolute and relative paths: no single prefix can be suggested safely.
        result.findings.append(make_finding(
            "ABSOLUTE_PATHS_DETECTED", manifest=result.manifest,
            detail=f"{len(absolute)} of {len(result.entries)} paths are absolute; "
                   "use --strip-prefix to choose what to remove"))
        return

    prefix = _common_folder([e.path for e in result.entries])
    if prefix_mode == "auto" and prefix is not None:
        _strip(result, prefix)
        return
    result.suggested_prefix = prefix
    result.findings.append(make_finding(
        "ABSOLUTE_PATHS_DETECTED", manifest=result.manifest,
        detail=f"all paths start with {prefix!r}; re-run with --strip-prefix {prefix!r}"))


def best_prefix(manifest_paths, disk_paths):
    """Choose the prefix to strip that makes the most manifest paths match real files.

    Tries every folder level of the shared start, e.g. 'D:/', 'D:/Deliveries/',
    'D:/Deliveries/ShowA/'. The longest shared folder can strip one level too many
    (found in Georgi's module 1 quiz). Returns (prefix, number matched).
    """
    common = _common_folder(list(manifest_paths))
    if common is None:
        return None, 0
    parts = common.rstrip("/").split("/")
    candidates = ["/".join(parts[:i + 1]) + "/" for i in range(len(parts))]
    disk = set(disk_paths)
    scored = [(sum(p[len(c):] in disk for p in manifest_paths), c) for c in candidates]
    best_count = max(count for count, _ in scored)
    if best_count == 0:
        return common, 0  # nothing fits: fall back to the longest shared folder
    # Among equally good candidates, prefer the shortest: it removes the least information.
    return next(c for count, c in scored if count == best_count), best_count


def _strip(result, prefix):
    for entry in result.entries:
        if entry.path.startswith(prefix):
            entry.path = entry.path[len(prefix):]
    result.stripped_prefix = prefix


# --- Duplicates ----------------------------------------------------------------

def _handle_duplicates(result):
    first_seen = {}
    kept = []
    for entry in result.entries:
        earlier = first_seen.get(entry.path)
        if earlier is None:
            first_seen[entry.path] = entry
            kept.append(entry)
        elif earlier.hash == entry.hash:
            # Same file listed twice: harmless, so keep one and note it.
            result.findings.append(make_finding(
                "DUPLICATE_SAME_HASH", path=entry.path, manifest=result.manifest, line=entry.line,
                detail=f"also listed on line {earlier.line} with the same hash"))
        else:
            # Only one file can exist at a path, so one of these entries will always fail.
            # Both are kept so later checks and the report can show each version.
            kept.append(entry)
            result.findings.append(make_finding(
                "DUPLICATE_ENTRY", path=entry.path, manifest=result.manifest, line=entry.line,
                detail=f"line {earlier.line} has {earlier.hash}, line {entry.line} has {entry.hash}"))
    result.entries = kept
