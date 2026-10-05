"""Run every step in order: read manifests, scan, match, hash, check.

This is the one place that knows the order of the steps. Each step lives in its own module.
"""

from dataclasses import dataclass

from .checks import (check_cross_sets, check_extra, check_missing, check_names,
                     check_pairs, check_zero_byte)
from .diagnose import diagnose
from .hashing import hash_files
from .manifest import read_manifest
from .match import match_files
from .scan import scan_tree


@dataclass
class VerificationResult:
    manifests: list
    scan: object
    match: object
    hashes: dict
    cross_set: dict
    findings: list
    causes: list


def verify(tree, manifest_paths, algorithm="md5", prefix_mode="suggest", strip_prefix=None,
           name_rules="windows", hash_extras=False):
    manifests = [read_manifest(p, algorithm, prefix_mode, strip_prefix) for p in manifest_paths]
    scan = scan_tree(tree)
    entries = [e for m in manifests for e in m.entries]
    match = match_files(entries, scan.files)

    # Only paired files need hashing; extras only if asked (saves time on big deliveries).
    to_hash = [p.file.path for p in match.pairs]
    if hash_extras:
        to_hash += [f.path for f in match.extra]
    hashes, hash_findings = hash_files(tree, to_hash, algorithm)

    cross_set, cross_findings = check_cross_sets(manifests)
    findings = [
        *(f for m in manifests for f in m.findings),
        *scan.findings,
        *match.findings,
        *hash_findings,
        *check_missing(match.missing),
        *check_extra(match.extra, hashes),
        *check_pairs(match.pairs, hashes),
        *check_zero_byte(scan.files, match.pairs, algorithm),
        *check_names(scan.files, name_rules,
                     unicode_matched_paths={p.file.path for p in match.pairs if "unicode" in p.kinds}),
        *cross_findings,
    ]
    causes = diagnose(match, scan, findings)
    return VerificationResult(manifests, scan, match, hashes, cross_set, findings, causes)
