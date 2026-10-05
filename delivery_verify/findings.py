"""The shape of a finding, and the default severity for each finding code.

Every module reports problems the same way, so the reports (module 5) and
the diagnosis (module 4) can treat them all alike.
"""

from dataclasses import dataclass

ERROR = "ERROR"
WARNING = "WARNING"
INFO = "INFO"

# Georgi's "strict" defaults (docs/DECISIONS.md). Profiles may override them later.
DEFAULT_SEVERITY = {
    "MISSING": ERROR,
    "HASH_MISMATCH": ERROR,
    "ZERO_BYTE": ERROR,
    "DUPLICATE_ENTRY": ERROR,
    "CROSS_SET_CONFLICT": ERROR,
    "UNREADABLE": ERROR,
    "MANIFEST_LINE_UNREADABLE": ERROR,
    "EXTRA": WARNING,
    "UNICODE_ONLY_MATCH": WARNING,
    "CASE_ONLY_MATCH": WARNING,
    "PREFIX_OFFSET_MATCH": WARNING,
    "NAME_HYGIENE": WARNING,
    "ABSOLUTE_PATHS_DETECTED": WARNING,
    "HIDDEN_FILE": INFO,
    "DUPLICATE_SAME_HASH": INFO,
}


@dataclass
class Finding:
    code: str
    severity: str
    path: str | None = None
    detail: str = ""
    manifest: str | None = None
    line: int | None = None


def make_finding(code, **details):
    """Create a finding with its default severity, so severities live in one place."""
    return Finding(code=code, severity=DEFAULT_SEVERITY[code], **details)
