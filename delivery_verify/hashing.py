"""Module 2, part 2: calculate checksums, one small piece at a time."""

import hashlib
from pathlib import Path

from .findings import make_finding

# 1 MiB pieces keep memory use flat whether a file is 1 KB or 500 GB.
CHUNK_SIZE = 1024 * 1024


def hash_file(path, algorithm, chunk_size=CHUNK_SIZE):
    """Return the checksum of one file as lower-case hex. Read errors are raised."""
    digest = hashlib.new(algorithm)
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def hash_files(root, relative_paths, algorithm):
    """Hash each file under root. Returns ({path: hash}, findings).

    A file that can't be read gets an UNREADABLE finding with the reason, and the
    rest are still hashed. Georgi's failures F8 and F9: one bad file used to stop a whole job.
    """
    root = Path(root)
    hashes, findings = {}, []
    # Sorted order: predictable, and kinder to tape-backed or network storage (DESIGN.md 9.2).
    for relative in sorted(relative_paths):
        try:
            hashes[relative] = hash_file(root / relative, algorithm)
        except OSError as error:
            findings.append(make_finding(
                "UNREADABLE", path=relative, detail=f"could not be read: {error.strerror}"))
    return hashes, findings
