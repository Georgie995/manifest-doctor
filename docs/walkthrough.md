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
