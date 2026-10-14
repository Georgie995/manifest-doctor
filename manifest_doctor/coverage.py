"""What a check proves, and what it doesn't, in plain sentences.

Worked out only from what the check actually did, so it can never claim more than that. Saved in
report.json and summary.md, and shown by the ClearSum app. Wording approved by Georgi (2026-10-14).
"""

from .scan import FOLDER_UNREADABLE

CANNOT_TELL = ("This shows the files match the manifest today. It can't tell you whether the manifest itself was "
               "right, or catch changes made after this check.")
CHECKSUM_NAMES = {"md5": "MD5", "sha256": "SHA-256"}


def coverage(result, algorithm="md5", hash_extras=False):
    pairs = result.match.pairs
    read = [p for p in pairs if p.file.path in result.hashes]
    mismatched = {f.path for f in result.findings if f.code == "HASH_MISMATCH"}
    unreadable = [f for f in result.findings if f.code == "UNREADABLE"]
    folders = sum(1 for f in unreadable if f.detail.startswith(FOLDER_UNREADABLE))
    missing = len({e.path for e in result.match.missing})       # a path listed twice is one file
    n = {
        "checksum": CHECKSUM_NAMES.get(algorithm, algorithm.upper()),
        "manifests": len(result.manifests),
        "listed": len(pairs) + missing,
        "found": len(pairs),
        "found_under_other_name": sum(1 for p in pairs if p.kinds != ["exact"]),
        "read": len(read),
        "matched": sum(1 for p in read if p.file.path not in mismatched),
        "mismatched": sum(1 for p in read if p.file.path in mismatched),
        "missing": missing,
        "unreadable_files": len(unreadable) - folders,
        "unreadable_folders": folders,
        "unreadable_lines": sum(1 for f in result.findings if f.code == "MANIFEST_LINE_UNREADABLE"),
        "extra": len(result.match.extra),
        "extra_checksummed": bool(hash_extras),
        "set_aside": len(result.scan.hidden),
    }
    return {**n, "proved": _proved(n), "not_checked": _not_checked(n), "cannot_tell": CANNOT_TELL}


def _where(n):
    return "the manifests" if n["manifests"] > 1 else "the manifest"


def _proved(n):
    listed, read, checksum, where = n["listed"], n["read"], n["checksum"], _where(n)
    compared = f"{n['matched']:,} matched and {n['mismatched']:,} didn't"
    if read == 0:
        text = (f"The file listed in {where} couldn't be read and compared." if listed == 1
                else f"None of the {listed:,} files listed in {where} could be read and compared.")
    elif read == listed == 1:
        text = (f"The file listed in {where} was found and read in full, and its {checksum} checksum "
                + ("matched." if n["matched"] else "didn't match."))
    elif read == listed:
        text = (f"All {listed:,} files listed in {where} were found and read in full, and "
                + (f"every {checksum} checksum matched." if not n["mismatched"]
                   else f"their {checksum} checksums compared: {compared}."))
    else:
        text = (f"{read:,} of the {listed:,} files listed in {where} were read in full"
                + (f", and every {checksum} checksum matched." if not n["mismatched"]
                   else f" and their {checksum} checksums compared: {compared}."))
    other = n["found_under_other_name"]
    if other:
        text += (f" {other:,} of them {'was' if other == 1 else 'were'} found under a slightly different name "
                 "(an accent, upper/lower case or an extra folder); see the warnings.")
    return text


def _not_checked(n):
    where, lines = _where(n), []

    def add(count, one, many):
        if count:
            lines.append((one if count == 1 else many).replace("{n}", f"{count:,}"))

    add(n["missing"], "{n} listed file wasn't found, so it couldn't be compared.",
        "{n} listed files weren't found, so they couldn't be compared.")
    add(n["unreadable_files"], "{n} file couldn't be read, so it wasn't compared.",
        "{n} files couldn't be read, so they weren't compared.")
    add(n["unreadable_folders"], "{n} folder couldn't be opened, so nothing inside it was checked.",
        "{n} folders couldn't be opened, so nothing inside them was checked.")
    add(n["unreadable_lines"], f"{{n}} line in {where} couldn't be read, so whatever it lists wasn't checked.",
        f"{{n}} lines in {where} couldn't be read, so whatever they list wasn't checked.")
    if n["extra_checksummed"]:
        add(n["extra"], f"{{n}} file in the folder isn't in {where}, so there was nothing to compare it with "
                        "(its checksum is in the report).",
            f"{{n}} files in the folder aren't in {where}, so there was nothing to compare them with "
            "(their checksums are in the report).")
    else:
        add(n["extra"], f"{{n}} file in the folder isn't in {where}, and wasn't checksummed.",
            f"{{n}} files in the folder aren't in {where}, and weren't checksummed.")
    add(n["set_aside"], "{n} system file (such as .DS_Store) was set aside and not checked.",
        "{n} system files (such as .DS_Store) were set aside and not checked.")
    return lines
