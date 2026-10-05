# Walkthrough

One section per module. Each has a plain-English explanation, interview questions with short answers, and "change this behaviour" exercises.

---

## Module 1: reading manifests (`delivery_verify/manifest.py`)

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
