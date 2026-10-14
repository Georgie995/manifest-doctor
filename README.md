# manifest-doctor

[![tests](https://github.com/Georgie995/manifest-doctor/actions/workflows/tests.yml/badge.svg)](https://github.com/Georgie995/manifest-doctor/actions/workflows/tests.yml) *Tests run on Linux and Windows after every change.*

A read-only tool that checks a folder against its checksum manifest and explains **why** things don't match, not just **that** they don't.

## The problem

When data is copied, delivered, archived, restored or migrated, "the job finished" is not evidence that the data is right. Standard verification tools tell you *that* files are missing, extra or different. In real delivery work, the slow part is working out *why*:

- A delivery wrapped in one extra top folder shows up as "every file missing, every file extra".
- A file name typed on a Mac and the same name typed on Windows look identical, but are stored differently, so the file is reported missing.
- A manifest that lists the same file twice, with two different checksums, will fail verification at the recipient's end even though the file on disk is fine.

These come from real failures handled in post-production ingest, tape archive and delivery work (written up generically in [docs/domain-notes.md](docs/domain-notes.md)).

## What it does

1. **Reads the manifest(s)**: md5sum style (`hash  path`), pipe (`path|hash`) or CSV with a header row. The format is detected automatically. Unreadable lines are reported with their line number, never skipped.
2. **Scans the folder**: names and sizes only, read-only. Known system clutter (`.DS_Store`, `Thumbs.db`, `._*` files and similar) is set aside.
3. **Matches** each manifest entry to a file in three passes:
   1. exact name;
   2. same name ignoring Unicode form or upper/lower case;
   3. same name ignoring extra leading folders.

   If two files fit equally well, it doesn't guess.
4. **Checksums** paired files in 1 MiB pieces (MD5 or SHA-256). A file that can't be read is reported, with the reason, and the run continues.
5. **Checks**: missing, extra, size or checksum mismatch, zero-byte, problem names (with a *proposed* clean name; nothing is renamed), duplicate listings, and conflicts between several manifests.
6. **Diagnoses**: groups related findings into **probable causes** (wrapper folder, Unicode form, case only, duplicate listing, system-file noise), each listing the files it covers. Every cause is labelled *"Probable cause, not a verdict."*
7. **Reports**: writes `report.json` (for automation), `report.csv` (for spreadsheets), `summary.md` (for people) and optionally `findings.sqlite`, into a new dated folder each run.
8. **Says what it proved**: a few plain sentences at the end of `summary.md` (and in `report.json`), worked out from what the check actually did. For example: how many listed files were read in full and matched, what wasn't checked and why (not found, unreadable, a folder that couldn't be opened, manifest lines that couldn't be read, extra or system files), and what no checksum check can tell you.

It never modifies, renames, moves or deletes anything in the folder it checks, and it makes no network calls.

## Quick start

Requires Python 3.11 or newer. The tool itself uses only the Python standard library.

```bash
git clone <this repository>
cd manifest-doctor

# Make a synthetic sample delivery with one example of every problem
python -m tools.make_fixtures

# Check it
python -m manifest_doctor check fixtures_out/delivery --manifest fixtures_out/manifest_set1.md5 --manifest fixtures_out/manifest_set2.md5 --out fixtures_out/reports
```

To run the tests (needs `pytest`, used for testing only):

```bash
python -m venv .venv
.venv/Scripts/python -m pip install pytest      # on macOS/Linux: .venv/bin/python
.venv/Scripts/python -m pytest
```

## Example run (real output, synthetic data)

```
RESULT: PROBLEMS FOUND (8 errors, 5 warnings, 2 info)
  ERROR: 1 path is listed more than once in a manifest with different checksums. Only one version can exist at a path, so verification against the other entry will fail. Check which version was intended.
  WARNING: 1 file only matches once the folder 'Wrapper_Folder/' on disk is ignored. This usually means the delivery was wrapped in an extra top-level folder.
  WARNING: 1 file name differs from the manifest only in how accented letters are stored (one character, or a letter plus a separate accent mark). This typically happens when names made on macOS meet names made on Windows or Linux.
  WARNING: 1 file name differs from the manifest only in upper/lower case. Windows and most macOS drives treat these as the same name; case-sensitive storage (such as Linux or cloud object storage) treats them as different files.
  INFO: 1 system file was set aside (it would otherwise have counted as an extra file). Files like these are created automatically by macOS and Windows.
Reports: fixtures_out/reports/report-2026-10-05_161615
```

Exit code: `1`. The full finding list (missing file, checksum mismatches, zero-byte file, conflict between the two manifests, and so on) is in `summary.md`, `report.csv` and `report.json`.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Checked; no ERROR findings (warnings may exist) |
| `1` | Checked; at least one ERROR finding |
| `2` | Could not check: unusable manifest, folder missing, settings mistake, report folder inside the delivery, or absolute manifest paths in `suggest` mode (the message says exactly which `--strip-prefix` to use) |

`2` must never be treated as "clean": nothing was verified.

## Compare two versions of a list

When a delivery has been sent more than once, its checksum list changes from version to version. To find where a problem started, compare two versions at a time and work backwards:

```bash
python -m manifest_doctor compare delivery_v1.md5 delivery_v2.md5 --out reports
```

- **Only the two lists are read.** No folder is needed, and no file is opened.
- **How files are paired:** by exact name first, then by a checksum that appears exactly once in each list. Never by similar-looking names.
- **What it shows:**
  - **Changed:** same name, different checksum. This usually points at the problem.
  - **Renamed or moved:** same checksum, different name.
  - **Only in the earlier list**, and **only in the later list**.
  - **Can't tell which became which:** a checksum shared by several files, or a name listed more than once. These are shown together, not guessed.
  - **Empty files:** all empty files share one checksum, so they're never paired.
- **A changed file whose old content now sits under another name** is pointed out. This is the re-delivery pattern behind "one path, two versions".
- **Lines that couldn't be read** are counted first, because a cut-off list makes files wrongly look as if they're only in the other list.
- **Results:** `comparison.json`, `comparison.csv` and `summary.md`, in a new dated `compare-…` folder each time.
- **Exit codes:** `0` the lists describe exactly the same files; `1` they differ; `2` they couldn't be compared, for example because a list is missing, empty, unreadable, or uses a different checksum type.

## Options and workflow profiles

| Option | Default | Purpose |
|---|---|---|
| `--manifest FILE` | required, repeatable | One or more manifests. Two or more turn on the cross-set comparison. |
| `--algorithm md5\|sha256` | `md5` | Checksum algorithm used by the manifests |
| `--prefix-mode suggest\|auto\|off` | `suggest` | Handling of absolute manifest paths (`D:\…`, `/Volumes/…`) |
| `--strip-prefix TEXT` | – | Remove this start from every manifest path |
| `--name-rules windows\|strict` | `windows` | Name rules: Windows-reserved characters (Microsoft), or a stricter list from Netflix's public footage-ingest guide. **A lint profile, not a certification of any platform's requirements.** |
| `--hash-extras` | off | Also checksum files not in any manifest |
| `--profile NAME`, `--config FILE` | – | Load a named profile from `manifest-doctor.toml` |
| `--out DIR` | `manifest-doctor-report` | Where report folders go (refused if inside the checked folder) |
| `--sqlite` | off | Also write `findings.sqlite` |
| `--progress-file PATH` | off | Keep a small JSON file up to date with how far the check has got (files and bytes done, the current file), for apps that show a progress bar. It's updated a few times a second, and an update held back is still written a moment later, so it always shows the file being read, even if the check gets stuck. It must be outside the folder being checked. A problem writing it never stops the check. |

Example profile file:

```toml
[profiles.tape-restore]
severity.EXTRA = "ERROR"   # nothing unexpected may come back from tape
fail_on = "warning"
```

The report header records where every setting came from: default, profile or command line.

**Empty files are always errors, by design.** A 0-byte file is an ERROR even when the manifest's checksum shows it was already empty at the source. The finding says so, but isn't softened, because in my experience files that arrived empty from the source still broke a downstream tool. If your deliveries legitimately include empty files (placeholders, for example), lower it in a profile: `severity.ZERO_BYTE = "WARNING"`.

## Why not just use the standard tool?

Use them. This tool complements them rather than replacing them.

| Tool | What it already does well | What this adds |
|---|---|---|
| `md5sum -c` | Checks every file listed | Extra-file detection, a machine-readable report, diagnosis |
| [ASC MHL](https://github.com/ascmitc/mhl) (`ascmhl`) | Chain-of-custody hash lists for camera media; required by some platforms; detects missing and extra files | Works on plain md5sum, pipe and CSV manifests, and explains *why* files don't match |
| [hashdeep](https://github.com/jessek/hashdeep) audit mode | Reports matched, moved, new and missing files | Grouped probable causes, JSON/CSV reports, name checks |
| [`rclone check`](https://rclone.org/commands/rclone_check/) | Per-file missing/differ lists between two locations | Diagnosis of wrapper folders, Unicode and case; duplicate-listing detection |
| [BagIt](https://www.rfc-editor.org/rfc/rfc8493) validators | Strict package validation | Works on deliveries that aren't BagIt packages |

If you already work with ASC MHL, keep using `ascmhl` for chain of custody.

## Known limits

- **Testing so far:** developed and used on Windows 11. The tests also run on GitHub's Linux and Windows machines (Python 3.11 and 3.13) after every change; the badge at the top shows the latest result. macOS is not tested.
- **Extra columns in pipe manifests:** a `|` inside a file name is allowed, because the checksum is always at one end of the line. So a line with an extra column next to the name (e.g. `path|size|hash`) is read with that column as part of the name. It is still reported, as a missing file whose name shows the extra column, never passed.
- **Simulated errors:** unreadable files are tested by simulating the error, not with real locked files.
- **Wrapper folders combined with name differences:** a file that is *both* inside an extra folder *and* differs in Unicode or case is not paired.
- **Clean-name collisions:** two different problem names can produce the same proposed clean name. This is not detected yet.
- **Backslashes:** a `\` in a manifest path is always treated as a folder separator.
- **Escaped md5sum lines:** GNU md5sum lines starting with `\` (escaped names) are reported as unreadable, not decoded.
- **Algorithms:** MD5 and SHA-256 only (no xxHash). No ASC MHL (XML) input; use `ascmhl` for that.
- **Cause severities:** profiles can change finding severities, not cause severities.
- **Symbolic links:** links to folders are not followed.
- **Read order:** files are read in sorted path order, not in physical order on tape.

## How it was built

Design, decisions and explanations are in [`docs/`](docs/):

- [DESIGN.md](docs/DESIGN.md): how it works, step by step, with a glossary.
- [DECISIONS.md](docs/DECISIONS.md): every design choice, the alternatives considered, and why.
- [walkthrough.md](docs/walkthrough.md): plain-English explanation of each module, interview-style questions and practice exercises.
- [report-schema.md](docs/report-schema.md): the `report.json` format.
- [domain-notes.md](docs/domain-notes.md): the real-world failure modes the tool is built around.

All test data is synthetic. No client names, project or tape codes, hostnames or internal paths appear anywhere.

## AI assistance

The code in this repository was written with an AI coding assistant (Claude, by Anthropic). I did not write the Python by hand.

What I did:

- **Specified it.** The problem and the checks come from failures I have handled in post-production ingest, LTO/LTFS tape and delivery work. I chose:
  - the manifest formats to support;
  - the severity of each finding;
  - how absolute paths should be handled;
  - that wrapper folders are warnings and zero-byte files are errors;
  - that every run keeps its own report.
- **Directed and approved the design** before any code was written. The decisions are logged in `docs/DECISIONS.md`.
- **Reviewed the behaviour as an operator.** I ran the tool on synthetic deliveries and judged the output. That review changed the tool:
  - a duplicate-version mismatch now says which entry the file matches;
  - a Mac-style name gives one clear explanation instead of two confusing ones.

  Working through how it handled absolute paths, I found that its suggested prefix could strip one folder too many. That was fixed so it tests the suggestion against the real folder.
- **Learned how it works.** Every module has a written walkthrough and a quiz, which I worked through. I can explain each part, and I'm continuing to practise making changes to it.

The assistant wrote the tests first, from these requirements, and each test was shown failing before the code that makes it pass.

## Licence

[MIT](LICENSE) © 2026 Georgi Stoyanov
