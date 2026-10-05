# Domain notes

Real failure modes from Georgi's work in ingest, tape archive and file delivery that this tool is designed around. They are written generically, with no client, project or product details.

| # | Failure | How it showed up | What manifest-doctor does about it |
|---|---|---|---|
| 1 | File not fully ingested or corrupted | Silent. The recipient found it, because that workflow had no verify step before sending. | `HASH_MISMATCH`, run before sending |
| 2 | Missing or extra files after an incomplete copy, or junk files included | Found by comparing file counts by hand | `MISSING` / `EXTRA`, with hidden files set aside |
| 3 | Zero-byte files already present on received media | A downstream tool failed | `ZERO_BYTE` |
| 4 | Same path, different content across sets. A re-delivery overwrote the earlier object in cloud storage, but the checksum list kept two entries for that path. | The recipient's verification failed | `DUPLICATE_ENTRY`, `CROSS_SET_CONFLICT`, `CAUSE_DUPLICATE_LISTING` |
| 5 | Mac vs Windows Unicode names, and case-only differences | Verify reported files "missing" that were present | `UNICODE_ONLY_MATCH`, `CASE_ONLY_MATCH` and their causes |
| 6 | Delivery wrapped in an extra top-level folder | Verify listed *everything* as failed without saying which, so the search was manual and slow | `PREFIX_OFFSET_MATCH`, `CAUSE_WRAPPER_FOLDER` |
| 7 | Hidden system files | Broke scripts and automation | `HIDDEN_FILE`, `CAUSE_HIDDEN_NOISE` |
| 8 | Permission errors partway through a run (different copy methods set different permissions) | A script errored out mid-run | `UNREADABLE` per file; the run continues |
| 9 | Read errors on archive media | The software reported counts, not which files, then stalled and crashed | `UNREADABLE` per file, with the reason; the run continues |

Recurring theme: tools said *that* something failed, not *which* files or *why*. That is the gap this tool targets.
