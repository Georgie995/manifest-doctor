# Decisions

Each entry records the decision, the alternatives considered and why this one was chosen.

## 2026-10-05: Headline feature is diagnosis, not verification

- **Decision:** do the standard manifest comparison, then group findings into probable causes.
- **Alternatives:** a plain verifier like the original brief.
- **Why:** `ascmhl`, `hashdeep` audit mode, `rclone check` and BagIt validators already report missing, extra and mismatched files. Georgi's repeated pain was tools saying *that* something failed but not *which* files or *why*.

## 2026-10-05: Resume support dropped

- **Decision:** no resume support.
- **Alternatives:** keep it, as in the original brief.
- **Why:** there is no confirmed real failure behind it (records were never lost in practice). Building it would add complexity to defend without a story behind it.

## 2026-10-05: Manifest formats

- **Decision:** support md5sum-style, pipe-delimited, and CSV with a header row (columns matched by name).
- **Alternatives:** md5sum only; MHL XML.
- **Why:** these are the three formats Georgi has worked with. MHL is already handled by `ascmhl`.

## 2026-10-05: Algorithms

- **Decision:** MD5 (default) and SHA-256, both from the standard library. No xxHash.
- **Why:** Georgi has only seen MD5 in practice. xxHash would need a new dependency for a case he hasn't met.

## 2026-10-05: Absolute paths

- **Decision:** three modes (`suggest` by default, `auto`, `off`) plus an explicit `--strip-prefix`, settable per workflow profile.
- **Alternatives:** suggest-only; auto-only.
- **Why:** Georgi said the right behaviour depends on the workflow. Some workflows auto-strip, others shouldn't. The default never guesses silently.

## 2026-10-05: Severity defaults

- **Decision:** "strict". ERROR for missing, mismatch, zero-byte, duplicate entry, cross-set conflict, unreadable. WARNING for extra, Unicode/case/prefix-only matches, name hygiene. INFO for hidden files. All overridable per profile.
- **Why:** this was Georgi's choice.

## 2026-10-05: Illegal-character rules

- **Decision:** two profiles. `windows` (default, from Microsoft's published naming rules) and `strict` (adds Netflix's public footage-ingest list).
- **Why:** Georgi chose both, as profiles. Both sources are public and cited. The strict profile is described as linting, not certification.

## 2026-10-05: Settings file format

- **Decision:** TOML, read with `tomllib`.
- **Alternatives:** JSON; YAML.
- **Why:** `tomllib` is in the standard library from Python 3.11. TOML is easier for people to read than JSON. YAML would need a dependency.

## 2026-10-05: Test tool is pytest

- **Decision:** pytest, a development-only dependency.
- **Alternatives:** `unittest` from the standard library.
- **Why:** pytest tests use plain `assert`, which is easier for Georgi to read and edit. The tool itself still uses only the standard library.

## 2026-10-05: Exit code 1 only for ERRORs

- **Decision:** exit code 1 only when there is at least one ERROR. Profiles can set `fail_on = "warning"`.
- **Alternatives:** fail on warnings too.
- **Why:** warnings such as an extra file are worth reading but shouldn't trigger an alert for every delivery. Automation (n8n) branches on this code.

## 2026-10-05: Extra files not hashed by default

- **Decision:** don't hash extra files unless `--hash-extras` is given.
- **Alternatives:** always hash them.
- **Why:** it saves time on large deliveries. The flag is there when you need to check whether an "extra" is really a renamed expected file.

## 2026-10-05: Manifest parsing details (module 1)

- **Spaces:** spaces in paths are never trimmed. Leading and double spaces are a hygiene finding for later, and trimming them would hide it.
- **md5sum separator:** the strict md5sum separator (`hash` + space + space-or-`*`) is tried first, then a single space. This keeps a file name that really starts with a space intact.
- **Duplicate listings:** a duplicate path with a different hash keeps *both* entries, so later checks can show each version. With the same hash, it is collapsed to one entry with an INFO note.
- **File-level problems:** a manifest that is empty, unreadable, not UTF-8, or has no recognisable lines raises `ManifestError`. That is a tool error (exit code 2), because a run without a usable manifest proves nothing.
- **Mixed paths:** a mix of absolute and relative paths gets a finding but no suggested prefix, because no single prefix fits safely.

## 2026-10-05: Smarter prefix suggestion (planned for module 5)

- **Problem:** found in Georgi's module 1 quiz. Suggesting the *longest* shared folder can strip one folder too many. For example, when every file is under `D:/Deliveries/ShowA/` but the folder being checked still contains `ShowA/`.
- **Decision:** when the CLI has both the manifest and the folder, it tries each candidate prefix and suggests the one that makes the most manifest paths match real files.
- **Interim:** until module 5, module 1 suggests the longest shared folder, clearly labelled as a suggestion.
- **Approved by Georgi:** 2026-10-05.

## 2026-10-05: Scanning and hashing details (module 2)

- **Hidden files:** only the configured list of system files is set aside (`.DS_Store`, `Thumbs.db`, `desktop.ini`, `._*`, and anything inside `.Spotlight-V100`, `.Trashes`, `.fseventsd`, `.TemporaryItems`). Other names starting with a dot are checked like normal files. Treating every dot-file as hidden could hide a real deliverable.
- **Zero-byte files:** the scan only records sizes. Zero-byte files are flagged by the checks in module 3, so each module has one job.
- **Errors on one file or folder:** a folder that can't be listed, or a file whose size or contents can't be read, gives an `UNREADABLE` finding and the run continues. Only a missing or non-folder root is a tool error (exit code 2).
- **Simulated errors in tests:** tests use simulated errors (pytest's `monkeypatch` swaps in a function that raises an error) rather than real locked files. Real permission changes behave differently on Windows, macOS and Linux, and would make the tests unreliable.
- **Symbolic links:** links to folders are not followed (the `os.walk` default), which avoids loops. A link to a file is checked as the file it points to. This is a known limit.

## 2026-10-05: Matching and checks details (module 3)

- **No guessing:** when two files are equally good candidates in pass 2 or 3, nothing is paired and both stay missing/extra. A wrong pairing would hide a real problem behind a confident-looking explanation.
- **Wrapper folders:** pass 3 accepts any number of leading folders, not only one. When two manifest paths could claim the same file, the longer (more specific) path wins.
- **Pass 3 limit:** pass 3 doesn't combine with pass 2. A file that is *both* in a wrapper folder *and* differs in Unicode or case stays unpaired. This is a known limit.
- **Size before checksum:** a size difference counts as a mismatch even before the checksum is compared. The file is still hashed so both checksums appear in the report.
- **No double explanations:** a file that couldn't be read isn't also called a mismatch. It already has one correct explanation (UNREADABLE).
- **Duplicate listings:** each entry of a duplicated path is checked separately against the file. In the cloud-overwrite case, the older entry fails, just as the client's check did.
- **Zero-byte hint:** when a zero-byte file's manifest checksum is also the "empty file" checksum, the detail says it was probably empty at the source. That points the investigation upstream (Georgi's F3).
- **Name problems:** each folder or file name is checked once. A bad folder name gives one finding, not one per file inside it. The proposed clean name is text only.
- **Clean names can collide:** two different bad names can produce the same proposed name (e.g. `a?.mov` and `a*.mov` both become `a_.mov`). This is not detected yet. It is a known limit.
- **Cross-set comparison:** it compares paths after tidying and prefix rules, but doesn't merge Unicode or case variants across manifests. Conflict wording always says the tool cannot tell which version is correct.

## 2026-10-05: Changes from Georgi's mid-project review of real output

Georgi reviewed the findings for two synthetic deliveries (mixed problems; a wrapped delivery) as an operator would.

- **Changed: the duplicate-version mismatch says which entry the file matches.** For example: "the file matches line 5, not line 4". Before, a good file read as a bad one.
- **Changed: a Mac-style (NFD) name gives one finding, not two.** The `UNICODE_ONLY_MATCH` wording now explains the difference in words: "the manifest writes é as one character; the disk writes it as a letter plus a separate accent mark". The two names look identical on screen, so showing both explained nothing. The name-hygiene check no longer repeats the Unicode problem for a name already explained by a match. Other problems with that name are still reported.
- **Confirmed: a wrapper folder stays a WARNING** (exit code 0). Georgi's judgement is that warnings are enough for this case.
- **Confirmed: a zero-byte file stays an ERROR**, even when the manifest shows it was already empty at the source. There are no legitimate empty files in his deliveries.

## 2026-10-05: Diagnosis details (module 4)

- **Causes sit above findings.** Causes are added *above* the findings, not instead of them. The report keeps every individual finding so nothing is hidden, and the causes say what groups of findings have in common.
- **Five causes:**
  - wrapper folder: one cause per folder and direction;
  - Unicode form;
  - upper/lower case;
  - duplicate listing;
  - hidden-file noise.

  A name that differs in both Unicode and case appears in both causes.
- **Severity of a cause:** each cause carries the severity of the findings it explains (duplicate listing ERROR; wrapper, Unicode, case WARNING; hidden INFO). Causes are ordered most serious first, then by number of files.
- **Hint, not verdict:** every cause carries the note "Probable cause, not a verdict." The wording says "usually" or "typically", never "this is".
- **No cause for mismatches and missing files yet.** No single explanation reliably covers those, so they stay as individual findings. Inventing a cause would be guessing.
- **Wording claims:** the claims in the cause text are general platform behaviour, not industry statistics. macOS drives are usually case-insensitive (rclone docs, https://rclone.org/overview/). Changing operating systems creates hidden system files (Netflix footage-ingest guide).

## 2026-10-05: Reports and command line (module 5)

- **A new dated folder every run** (`report-YYYY-MM-DD_HHMMSS`, with `-2`, `-3` if two runs share a second). Georgi's choice: old reports are never overwritten, so there's a full history.
- **Absolute paths in suggest mode stop with exit code 2** (Georgi's choice), because nothing was really verified. The message names the prefix that makes the most manifest paths match files actually in the folder (approved fix from the module 1 quiz), and says how many match. If no prefix fits, it says so and suggests checking the folder. No report is written.
- **Report folder inside the checked folder is refused** (exit code 2). The report would become an "extra" file in the delivery.
- **Settings in three layers:** built-in defaults, then the profile, then the command line. Each value's source is recorded in the report header. Mistakes in the settings file (unknown setting, unknown finding code, invalid value, broken TOML) stop the tool with a clear message rather than being ignored.
- **Severity overrides** from a profile are applied to findings before the exit code is decided. Cause severities are not overridden. This is a known limit.
- **CSV is written as UTF-8 with a byte-order mark,** so Excel shows accented names correctly. JSON keeps accented characters as they are rather than escaping them.
- **Shortened summary lists:** `summary.md` lists up to 20 files per cause and 50 findings (configurable defaults), then points to `report.csv` for the full list.
- **Runs without installing:** the tool works as `python -m manifest_doctor` (via `__main__.py`), as well as the `manifest-doctor` command once installed.
- **Odd characters can't crash it:** printing to a terminal that can't show a character (for example a combining accent on an older Windows console) shows a `\u…` code instead of crashing.

## 2026-10-05: Read-only tool

- **Decision:** never modify the tree being checked. The report folder can't be inside it.
- **Why:** this is a project rule (never rename, move or delete user files by default). A report written inside the tree would also show up as an extra file.

## 2026-10-05: Project renamed from delivery-verify to manifest-doctor

- **Decision:** rename the repository, Python package (`manifest_doctor`), command, settings file (`manifest-doctor.toml`) and default report folder.
- **Why:** "doctor" is a familiar developer convention for "diagnose what's wrong" (for example `brew doctor`), which matches the headline feature. No PyPI package or GitHub project with this name was found on 2026-10-05.
- **Rejected names:**
  - names with "sleuth": strongly associated with The Sleuth Kit forensics tools;
  - "delivery-doctor": search results are dominated by medical-delivery software.
- **Approved by:** Georgi.

## 2026-10-11: Mismatch wording names both manifests

- **Change:** when the file matches an entry in *another* manifest, the detail now names both, e.g. "the file matches line 1 of set1.md5, not line 1 of set2.md5". Before, it ended "…not line 1", which didn't say which manifest. Found while building ai-triage's harness cases. Manifest file names are shown, not full local paths.

## 2026-10-11: An opt-in progress file, for the Delivery Desk app

- **Need:** the Delivery Desk app (a desktop window over delivery-desk) shows real progress while a delivery is checked: files done, the current file, time left. Georgi chose real progress over a spinner, because "is it still going, and how long left?" is the exact anxiety behind job-watch.
- **Decision:** `--progress-file PATH`, off by default. While checking, it keeps a small JSON file up to date:
  - fields: `stage` (preparing, hashing, finished), `files_done`/`files_total`, `bytes_done`/`bytes_total`, `current_file`, `updated_at`;
  - written at most about 4 times a second;
  - each update goes to a temporary copy first and is then swapped in, so a reader never sees half a file;
  - "finished" is written only after the reports are on disk.
- **Why a file and not printed lines:** when alerts are on, delivery-ops-hub runs manifest-doctor and keeps its printed output until the end. It already passes extra options through unchanged, so a file works on both routes with no change to delivery-ops-hub.
- **Safety:**
  - a progress file inside the delivery is refused, because it would turn up as an "extra" file;
  - a write that fails is skipped with one warning, and the check carries on, because the report is what matters;
  - with the option off, file reading is called exactly as before, and the original 149 tests pass unchanged.
- **Tested by:** 10 new tests, checked by breaking 7 protections on purpose. Two of those breaks were missed at first (warn-once, swap-in-whole), so the tests were strengthened until both were caught.
