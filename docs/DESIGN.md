# delivery-verify: design

Status: **Approved by Georgi on 2026-10-05.**

## 1. What problem this solves

Whenever data is copied, moved or stored (ingest, delivery, archive write, restore, migration, sync, reorganisation, packaging, or simply sitting on storage), "the job finished" is not evidence that the data is right.

Existing tools (`md5sum -c`, ASC MHL's `ascmhl`, `hashdeep`, `rclone check`, BagIt validators) already tell you *that* files are missing, extra or different. In real work, the slow part is working out *why*:

- A whole delivery wrapped in an extra top folder shows up as "everything missing, everything extra".
- A Mac-made name and a Windows-made name that look identical are reported as missing.
- A manifest that lists the same file twice with two different checksums fails at the recipient's end.

`delivery-verify` does the standard comparison and then **groups the findings into probable causes, listing exactly which files each cause affects**.

It is **read-only**. It never renames, moves, deletes or changes permissions on anything it checks.

## 2. Words used in this document

| Term | Meaning |
|---|---|
| **Manifest** | A text file listing files and their expected checksums: "what should be here". |
| **Checksum / hash** | A short fingerprint calculated from a file's contents. If one byte changes, the fingerprint changes. MD5 and SHA-256 are two ways (algorithms) of calculating it. |
| **Tree** | The folder being checked, with everything inside it: "what is here". |
| **Finding** | One problem about one file, e.g. "this file is missing". Each has a **code**, a **severity** and a **path**. |
| **Severity** | How serious a finding is: `ERROR`, `WARNING` or `INFO`. |
| **Probable cause** | A group of findings that one explanation accounts for, e.g. "these 40 missing and 40 extra files are the same files under an extra top folder". A hint, not a verdict. |
| **Unicode normalisation (NFC/NFD)** | The same visible letter, e.g. "é", can be stored as one character (NFC) or as "e" plus an accent (NFD). macOS often produces NFD. Most other systems produce NFC. The names look identical but compare as different. |
| **Exit code** | The number a program returns when it finishes. Other automation reads it: 0 = clean, 1 = problems found, 2 = the tool itself failed. |
| **JSON** | A structured text format of labelled fields that other programs can read reliably. |
| **SQLite** | A small database stored in a single file. It is built into Python, so it needs no extra install. |
| **TOML** | A simple settings-file format. Python 3.11+ can read it without extra libraries. |
| **CLI** | Command-line interface: running the tool by typing a command. |

## 3. How it is used

```
delivery-verify check TREE --manifest FILE [--manifest FILE ...] [options]
```

| Option | Default | Purpose |
|---|---|---|
| `--manifest FILE` | (required, repeatable) | One or more manifests. Giving several turns on the cross-set comparison. |
| `--algorithm md5\|sha256` | `md5` | Which checksum the manifests use. |
| `--profile NAME` | none | Load a named workflow profile from the settings file (section 8). |
| `--prefix-mode suggest\|auto\|off` | `suggest` | What to do when manifest paths are absolute (section 5.3). |
| `--strip-prefix TEXT` | none | Remove this exact start from every manifest path. |
| `--name-rules windows\|strict` | `windows` | Which illegal-character list to use (section 6.2). |
| `--out DIR` | `./delivery-verify-report` | Where reports go. Refuses a folder inside TREE, because the report would become an "extra" file. |
| `--sqlite` | off | Also write findings to `findings.sqlite`. |
| `--hash-extras` | off | Also hash files that are not in any manifest. |

Exit codes: `0` no ERROR findings, `1` at least one ERROR finding, `2` the tool could not run (unreadable manifest, TREE missing, bad option). A profile can set `fail_on = "warning"` to make warnings fail too.

## 4. Overall flow

```
manifests ──► 1. READ MANIFESTS ──► expected entries ─┐
                                                      ├─► 3. MATCH (3 passes) ──► 4. HASH matched files
tree ───────► 2. SCAN TREE ───────► actual files ─────┘                                  │
                                                                                         ▼
                        7. WRITE REPORTS ◄── 6. DIAGNOSE (probable causes) ◄── 5. RUN CHECKS
```

Each numbered step is one module, so it can be explained, tested and quizzed on its own.

## 5. Step by step

### 5.1 Read manifests (`manifest.py`)

Three formats, which are the ones Georgi has worked with. **The format is detected, not assumed**:

| Format | Example line | How it is recognised |
|---|---|---|
| md5sum style | `d41d8cd98f00b204e9800998ecf8427e  Folder/file.mov` | Line starts with a hex string of the right length for the algorithm, then whitespace, then the path. |
| Pipe | `Folder/file.mov\|d41d8cd98f00b204e9800998ecf8427e` | Line contains `\|` and one side is a hex string of the right length. |
| CSV with header | `path,size,md5` then rows | First line is a header that names a path column and a hash column. Column names are matched from a configurable list (e.g. `path`, `file`, `filename`; `md5`, `hash`, `checksum`). A `size` column is used if present. |

Rules:

- Lines that can't be understood are **not silently skipped**. Each one becomes a `MANIFEST_LINE_UNREADABLE` finding with the manifest name and line number.
- Paths are tidied for comparison only: `\` becomes `/`, and a leading `./` is removed. The original text is kept for the report.
- The same path listed twice with **different** hashes gives `DUPLICATE_ENTRY` (Georgi's S3 case). Listed twice with the same hash, it is only counted once (`DUPLICATE_SAME_HASH`, INFO).
- Known limit: GNU md5sum "escapes" names containing a backslash or newline by starting the line with `\`. Those lines are not decoded. They are reported as `MANIFEST_LINE_UNREADABLE`, not skipped.
- Known limit: a `\` is always treated as a folder separator, so a macOS file name that really contains a backslash would be misread.

### 5.2 Scan the tree (`scan.py`)

- Walk every folder under TREE and record each file's relative path and size.
- Sort paths so reads happen in a predictable order (see design note 9.2).
- Classify hidden and system files (configurable list: `.DS_Store`, `Thumbs.db`, `desktop.ini`, `._*` AppleDouble files, `.Spotlight-V100/`, `.Trashes/`, `.fseventsd/`). They are set aside before matching, so they never count as "extra". Each is reported once as `HIDDEN_FILE` (INFO).

### 5.3 Absolute paths in manifests

Georgi's answer: it depends on the workflow. So all three behaviours are available, and the profile or option chooses:

- `suggest` (default): if all manifest paths share an absolute start such as `/Volumes/Drive/Job/`, the tool stops, reports `ABSOLUTE_PATHS_DETECTED` and tells you the exact `--strip-prefix` to re-run with. It never guesses silently.
- `auto`: the shared start is removed automatically and recorded in the report header ("stripped prefix: …"), so the result can be audited.
- `off`: paths are used exactly as written.
- `--strip-prefix TEXT` always wins over the mode.

### 5.4 Match (`match.py`)

Matching pairs each expected entry with an actual file. It runs in **three passes**. Each pass only looks at what the earlier passes could not pair:

1. **Exact:** the same path, character for character.
2. **Normalised:** the same path after Unicode normalisation (NFC) and/or ignoring case. Each pair is labelled `UNICODE_ONLY_MATCH` or `CASE_ONLY_MATCH`, so you can see exactly which names differ and how.
3. **Prefix offset:** an expected path and an actual path that are the same once one top-level folder is added or removed. For example, `Job/Reel1/a.mov` on disk and `Reel1/a.mov` in the manifest. These are paired and tagged with the folder name.

Whatever is still unpaired at the end is a genuine `MISSING` (expected but not on disk) or `EXTRA` (on disk but not expected).

**Why passes (for the walkthrough):** it is how a person troubleshoots. First check the obvious, then the "same name, written differently" cases, then the "everything shifted by one folder" case. Doing them in order means each file ends up with one clear explanation, never two.

### 5.5 Hash (`hashing.py`)

- Only paired files are hashed. Extra files are not hashed by default, which saves time.
- Files are read in **1 MiB chunks** and never loaded whole, because deliverables can be very large.
- If a CSV manifest gives a size, sizes are compared first. A size difference is already a mismatch, so it can be reported without the slow hash. The file is still hashed so both hashes appear in the report.
- If a file can't be read (permissions, I/O error), it gets an `UNREADABLE` finding with the reason, and **the run continues**. This answers Georgi's failure modes 8 (permissions mid-run) and 9 (one bad read crashed the whole job).

### 5.6 Checks (`checks.py`)

| Code | What it means | Default severity |
|---|---|---|
| `MISSING` | In a manifest, not on disk | ERROR |
| `HASH_MISMATCH` | Paired, but the checksum (or size) differs. Shows both hashes and sizes. | ERROR |
| `ZERO_BYTE` | File is 0 bytes | ERROR |
| `DUPLICATE_ENTRY` | Same path listed more than once in one manifest with different hashes | ERROR |
| `CROSS_SET_CONFLICT` | Same path in two or more manifests with different hashes | ERROR |
| `UNREADABLE` | File could not be read; the reason is recorded | ERROR |
| `MANIFEST_LINE_UNREADABLE` | A manifest line could not be understood | ERROR |
| `EXTRA` | On disk, not in any manifest | WARNING |
| `UNICODE_ONLY_MATCH` | Paired only after Unicode normalisation | WARNING |
| `CASE_ONLY_MATCH` | Paired only after ignoring case | WARNING |
| `PREFIX_OFFSET_MATCH` | Paired only after adding or removing a top folder | WARNING |
| `NAME_HYGIENE` | Problem characters or spacing in a name (section 6.2), with a *proposed* clean name. Nothing is renamed. | WARNING |
| `ABSOLUTE_PATHS_DETECTED` | Manifest paths are absolute (see 5.3) | WARNING |
| `HIDDEN_FILE` | System or hidden file, set aside | INFO |
| `DUPLICATE_SAME_HASH` | Same path listed twice in one manifest with the same hash. Harmless, so it is kept once and noted. | INFO |

Severities are Georgi's "strict" choice and can be changed per profile.

**Cross-set comparison** (when there is more than one manifest): every path is classified as `identical` (same hash everywhere it appears), `conflicting` (different hashes, giving `CROSS_SET_CONFLICT`) or `unique` (in one set only). The report lists each conflict with every set's hash. It does **not** say which version is correct. The tool cannot know that.

### 5.7 Diagnose (`diagnose.py`), the headline feature

After the checks, related findings are grouped into **probable causes**:

| Cause | Triggered when | What the report says |
|---|---|---|
| `CAUSE_WRAPPER_FOLDER` | One or more `PREFIX_OFFSET_MATCH` pairs share the same folder | "N files only match if the folder `X/` is added/removed. This usually means the delivery was wrapped in (or lost) a top-level folder." Lists the N files. |
| `CAUSE_UNICODE_FORM` | One or more `UNICODE_ONLY_MATCH` | "N names differ only in Unicode form (e.g. made on macOS vs Windows)." Lists before/after names. |
| `CAUSE_CASE_ONLY` | One or more `CASE_ONLY_MATCH` | "N names differ only in upper/lower case." Lists them. |
| `CAUSE_HIDDEN_NOISE` | Hidden/system files were set aside | "N system files were ignored (would otherwise have been EXTRA)." |
| `CAUSE_DUPLICATE_LISTING` | Any `DUPLICATE_ENTRY` | "N paths are listed more than once with different hashes. Only one version can exist at that path, so verification against the other entry will fail. Check which version was intended." |

Every cause carries the wording **"probable cause, not a verdict"**.

## 6. Settings and sources

### 6.1 Defaults are labelled as defaults

Any threshold or list that doesn't come from a cited public source is a configurable default, and the code comment says so.

### 6.2 Name rules (two profiles, Georgi's choice)

- **`windows` (default).** Reserved characters `< > : " / \ | ? *`, control characters 0–31, reserved names (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`), and names ending in a space or full stop. Source: Microsoft, "Naming Files, Paths, and Namespaces", https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file (accessed 2026-10-05). Also, as configurable defaults: leading spaces and double spaces.
- **`strict`.** Adds the characters listed in Netflix's public "Footage Ingest – Preparing Your Media For Upload" guide (https://studiopartner.netflix.net/studio/footageingest-prep, accessed 2026-10-05). The README must say this is a **linting profile, not a certification** of meeting any platform's requirements.

## 7. Outputs (`report.py`)

All are written to `--out`, which is never inside TREE:

- **`report.json`:** for automation. A header (tool version, time, tree, manifests, algorithm, profile, prefix stripped, counts by severity), then `causes[]`, then `findings[]`. Each finding has `code`, `severity`, `path`, `detail` and, where relevant, `expected_hash`, `actual_hash`, `size`, `manifest`, `line`. The schema is documented in `docs/report-schema.md`. Project 2 (n8n) depends on it.
- **`report.csv`:** one row per finding, for people using a spreadsheet.
- **`summary.md`:** a short human summary at the top: counts, probable causes first, then the top findings.
- **`findings.sqlite`** (only with `--sqlite`): the same findings in a table, plus example queries in the walkthrough, e.g. "count findings by code".

## 8. Workflow profiles (`config.py`)

Optional `delivery-verify.toml`. Each named profile can set: algorithm, prefix mode, name rules, hidden-file list, severity overrides, CSV column names. Example:

```toml
[profiles.cloud-delivery]
algorithm = "md5"
prefix_mode = "auto"
name_rules = "strict"

[profiles.tape-restore]
prefix_mode = "suggest"
severity.EXTRA = "ERROR"
```

Command-line options override the profile, and the profile overrides the built-in defaults. The report header records which values were used and where they came from.

## 9. Design notes

### 9.1 Chunked hashing

Reading a file in 1 MiB pieces keeps memory use flat whether the file is 1 KB or 500 GB.

### 9.2 Read order

Files are hashed in sorted path order. On tape-backed or network storage, reading files in a random order can be dramatically slower than reading them in sequence, because the drive has to seek back and forth. Sorting by path is a simple, predictable order. True tape-order reading (by position on tape) is **not** implemented, because it needs information from the tape index. It is noted as a possible link to the optional tape-index project.

### 9.3 Probable cause vs verdict

The tool can show that two sets differ, with sizes and hashes. It can't know which is correct or when they diverged, and the wording everywhere must reflect that.

### 9.4 Read-only by design

The tool never modifies TREE. Proposed clean names are text in the report only.

### 9.5 No network

No network access anywhere. Sending the report to n8n is a separate step in Project 2.

## 10. Testing

- **Synthetic fixtures only.** `tools/make_fixtures.py` builds a tree and manifests in `fixtures_out/` (git-ignored) containing **one deliberate instance of every finding code and every probable cause**, with made-up names like `ShowA/Reel01/clip_0001.mov`.
- Case-only differences can't be created as real files on Windows (the filesystem treats them as the same name), so that case is tested through manifest entries. A real-file version runs only where the filesystem supports it, and is skipped otherwise.
- Unreadable files: tested by simulating a read error in the hashing step. Changing real permissions behaves differently on Windows and Linux.
- Each check gets a test that **fails first**, then the code that makes it pass.
- Acceptance tests:
  - The full fixture produces exactly the expected findings and causes, nothing more.
  - A clean tree gives exit code 0 and no findings.
  - The wrapper-folder fixture produces **one** `CAUSE_WRAPPER_FOLDER` listing its files, not a wall of missing and extra findings.

## 11. Build order (modules), each ending with a walkthrough and a five-question quiz

1. **Manifest reading:** formats, CSV headers, path tidying, duplicates, absolute paths.
2. **Scanning and hashing:** tree walk, hidden files, chunked hashing, unreadable files.
3. **Matching and checks:** the three passes, cross-set comparison, name hygiene.
4. **Diagnosis:** probable causes.
5. **Reports and CLI:** JSON, CSV, Markdown, SQLite, exit codes, profiles.
6. **Fixtures, end-to-end test, README:** including "why not just use ascmhl / hashdeep / rclone check?" and the AI-assistance statement.

## 12. Resolved questions (2026-10-05)

1. **Test tool:** pytest, a development-only install used only to run tests.
2. **Failing level:** exit code `1` only when there are ERRORs. Warnings are reported but don't fail the run. Changeable per profile (`fail_on = "warning"`).
3. **Extra files:** not hashed by default. The `--hash-extras` flag turns it on.
4. **Names:** the command is `delivery-verify` and the Python package is `delivery_verify`.
