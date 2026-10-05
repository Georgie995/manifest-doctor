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

## 2026-10-05: Read-only tool

- **Decision:** never modify the tree being checked. The report folder can't be inside it.
- **Why:** this is a project rule (never rename, move or delete user files by default). A report written inside the tree would also show up as an extra file.
