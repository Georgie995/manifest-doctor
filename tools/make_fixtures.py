"""Build a synthetic sample delivery with one deliberate example of every problem.

All names and contents are made up. Run it to get a folder to try the tool on:

    python -m tools.make_fixtures            # writes into fixtures_out/ (git-ignored)

Then:

    python -m delivery_verify check fixtures_out/delivery \
        --manifest fixtures_out/manifest_set1.md5 --manifest fixtures_out/manifest_set2.md5 \
        --out fixtures_out/reports

The file "locked.mov" is only unreadable in the automated test, where the lock is
simulated. On a real run it is checked like any other file.
"""

import hashlib
import sys
import unicodedata
from pathlib import Path


def _md5(data):
    return hashlib.md5(data).hexdigest()


# (path on disk, contents). Each comment says which problem the file plants.
_FILES = [
    ("ShowA/Reel01/clip_0001.mov", b"good picture"),               # fine in set 1; conflicts with set 2
    ("ShowA/Reel01/clip_0002.mov", b"picture changed later"),      # HASH_MISMATCH
    ("ShowA/Reel01/clip_0003.mov", b""),                           # ZERO_BYTE (empty at source)
    ("ShowA/Reel01/clip_0004.mov", b"version 2"),                  # DUPLICATE_ENTRY (two versions listed)
    ("ShowA/Reel01/clip_0005.mov", b"listed twice"),               # DUPLICATE_SAME_HASH
    ("ShowA/Reel01/extra_0007.mov", b"not in any manifest"),       # EXTRA
    ("ShowA/Reel01/.DS_Store", b"macOS clutter"),                  # HIDDEN_FILE
    ("ShowA/Reel01/locked.mov", b"locked in the test"),            # UNREADABLE (simulated in tests)
    (unicodedata.normalize("NFD", "ShowA/Audio/Café_stem.wav"), b"stem"),  # UNICODE_ONLY_MATCH (Mac-style name)
    ("ShowA/Audio/Dialogue_Stem.wav", b"dialogue"),                # CASE_ONLY_MATCH
    ("ShowA/Docs/ notes.txt", b"notes"),                           # NAME_HYGIENE (leading space)
    ("Wrapper_Folder/Reel09/clip_0009.mov", b"wrapped"),           # PREFIX_OFFSET_MATCH (extra folder)
]

_SET1 = [
    f"{_md5(b'good picture')}  ShowA/Reel01/clip_0001.mov",
    f"{_md5(b'original picture')}  ShowA/Reel01/clip_0002.mov",
    f"{_md5(b'')}  ShowA/Reel01/clip_0003.mov",
    f"{_md5(b'version 1')}  ShowA/Reel01/clip_0004.mov",
    f"{_md5(b'version 2')}  ShowA/Reel01/clip_0004.mov",
    f"{_md5(b'listed twice')}  ShowA/Reel01/clip_0005.mov",
    f"{_md5(b'listed twice')}  ShowA/Reel01/clip_0005.mov",
    f"{_md5(b'never delivered')}  ShowA/Reel01/clip_0006.mov",    # MISSING
    f"{_md5(b'locked in the test')}  ShowA/Reel01/locked.mov",
    f"{_md5(b'stem')}  " + unicodedata.normalize("NFC", "ShowA/Audio/Café_stem.wav"),
    f"{_md5(b'dialogue')}  ShowA/Audio/dialogue_stem.wav",
    f"{_md5(b'notes')}  ShowA/Docs/ notes.txt",
    f"{_md5(b'wrapped')}  Reel09/clip_0009.mov",
    "### damaged line ###",                                         # MANIFEST_LINE_UNREADABLE
]

_SET2 = [
    f"{_md5(b'a different version')}  ShowA/Reel01/clip_0001.mov",  # CROSS_SET_CONFLICT with set 1
]

_CLEAN_FILES = [("ShowA/Reel01/clip_0001.mov", b"good picture"), ("ShowA/Audio/stem_01.wav", b"stem")]


def build_fixtures(destination, clean=False):
    """Write the sample delivery and its manifests. Returns their paths."""
    destination = Path(destination)
    tree = destination / "delivery"
    files = _CLEAN_FILES if clean else _FILES
    for relative, content in files:
        path = tree / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    if clean:
        sets = {"manifest_clean.md5": [f"{_md5(c)}  {p}" for p, c in _CLEAN_FILES]}
    else:
        sets = {"manifest_set1.md5": _SET1, "manifest_set2.md5": _SET2}
    manifests = []
    for name, lines in sets.items():
        manifest = destination / name
        manifest.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
        manifests.append(manifest)
    return {"tree": tree, "manifests": manifests}


def main():
    destination = Path("fixtures_out")
    if destination.exists():
        # Project rule: never delete files by default, even our own output.
        print(f"{destination} already exists. Delete or rename it yourself, then run this again.",
              file=sys.stderr)
        return 2
    fixtures = build_fixtures(destination)
    print(f"Sample delivery: {fixtures['tree']}")
    for manifest in fixtures["manifests"]:
        print(f"Manifest:        {manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
