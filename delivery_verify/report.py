"""Module 5: write the reports. JSON for automation, CSV for spreadsheets,
a short Markdown summary for people, and optionally SQLite for queries.

Every run gets its own dated folder, so earlier reports are never overwritten.
"""

import csv
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from . import __version__
from .findings import ERROR, INFO, WARNING

CSV_COLUMNS = ["severity", "code", "path", "detail", "manifest", "line",
               "expected_hash", "actual_hash", "size", "proposed_name"]
SUMMARY_LIST_LIMIT = 20      # configurable default: files listed per cause in summary.md
SUMMARY_FINDING_LIMIT = 50   # configurable default: findings listed in summary.md
_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}


def result_label(exit_code, counts):
    if exit_code == 1:
        return "PROBLEMS FOUND"
    return "PASSED WITH WARNINGS" if counts[WARNING] else "CLEAN"


def sorted_findings(findings):
    return sorted(findings, key=lambda f: (_ORDER[f.severity], f.code, f.path or ""))


def count_by_severity(findings):
    return {level: sum(f.severity == level for f in findings) for level in (ERROR, WARNING, INFO)}


def write_reports(result, out_dir, settings, sources, exit_code, sqlite=False, now=None):
    now = now or datetime.now().astimezone()
    folder = _new_folder(Path(out_dir), now)
    findings = sorted_findings(result.findings)
    counts = count_by_severity(findings)
    header = _header(result, settings, sources, exit_code, counts, now)

    _write_json(folder / "report.json", header, result.causes, findings)
    _write_csv(folder / "report.csv", findings)
    _write_summary(folder / "summary.md", header, result.causes, findings)
    if sqlite:
        _write_sqlite(folder / "findings.sqlite", result.causes, findings)
    return folder


def _new_folder(out_dir, now):
    base = f"report-{now:%Y-%m-%d_%H%M%S}"
    suffix = 1
    while True:
        folder = out_dir / (base if suffix == 1 else f"{base}-{suffix}")
        try:
            folder.mkdir(parents=True, exist_ok=False)
            return folder
        except FileExistsError:
            suffix += 1  # never overwrite an earlier report


def _header(result, settings, sources, exit_code, counts, now):
    cross = result.cross_set.values()
    return {
        "tool": "delivery-verify",
        "version": __version__,
        "run_at": now.isoformat(timespec="seconds"),
        "tree": str(Path(result.tree).resolve()),
        "result": result_label(exit_code, counts),
        "exit_code": exit_code,
        "counts": counts,
        "settings": {k: {"value": settings[k], "source": sources[k]} for k in settings},
        "manifests": [{"path": m.manifest, "format": m.format, "entries": len(m.entries),
                       "stripped_prefix": m.stripped_prefix} for m in result.manifests],
        "cross_set": {status: sum(s == status for s in cross)
                      for status in ("identical", "conflicting", "unique")} if result.cross_set else None,
    }


def _write_json(path, header, causes, findings):
    data = {"header": header,
            "causes": [asdict(c) for c in causes],
            "findings": [asdict(f) for f in findings]}
    # ensure_ascii=False keeps names like "Café" readable instead of "Caf\u00e9".
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_csv(path, findings):
    # "utf-8-sig" adds the marker Excel needs to show accented names correctly.
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for f in findings:
            writer.writerow({k: v for k, v in asdict(f).items() if k in CSV_COLUMNS})


def _write_summary(path, header, causes, findings):
    counts = header["counts"]
    lines = [
        "# Delivery verification summary",
        "",
        f"**RESULT: {header['result']}** "
        f"({counts[ERROR]} errors, {counts[WARNING]} warnings, {counts[INFO]} info)",
        "",
        f"- Folder checked: `{header['tree']}`",
        f"- Run at: {header['run_at']}",
        *(f"- Manifest: `{m['path']}` ({m['format']}, {m['entries']} entries"
          + (f", stripped prefix `{m['stripped_prefix']}`" if m["stripped_prefix"] else "") + ")"
          for m in header["manifests"]),
        "",
        "## Probable causes",
        "",
    ]
    if not causes:
        lines.append("None found.")
    for cause in causes:
        lines += ["", f"### {cause.severity}: {cause.code}", "", cause.summary, "", f"*{cause.note}*", ""]
        shown = cause.paths[:SUMMARY_LIST_LIMIT]
        lines += [f"- `{p}`" for p in shown]
        if len(cause.paths) > len(shown):
            lines.append(f"- … and {len(cause.paths) - len(shown)} more (full list in report.csv)")
    lines += ["", "## Findings", ""]
    if not findings:
        lines.append("None.")
    else:
        lines += ["| Severity | Code | Path | Detail |", "|---|---|---|---|"]
        for f in findings[:SUMMARY_FINDING_LIMIT]:
            where = f.path if f.path is not None else f"{f.manifest} line {f.line}"
            detail = f.detail
            if f.proposed_name is not None:
                detail += f" → proposed name: `{f.proposed_name}`"
            lines.append(f"| {f.severity} | {f.code} | `{where}` | {_cell(detail)} |")
        if len(findings) > SUMMARY_FINDING_LIMIT:
            lines.append(f"\n… and {len(findings) - SUMMARY_FINDING_LIMIT} more findings (full list in report.csv)")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _cell(text):
    return text.replace("|", "\\|").replace("\n", " ")


def _write_sqlite(path, causes, findings):
    db = sqlite3.connect(path)
    try:
        with db:  # commits the inserts as one transaction
            db.execute(f"CREATE TABLE findings ({', '.join(CSV_COLUMNS)})")
            db.executemany(f"INSERT INTO findings VALUES ({', '.join('?' * len(CSV_COLUMNS))})",
                           [tuple(getattr(f, c) for c in CSV_COLUMNS) for f in findings])
            db.execute("CREATE TABLE causes (cause_id, code, severity, summary, note)")
            db.execute("CREATE TABLE cause_paths (cause_id, cause_code, path)")
            for cause_id, c in enumerate(causes, start=1):
                db.execute("INSERT INTO causes VALUES (?, ?, ?, ?, ?)",
                           (cause_id, c.code, c.severity, c.summary, c.note))
                db.executemany("INSERT INTO cause_paths VALUES (?, ?, ?)",
                               [(cause_id, c.code, p) for p in c.paths])
    finally:
        db.close()  # "with db" commits but doesn't close; an open file stays locked on Windows
