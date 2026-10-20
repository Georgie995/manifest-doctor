# Walkthrough

One section per module. Each has a plain-English explanation, interview questions with short answers, and "change this behaviour" exercises.

---

## Module 1: reading manifests (`manifest_doctor/manifest.py`)

### What it does, step by step

Think of this as the step where the tool reads the delivery paperwork before it looks at a single file.

1. **Open the manifest as UTF-8 text** (`_read_lines`).
   - UTF-8 is the standard way of storing text, including accents and Cyrillic.
   - Some Windows tools put an invisible marker at the start (a "byte order mark"). It is removed.
   - If the file isn't UTF-8, is empty, or can't be opened, the tool **stops** with a `ManifestError`. A check against a broken manifest proves nothing, so it's better to refuse than to report "all clear".
   - The text is split into lines, and **spaces are never trimmed**. A name with a leading or double space is a problem to report later; trimming would hide it.

2. **Work out the format** (`_detect_format`). It looks at the first meaningful line:
   - Is it a CSV header that names a path column and a hash column? Then it's **csv**.
   - Does it start with a hash of the right length (32 characters for MD5, 64 for SHA-256), then a space? Then it's **md5sum**.
   - Is it two parts separated by `|`, one of which is a hash? Then it's **pipe**.
   - Nothing recognisable anywhere means a `ManifestError`.

3. **Read every line into an entry.** An entry is the path as written, a tidied path, the hash (always lower case), the size if the CSV has one, the manifest name and the line number.
   - Any line that doesn't fit becomes a `MANIFEST_LINE_UNREADABLE` finding with its line number. It is **never silently skipped**: a skipped line would make a missing file invisible.

4. **Tidy paths** (`_tidy`). Backslashes become forward slashes, and a leading `./` is removed, so `.\ShowA\clip.mov` and `ShowA/clip.mov` compare as equal. The original text is kept for the report.

5. **Handle absolute paths** (`_apply_prefix_rules`). If paths look like `/Volumes/Drive/Job/...` or `D:/Deliveries/...`, the shared start (the longest folder path common to all of them) is found. Then:
   - **suggest** (default): change nothing, record `ABSOLUTE_PATHS_DETECTED`, and say exactly which `--strip-prefix` to use.
   - **auto**: remove the shared start and record what was removed, so it can be audited.
   - **off**: leave paths exactly as written.
   - An explicit `--strip-prefix` always wins.

6. **Look for duplicate listings** (`_handle_duplicates`).
   - Same path, **same** hash: harmless. Keep one and add an INFO note.
   - Same path, **different** hashes: an ERROR (`DUPLICATE_ENTRY`). Only one file can exist at a path, so verification against one of the entries is bound to fail. This is exactly the cloud-overwrite case. Both entries are kept so the report can show both hashes.

### How it's tested

`tests/test_manifest.py` has 24 tests. Each one writes a tiny made-up manifest into a temporary folder, reads it, and checks the result. Run them all with:

```bash
.venv/Scripts/python -m pytest -q
```

### Interview questions (try answering before you open the answers)

<details><summary>1. Why does the tool detect the manifest format instead of being told?</summary>
Manifests come from different tools and vendors. Detecting the format removes a manual step that people get wrong. If detection fails, the tool stops rather than guessing.
</details>

<details><summary>2. Why are bad lines reported instead of skipped?</summary>
A skipped line is a file nobody checks, so it would be silently "verified". Reporting it with its line number makes the gap visible.
</details>

<details><summary>3. Why don't you trim spaces from file names?</summary>
Leading or double spaces are a real cause of failed matches and broken scripts. Trimming would hide the problem the tool is meant to find.
</details>

<details><summary>4. What is a ManifestError, and why stop instead of carrying on?</summary>
It means the manifest file itself is unusable: empty, unreadable, the wrong text encoding, or no recognisable lines. Carrying on would produce a report that looks clean but proves nothing. It maps to exit code 2, meaning the tool couldn't do its job.
</details>

<details><summary>5. What happens with the same path listed twice?</summary>
With the same hash, it's kept once and noted (INFO). With different hashes, it's an ERROR, because only one file can exist at that path, so one entry must fail. Both are kept for the report.
</details>

<details><summary>6. Why three modes for absolute paths?</summary>
Different workflows want different things. The safe default (suggest) never guesses. Auto is for workflows that always strip, and records what it removed. Off is for when absolute paths are intended.
</details>

<details><summary>7. Why convert backslashes to forward slashes?</summary>
Windows writes paths with `\` and macOS/Linux with `/`. Converting means the same file compares equal whichever system wrote the manifest. The known limit is that a Mac file name containing a real backslash would be misread.
</details>

<details><summary>8. How does it tell an MD5 manifest from a SHA-256 one?</summary>
By length: an MD5 hash is 32 hexadecimal characters and a SHA-256 hash is 64. You choose the algorithm with `--algorithm`, and lines with the wrong length are reported.
</details>

<details><summary>9. Why is every hash stored in lower case?</summary>
Hex is case-insensitive (`ABC` is the same value as `abc`), but text comparison isn't. Lower-casing makes comparison reliable.
</details>

<details><summary>10. Did you write this code?</summary>
No. The code is AI-assisted. I specified the formats and behaviours from real failures I've handled, decided the severities and the absolute-path modes, reviewed the tests, and I can explain each step and change it.
</details>

### Exercises: change this behaviour

1. **Add a CSV column name.**
   - Make the reader accept a header called `digest` as the hash column. (Hint: `CSV_HASH_NAMES` near the top of `manifest.py`.)
   - Add a test like `test_csv_header_names_are_case_insensitive_aliases`, and watch it fail before your change and pass after.
2. **Make same-hash duplicates a warning.**
   - Change `DUPLICATE_SAME_HASH` from INFO to WARNING. (Hint: `findings.py`.)
   - Which test fails? Update it.
3. **Treat `#` lines as comments.**
   - Make lines starting with `#` be ignored rather than reported as unreadable.
   - Write the test first. Then think about whether this could hide a real file name starting with `#` in a pipe or CSV manifest, and record your answer in `DECISIONS.md`.

---

## Module 2: scanning the folder and calculating checksums (`scan.py`, `hashing.py`)

### What it does, step by step

Module 1 read the paperwork ("what should be here"). Module 2 looks at the shelf ("what is here").

**Scanning (`scan.py`)**

1. **Check the folder exists and is a folder.** If not, the tool stops with a `ScanError` (exit code 2), because there is nothing to verify.
2. **Walk through every folder and sub-folder** with Python's `os.walk`, and record each file's path, relative to the folder being checked and always written with `/`, plus its size.
3. **Set system clutter aside.** `.DS_Store`, `Thumbs.db`, `desktop.ini`, macOS `._` companion files, and anything inside folders like `.Spotlight-V100` or `.Trashes` go into a separate "hidden" list. Each gets an INFO note. They are never counted as extra files. Only this list is set aside, which you can change. An ordinary file starting with a dot is still checked, because it might be a real deliverable.
4. **If a folder can't be opened, or a file's size can't be read,** the problem is recorded as `UNREADABLE` with the reason, and the scan **carries on**.
5. **Sort everything by path**, so every run lists files in the same order.

Nothing is opened, changed or moved during the scan. It only looks at names and sizes.

**Hashing (`hashing.py`)**

1. **`hash_file` reads a file in 1 MiB pieces** (about one million bytes). Each piece is fed into the checksum calculation and then forgotten, so a 500 GB file needs no more memory than a 1 KB file.
2. **`hash_files` hashes a list of files in sorted order.** Reading in a steady, predictable order is kinder to tape-backed and network storage than jumping around.
3. **If one file fails** (locked, permission denied, vanished, or a read error halfway through, like a bad section on media), it gets an `UNREADABLE` finding with the reason, and **the next file is still hashed**. This is the direct answer to the job that stalled and crashed on bad reads, and to the run that died on a permissions error.

### How it's tested

- `tests/test_scan.py` builds small made-up folders and checks the file list, the sizes, the hidden-file handling and the error handling.
- `tests/test_hashing.py` checks:
  - the answers against known checksums (the MD5 of `hello` is published everywhere);
  - that reading in tiny pieces gives the same answer as reading all at once;
  - the read order;
  - that errors on one file don't stop the others.
- Errors are **simulated**: the test swaps in a stand-in function that raises an error, because real locked files behave differently on each operating system.

### Interview questions

<details><summary>1. Why read files in pieces instead of all at once?</summary>
Media files can be hundreds of gigabytes. Loading one whole would exhaust memory. Reading 1 MiB at a time keeps memory use flat, and the answer is identical. A test proves that.
</details>

<details><summary>2. How do you know the chunked checksum is correct?</summary>
Tests compare it against known published values (for example the MD5 of `hello`, and of an empty file) and against Python's own all-at-once calculation using a deliberately tiny piece size.
</details>

<details><summary>3. What happens if one file can't be read in a run of 10,000?</summary>
It gets an `UNREADABLE` finding with the operating system's reason, and the other 9,999 are still checked. The report says exactly which file failed and why. That's the opposite of a tool that reports "3 errors", stalls and crashes.
</details>

<details><summary>4. Why aren't all files starting with a dot treated as hidden?</summary>
Only known system clutter is set aside. Treating every dot-file as hidden could hide a real deliverable from the check, which is a silent failure. The list is configurable.
</details>

<details><summary>5. Why sort the files?</summary>
Repeatable reports (the same order every run), and a steadier read pattern. On tape-backed or network storage, random-order reads can be much slower than sequential ones.
</details>

<details><summary>6. Why isn't "folder doesn't exist" just another finding?</summary>
If the folder isn't there, nothing was checked. Reporting "0 problems" would be false reassurance, so it's a tool error (exit code 2) instead.
</details>

<details><summary>7. How do you test a locked file without actually locking one?</summary>
With pytest's `monkeypatch`, which temporarily swaps the real function for a stand-in that raises the same error the operating system would. Real permission changes behave differently on Windows, macOS and Linux, so this keeps tests reliable everywhere.
</details>

<details><summary>8. Does scanning change anything on disk?</summary>
No. It only reads names and sizes, and hashing only reads contents. The tool is read-only by design.
</details>

<details><summary>9. Why are zero-byte files not flagged here?</summary>
Each module has one job. The scan records sizes faithfully, including 0, and the checks in module 3 decide what's a problem. That keeps each part simple to test and explain.
</details>

<details><summary>10. What does the tool do with symbolic links (shortcuts)?</summary>
Links to folders aren't followed, which avoids endless loops. A link to a file is checked as the file it points to. This is documented as a known limit.
</details>

### Exercises: change this behaviour

1. **Add a hidden file.**
   - Make `Icon\r` (the macOS custom-folder-icon file) count as system clutter.
   - Write the test first by copying one of the `hidden_path` examples.
2. **Change the piece size.**
   - Change `CHUNK_SIZE` to 4 MiB.
   - Which single test fails, and why is it right that it fails?
3. **Make hidden files warnings.**
   - Make `HIDDEN_FILE` a WARNING instead of INFO for a workflow where any clutter in a delivery is unacceptable.
   - Where is the one place to change it?

---

## Module 3: matching and checks (`match.py`, `checks.py`, `verify.py`)

### What it does, step by step

Module 1 read "what should be here" and module 2 found "what is here". Module 3 lines them up and decides what's wrong.

**Matching (`match.py`): three passes, like a person troubleshooting.**

1. **Exact.** The manifest says `ShowA/a.mov` and the disk has `ShowA/a.mov`. Paired.
2. **Same name, written differently.** Of what's left, pair names that are the same once you ignore:
   - **Unicode form**: `Café` typed on a Mac vs on Windows. They look identical but are stored differently.
   - **upper/lower case**: `Clip.MOV` vs `clip.mov`.
   Each pair gets a WARNING saying exactly how the names differ.
3. **Shifted by a folder.** Of what's still left, pair names that are the same once leading folders are ignored. For example, the disk has `JobX/Reel01/a.mov` and the manifest says `Reel01/a.mov`. This works in both directions: an extra folder on disk, or an extra folder in the manifest.

**Never guess.** If two files fit equally well, the tool pairs neither and leaves them for a person to look at. A wrong pairing would be worse than no pairing, because it would hide a real problem behind a confident answer.

Whatever is still unpaired at the end is genuinely **MISSING** (expected, not on disk) or **EXTRA** (on disk, not expected).

**Checks (`checks.py`): one small function per check.**

| Check | What it reports |
|---|---|
| `check_missing` | Each missing entry, with manifest name and line number |
| `check_extra` | Each extra file (with its checksum, if `--hash-extras` was used) |
| `check_pairs` | Checksum or size mismatch. Shows expected and actual checksum and the size. Each entry of a duplicated path is checked separately. |
| `check_zero_byte` | 0-byte files. If the manifest's checksum is also the "empty file" checksum, it says the file was probably already empty at the source. |
| `check_names` | Bad characters, spaces, trailing full stops, Windows-reserved names, Mac-style Unicode. Each folder or name is checked once and given a *proposed* clean name. Nothing is renamed. |
| `check_cross_sets` | With two or more manifests, each path is `identical`, `conflicting` or `unique`. Conflicts are an ERROR whose wording says the tool cannot tell which version is right. |

**Running it all (`verify.py`).** One function runs the steps in order: read manifests, scan, match, hash (paired files, plus extras only if asked), run checks, and collect every finding into one list.

### How it's tested

- `tests/test_match.py` uses plain lists of names, with no real files. That's how upper/lower-case differences can be tested on Windows, which can't hold two such files in one folder.
- `tests/test_checks.py` tests each check on its own.
- `tests/test_verify.py` builds small made-up deliveries on disk and runs everything end to end:
  - a clean delivery gives no findings;
  - a messy one gives exactly the expected findings, and nothing else;
  - a wrapper-folder delivery still has its checksums verified.

### Interview questions

<details><summary>1. Why match in three passes instead of all at once?</summary>
So each file ends up with exactly one explanation, the simplest one that fits. Exact first, then "written differently", then "shifted by a folder". Each pass only sees what the earlier passes couldn't explain.
</details>

<details><summary>2. What happens when two files could match one manifest entry?</summary>
Nothing is paired. Both stay as missing/extra for a person to look at. A wrong automatic match would hide a real problem.
</details>

<details><summary>3. How does the tool cope with a delivery wrapped in an extra folder?</summary>
Pass 3 notices that `JobX/Reel01/a.mov` on disk is `Reel01/a.mov` from the manifest with `JobX/` in front. The files are paired, their checksums are still verified, and each gets a WARNING naming the folder. Module 4 will group these into one "wrapper folder" cause.
</details>

<details><summary>4. Why compare size before checksum?</summary>
If a CSV manifest records sizes, a different size already proves the file is different. The checksum is still calculated so the report shows both values.
</details>

<details><summary>5. A file couldn't be read. Why isn't it also reported as a checksum mismatch?</summary>
There's no checksum to compare. Calling it a mismatch would be a second, wrong explanation. It already has the right one: UNREADABLE, with the reason.
</details>

<details><summary>6. What does the zero-byte check add beyond "this file is empty"?</summary>
If the manifest's checksum is the well-known checksum of an empty file, the file was probably already empty when the manifest was made. That points the investigation upstream, to the source or the media written, rather than at the copy.
</details>

<details><summary>7. Does the tool rename badly named files?</summary>
No. It reports the problem and *proposes* a clean name. Renaming is a deliberate step for a person (or a separate tool) to do, with a record. A verifier must see names exactly as they are.
</details>

<details><summary>8. Why is a bad folder name reported once, not for every file inside?</summary>
A folder holding 3,000 files would otherwise produce 3,000 identical findings and bury everything else. One finding at the folder says the same thing clearly.
</details>

<details><summary>9. What does "cross-set conflict" mean, and what can't the tool tell you?</summary>
The same path has different checksums in different manifests, for example two tapes or two deliveries. The tool shows each set's checksum. It can't know which version is correct, or when they diverged, and the wording says so.
</details>

<details><summary>10. Name a known limit of the matching.</summary>
A file that is *both* in a wrapper folder *and* differs in Unicode or case isn't paired, because pass 3 doesn't combine with pass 2. Also, two different bad names can produce the same proposed clean name, and this isn't detected yet.
</details>

### Exercises: change this behaviour

1. **Make extra files errors.**
   - Make an extra file an ERROR for a workflow where nothing unexpected may be delivered.
   - Find the one line to change, run the tests, and note which test needs updating and why.
2. **Spot a new reserved name.**
   - Add `CLOCK$` to the Windows reserved names. (Older Windows versions reserved it.)
   - Write the test first in `test_checks.py` by adding a line to the `bad_name, proposed` list.
3. **Count the cross-set results.**
   - In `test_verify.py`, write a test with three manifests where one path appears in all three: two agree and one differs.
   - Predict the finding first, then run it.

---

## Module 4: diagnosis (`diagnose.py`)

### What it does, step by step

Modules 1–3 produce a list of findings, one per problem per file. With a wrapped delivery of 500 files, that's 500 near-identical warnings, which is exactly the "it listed everything as failed" problem. Module 4 reads the findings and asks: **is there one explanation that covers a whole group?**

1. **Wrapper folder.** All files paired by pass 3 are grouped by *which* folder was ignored, and in which direction. Each group becomes one cause, such as "500 files only match once the folder `JobX/` on disk is ignored. This usually means the delivery was wrapped in an extra top-level folder", followed by the list of files.
2. **Unicode form.** All Mac-vs-Windows accented-letter matches become one cause.
3. **Upper/lower case.** All case-only matches become one cause, explaining why this matters on case-sensitive storage.
4. **Duplicate listing.** All paths listed twice with different checksums become one ERROR cause: "Check which version was intended."
5. **Hidden-file noise.** All system files that were set aside become one INFO cause.

Then the causes are **sorted**: errors first, then warnings, then info. Within each level, the cause affecting the most files comes first.

Every cause says **"Probable cause, not a verdict."** The tool can see a pattern; only a person can confirm why it happened. **The individual findings are all kept.** Causes are a summary on top, not a replacement, so nothing is hidden.

### What it doesn't do (deliberately)

There's no cause for checksum mismatches or missing files. They have many possible explanations (interrupted copy, re-export, wrong version, faulty media), and no pattern in the data reliably tells them apart. Guessing would be worse than saying nothing.

### How it's tested

`tests/test_diagnose.py`:
- builds small sets of pairs and findings by hand and checks that each pattern produces exactly one cause, with the right files, severity and wording;
- checks the ordering;
- checks that every cause is labelled as a hint;
- checks that a clean result gives no causes;
- checks the grammar for one file versus several. A real slip ("1 file name differ") was caught in the demo output and fixed test-first.

### Interview questions

<details><summary>1. What problem does the diagnosis solve?</summary>
Tools that say *that* something failed but not *why*. A wrapped delivery used to show up as hundreds of failures that someone had to untangle by hand. Now it's one line naming the folder, with the list of affected files.
</details>

<details><summary>2. Why keep the individual findings if you have causes?</summary>
So nothing is hidden. The cause is a summary; the findings are the evidence. Someone can always check the cause against the detail.
</details>

<details><summary>3. Why "probable cause, not a verdict"?</summary>
The tool sees a pattern in names and checksums. It can't know the history: who made the folder, or why. A person confirms. Overstating would push people to act on a guess.
</details>

<details><summary>4. Why is there no cause for checksum mismatches?</summary>
Many different things produce a mismatch, and the data doesn't reliably distinguish them. A made-up cause would be guessing dressed up as analysis.
</details>

<details><summary>5. How are causes ordered, and why?</summary>
Errors first, then warnings, then info; within each, the biggest group first. The person reading at the end of a long day sees the most important thing first.
</details>

<details><summary>6. What if files are wrapped in two different folders?</summary>
Each folder (and direction) becomes its own cause, so two different packaging mistakes are never merged into one.
</details>

<details><summary>7. Can one file appear in two causes?</summary>
Yes. A name that differs in both Unicode form and case appears under both, because both explanations apply.
</details>

<details><summary>8. How is this different from just counting findings by type?</summary>
A count says "500 PREFIX_OFFSET_MATCH". A cause says *what they have in common* (the same folder `JobX/` on disk), *what that usually means*, and *which files*. That's the difference between a symptom and a diagnosis.
</details>

<details><summary>9. How do you know the cause wording is accurate?</summary>
The claims are general platform behaviour with sources (for example, macOS drives being usually case-insensitive), and they're worded as "usually" or "typically". I also reviewed the wording on realistic demo output as an operator would.
</details>

<details><summary>10. What would you add next?</summary>
A cause for "all missing files are in one folder" (a folder that wasn't copied). I'd want to see it in real-looking data first, though, to make sure it wouldn't mislead.
</details>

### Exercises: change this behaviour

1. **Make hidden-file noise a WARNING.**
   - Do this for a workflow where clutter must be cleaned before delivery.
   - Which test needs updating?
2. **Change the wording of the wrapper cause** to mention the recipient: "…the recipient's automation may not find these files".
   - Update the test first.
3. **Design (no code): a "whole folder missing" cause.**
   - Write in `DECISIONS.md` how you'd detect that every missing file sits under the same folder.
   - Say what wording you'd use, and what could make it misleading.

---

## Module 5: reports and the command (`cli.py`, `config.py`, `report.py`)

### What it does, step by step

This module turns the engine (modules 1–4) into a tool you can type, or that n8n can call.

1. **You type a command**, for example:
   ```
   python -m manifest_doctor check D:/Incoming/ShowA --manifest ShowA.md5 --out D:/Reports
   ```
2. **Settings are worked out in three layers** (`config.py`):
   1. built-in defaults;
   2. a **workflow profile** from `manifest-doctor.toml`, if you name one with `--profile`;
   3. anything typed on the command line.

   Each layer overrides the one before. The report records where every setting came from. A mistake in the settings file stops the tool with a clear message instead of being quietly ignored.
3. **Safety checks before anything is read:**
   - The report folder must not be inside the delivery, because the report would become an "extra" file.
   - In **suggest** mode, if the manifest uses absolute paths (`D:\Deliveries\…`), the tool **stops with exit code 2**. It tries every possible prefix and tells you the one that makes the most paths match real files, e.g. `--strip-prefix "D:/Deliveries/"` (2 of 2 manifest paths then match). That fixes the "one folder too many" problem you found in the module 1 quiz.
4. **The check runs** (modules 1–4).
5. **Profile severity changes are applied** (e.g. a "tape-restore" profile can make EXTRA an ERROR).
6. **The exit code is decided:**
   - **0**: no ERRORs. With a profile setting `fail_on = "warning"`, no warnings either.
   - **1**: problems found.
   - **2**: the tool couldn't check (bad manifest, folder missing, bad settings, absolute paths in suggest mode).
7. **Reports are written to a new dated folder** (`report.py`). Old reports are never touched.
   - `report.json`: for automation. Its format is documented in `docs/report-schema.md`.
   - `report.csv`: for Excel. It's saved so accented names display correctly.
   - `summary.md`: the result line first, then the probable causes, then the findings. Long lists are shortened, with a pointer to the CSV.
   - `findings.sqlite`: only with `--sqlite`.
8. **A short summary is printed:** the result, the causes, and where the reports are.

### SQL you can try on `findings.sqlite`

```sql
-- How many findings of each kind?
SELECT code, COUNT(*) FROM findings GROUP BY code ORDER BY COUNT(*) DESC;

-- Only the errors, with their paths
SELECT path, code, detail FROM findings WHERE severity = 'ERROR';

-- Which files does each probable cause cover?
SELECT c.code, p.path FROM causes c JOIN cause_paths p ON p.cause_id = c.cause_id;
```

### How it's tested

- `tests/test_config.py`: defaults, profiles overriding defaults, the command line overriding profiles, and every kind of settings mistake.
- `tests/test_report.py`: dated folders (including two runs in the same second), JSON contents, CSV columns and the Excel marker, summary ordering and shortening, and SQLite queries.
- `tests/test_cli.py`:
  - exit codes 0, 1 and 2 in each situation;
  - the report folder refused inside the delivery;
  - the absolute-path stop choosing `D:/Deliveries/` rather than `D:/Deliveries/ShowA/`;
  - following its advice gives a clean run;
  - a real run as `python -m manifest_doctor`.

### Interview questions

<details><summary>1. What do the three exit codes mean, and why does it matter?</summary>
0 = checked, no errors. 1 = checked, problems found. 2 = couldn't check. Automation like n8n branches on this number, so "couldn't check" must never look like "clean".
</details>

<details><summary>2. Why a new folder for every run?</summary>
So earlier reports are never overwritten, and there's always a history to go back to. It's the same principle as keeping a record of the original and the re-delivery.
</details>

<details><summary>3. Why stop on absolute paths instead of guessing?</summary>
A wrong guess would turn every file into "missing" and "extra", which is a confident-looking but wrong report. The tool tests the possible prefixes against the real folder and tells you exactly what to type, with how many files would then match.
</details>

<details><summary>4. What's a workflow profile, and why have them?</summary>
A named set of settings in a small text file. A cloud delivery and a tape restore need different rules (for example, extras may be fatal for one and fine for the other). A profile saves retyping and makes the rules visible and reviewable.
</details>

<details><summary>5. What happens if someone makes a typo in the settings file?</summary>
The tool stops with exit code 2 and a message naming the setting. A silently ignored typo would mean running with rules you didn't intend.
</details>

<details><summary>6. Why is the CSV saved "with a byte-order mark"?</summary>
It's an invisible marker at the start of the file that tells Excel the text is UTF-8. Without it, Excel can show `Café` as garbled characters.
</details>

<details><summary>7. Why does the report record where each setting came from?</summary>
So a result can be traced. If a run passed that shouldn't have, you can see whether a profile or a typed option changed the rules.
</details>

<details><summary>8. What's in report.json, and who uses it?</summary>
A header (result, exit code, counts, settings, manifests), the probable causes, and every finding with its details. It's for automation: Project 2's n8n workflow reads it. The format is documented in `docs/report-schema.md`.
</details>

<details><summary>9. Why refuse a report folder inside the delivery?</summary>
The tool is read-only towards the delivery. A report written there would change the delivery and show up as an extra file next time.
</details>

<details><summary>10. Where does SQL come in?</summary>
With `--sqlite`, the findings go into a small database file. You can then ask questions in SQL, for example "count findings by type" or "which files does each cause cover", which is handy across many runs or very large deliveries.
</details>

### Exercises: change this behaviour

1. **Write a profile.**
   - Create `manifest-doctor.toml` with a `tape-restore` profile where EXTRA is an ERROR and `fail_on = "warning"`.
   - Run a check with and without `--profile tape-restore`, and compare the exit codes.
2. **Show the proposed name in the summary.**
   - Make `summary.md` show the proposed clean name for NAME_HYGIENE findings. (Hint: `_write_summary`.)
   - Write the test first in `test_report.py`.
3. **Ask the database a question.**
   - Run with `--sqlite`. Open `findings.sqlite` with any SQLite viewer (or Python), and write a query that lists every file with a WARNING, sorted by path.

---

## Module 6: sample delivery, acceptance test and release checks (`tools/make_fixtures.py`, `tests/test_acceptance.py`)

### What it does, step by step

1. **`tools/make_fixtures.py` builds a made-up delivery** with **one deliberate example of every problem** the tool knows about:
   - a changed file;
   - an empty file;
   - a file listed twice with two versions, and one listed twice with the same version;
   - a missing file and an extra file;
   - a `.DS_Store`;
   - a Mac-style name and a case-only difference;
   - a name starting with a space;
   - a file inside an extra folder;
   - a damaged manifest line;
   - a second manifest that disagrees with the first.

   Each line in the file has a comment saying which problem it plants. Run it with `python -m tools.make_fixtures`. If `fixtures_out/` already exists, it **stops** rather than deleting it, following the project rule.
2. **`tests/test_acceptance.py` runs the tool on that delivery** and checks that:
   - it finds **exactly** the planted problems, with nothing missing and nothing extra;
   - the five probable causes come out in the right order;
   - **every finding code the tool has** appears in the sample. If someone adds a new kind of finding later, this test fails until a sample is added. The only exception is the absolute-path stop, which is tested on the command line instead, because the tool stops before writing a report;
   - a clean copy of the sample gives no findings at all.
3. **Proving the test has teeth.** I deliberately removed one planted problem (the missing file) and confirmed the test noticed. A test that can't fail proves nothing.
4. **Release checks:**
   - **Clean-copy test:** the project was copied from Git into an empty folder and all tests run there. That proves nothing the tests need is left out of the repository.
   - **Safety search** across every published file *and* the commit history: tape-software names, local paths, hostnames, passwords and keys.

### Interview questions

<details><summary>1. What's the difference between the unit tests and the acceptance test?</summary>
Unit tests check one small piece at a time (for example "a pipe manifest is detected"). The acceptance test checks the whole tool on a realistic delivery, end to end: every planted problem found, nothing invented.
</details>

<details><summary>2. Why plant exactly one example of each problem?</summary>
So the expected result is known in advance and easy to read. If the tool finds anything else, it's a false alarm. If it misses one, it's a gap. Both fail the test.
</details>

<details><summary>3. How do you know the acceptance test isn't just passing by accident?</summary>
I broke the sample on purpose (removed the planted missing file) and confirmed the result changed and the test would fail.
</details>

<details><summary>4. What stops someone adding a new check and forgetting to test it?</summary>
A test compares the codes found in the sample with every code the tool defines. A new code without a sample makes it fail.
</details>

<details><summary>5. Why doesn't the generator delete an old sample folder?</summary>
The project rule is to never delete files by default, even the tool's own output. It stops and tells you to remove the folder yourself.
</details>

<details><summary>6. What is the clean-copy test for?</summary>
To catch "works on my machine". It downloads the repository into an empty folder and runs the tests there, so a file that was never committed would show up as a failure.
</details>

<details><summary>7. What did you search for before publishing, and why include the commit history?</summary>
Client and product names, local paths, hostnames, passwords and keys. Git keeps every old version and every commit message, so something removed from a file can still be published through the history.
</details>

<details><summary>8. What are the known limits, and why list them in the README?</summary>
For example: it's tested on Windows only so far, and a file in a wrapper folder that *also* has a Unicode difference isn't paired. Listing limits honestly is part of a tool being trustworthy, because users know where not to rely on it.
</details>

<details><summary>9. Why do the "locked file" findings differ between the test and a real run of the sample?</summary>
In the test the lock is simulated, because real locks behave differently on each operating system. On a real run the file reads normally, so the sample shows 8 errors instead of 9.
</details>

<details><summary>10. If you had another week, what would you add?</summary>
Testing on macOS and Linux; a "whole folder missing" cause; detecting proposed clean names that collide; and timing different read sizes on a large file to back the 1 MiB default with real numbers.
</details>

### Exercises: change this behaviour

1. **Plant a new problem.**
   - Add a file named `clip_0010.mov.` (with a trailing full stop) to the manifest *only*.
   - Predict which findings appear, then run the acceptance test and update `EXPECTED_FINDINGS`.
2. **Break the sample on purpose.**
   - Change the `.DS_Store` line in `_FILES` to `ShowA/Reel01/Thumbs.db`.
   - Does the acceptance test still pass? Why?
3. **Run the whole release check yourself:**
   1. `python -m tools.make_fixtures`
   2. the check command from the README
   3. `python -m pytest`

   Compare your output with the README's example run.

## Feature: `make`, a list from the source (2026-10-20)

**In plain words:** before a copy starts, `make` reads every file in the source and writes down each file's checksum, its fingerprint, in a list. After the copy, `check` compares the copy against that list. If anything went wrong in the copy, the fingerprints won't match.

**Why from the source, not the copy:** a list made from the copy is like checking a dub against itself. It always passes, so it proves nothing about the copy. A list made from the source is like checking the dub against the master.

**Why "all or nothing":** if one source file can't be read, a list without it would make the later check quietly skip that file. So no list is written at all, and the message names the file and the reason.

**Where it is:** `manifest_doctor/make.py` (about 60 lines), plus the `make` command in `cli.py`.
