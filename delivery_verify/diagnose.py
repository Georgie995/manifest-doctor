"""Module 4: group related findings into probable causes, the headline feature.

The individual findings stay in the report. A cause sits above them and says
"these N files are all explained by one thing", with the list of files. A cause
is always a hint for a person to confirm, never a verdict.
"""

from dataclasses import dataclass, field

from .findings import ERROR, INFO, WARNING

NOT_A_VERDICT = "Probable cause, not a verdict."
_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}


@dataclass
class Cause:
    code: str
    severity: str
    summary: str
    paths: list
    note: str = NOT_A_VERDICT


def diagnose(match, scan, findings):
    causes = [
        *_wrapper_folders(match.pairs),
        *_unicode_form(match.pairs),
        *_case_only(match.pairs),
        *_duplicate_listings(findings),
        *_hidden_noise(scan.hidden),
    ]
    # Most serious first; within a severity, the cause affecting the most files first.
    causes.sort(key=lambda c: (_ORDER[c.severity], -len(c.paths)))
    return causes


def _count(n, singular, plural=None):
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def _names_differ(n):
    return "1 file name differs" if n == 1 else f"{n} file names differ"


def _wrapper_folders(pairs):
    groups = {}
    for p in pairs:
        if "prefix" in p.kinds:
            groups.setdefault((p.prefix, p.direction), []).append(p.file.path)
    causes = []
    for (prefix, direction), paths in groups.items():
        files = _count(len(paths), "file")
        if direction == "extra_folder_on_disk":
            summary = (f"{files} only match once the folder {prefix!r} on disk is ignored. "
                       "This usually means the delivery was wrapped in an extra top-level folder.")
        else:
            summary = (f"{files} only match once the folder {prefix!r} at the start of the manifest paths "
                       "is ignored. This usually means the manifest was made one folder level higher "
                       "than the delivery.")
        causes.append(Cause("CAUSE_WRAPPER_FOLDER", WARNING, summary, sorted(paths)))
    return causes


def _unicode_form(pairs):
    paths = sorted(p.file.path for p in pairs if "unicode" in p.kinds)
    if not paths:
        return []
    summary = (f"{_names_differ(len(paths))} from the manifest only in how accented letters "
               "are stored (one character, or a letter plus a separate accent mark). This typically "
               "happens when names made on macOS meet names made on Windows or Linux.")
    return [Cause("CAUSE_UNICODE_FORM", WARNING, summary, paths)]


def _case_only(pairs):
    paths = sorted(p.file.path for p in pairs if "case" in p.kinds)
    if not paths:
        return []
    summary = (f"{_names_differ(len(paths))} from the manifest only in upper/lower case. "
               "Windows and most macOS drives treat these as the same name; case-sensitive storage "
               "(such as Linux or cloud object storage) treats them as different files.")
    return [Cause("CAUSE_CASE_ONLY", WARNING, summary, paths)]


def _duplicate_listings(findings):
    paths = sorted({f.path for f in findings if f.code == "DUPLICATE_ENTRY"})
    if not paths:
        return []
    what = "1 path is" if len(paths) == 1 else f"{len(paths)} paths are"
    summary = (f"{what} listed more than once in a manifest with different checksums. Only one "
               "version can exist at a path, so verification against the other entry will fail. "
               "Check which version was intended.")
    return [Cause("CAUSE_DUPLICATE_LISTING", ERROR, summary, paths)]


def _hidden_noise(hidden_files):
    if not hidden_files:
        return []
    paths = sorted(f.path for f in hidden_files)
    if len(paths) == 1:
        start = "1 system file was set aside (it would otherwise have counted as an extra file)"
    else:
        start = f"{len(paths)} system files were set aside (they would otherwise have counted as extra files)"
    summary = start + ". Files like these are created automatically by macOS and Windows."
    return [Cause("CAUSE_HIDDEN_NOISE", INFO, summary, paths)]
