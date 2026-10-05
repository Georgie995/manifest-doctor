"""Module 2, part 1: list what is actually in the folder ("what is here").

Read-only: this only looks at names and sizes. Nothing is opened, changed or moved.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from .findings import make_finding

# Configurable defaults: operating-system clutter that is set aside rather than
# reported as EXTRA. Georgi's failure F7: these files broke scripts and automation.
HIDDEN_NAMES = (".DS_Store", "Thumbs.db", "desktop.ini")
HIDDEN_PREFIXES = ("._",)  # macOS AppleDouble companions, e.g. "._clip.mov"
HIDDEN_FOLDERS = (".Spotlight-V100", ".Trashes", ".fseventsd", ".TemporaryItems")


class ScanError(Exception):
    """The folder itself can't be checked. The tool stops (exit code 2)."""


@dataclass
class FileInfo:
    path: str  # relative to the folder being checked, always with "/"
    size: int


@dataclass
class ScanResult:
    files: list
    hidden: list
    findings: list


def scan_tree(root, hidden_names=HIDDEN_NAMES, hidden_prefixes=HIDDEN_PREFIXES,
              hidden_folders=HIDDEN_FOLDERS):
    root = Path(root)
    if not root.exists():
        raise ScanError(f"{root}: does not exist")
    if not root.is_dir():
        raise ScanError(f"{root}: is not a folder")

    files, hidden, findings = [], [], []

    def folder_error(error):
        # Called by os.walk when a folder can't be opened. Record it and keep going,
        # so one locked folder doesn't stop the whole check.
        findings.append(make_finding(
            "UNREADABLE", path=_relative(root, Path(error.filename)),
            detail=f"folder could not be listed: {error.strerror}"))

    for folder, _subfolders, names in os.walk(root, onerror=folder_error):
        for name in names:
            full_path = Path(folder) / name
            relative = _relative(root, full_path)
            try:
                size = _file_size(full_path)
            except OSError as error:
                findings.append(make_finding(
                    "UNREADABLE", path=relative, detail=f"size could not be read: {error.strerror}"))
                continue
            info = FileInfo(relative, size)
            if _is_hidden(relative, hidden_names, hidden_prefixes, hidden_folders):
                hidden.append(info)
            else:
                files.append(info)

    # A fixed order makes reports repeatable and reads predictable (DESIGN.md 9.2).
    files.sort(key=lambda f: f.path)
    hidden.sort(key=lambda f: f.path)
    findings.extend(make_finding("HIDDEN_FILE", path=f.path, detail="system file set aside")
                    for f in hidden)
    return ScanResult(files, hidden, findings)


def _file_size(path):
    return path.stat().st_size


def _relative(root, path):
    return path.relative_to(root).as_posix()


def _is_hidden(relative, names, prefixes, folders):
    *parent_folders, name = relative.split("/")
    return (name in names
            or name.startswith(tuple(prefixes))
            or any(folder in folders for folder in parent_folders))
