"""Module 5: the command line. Turns typed options into settings, runs the check,
writes the reports and returns the exit code that automation reads:

    0 = no ERROR findings, 1 = at least one ERROR finding, 2 = the tool couldn't check.

`compare` (two versions of a checksum list): 0 = identical, 1 = they differ, 2 = couldn't compare.
`make` (a list from the source, before a copy): 0 = list written, 2 = no list written.
"""

import argparse
import sys
from pathlib import Path

from .compare import compare_lists, result_text, write_comparison
from .config import ConfigError, resolve_settings
from .findings import ERROR, WARNING
from .make import make_list
from .manifest import ManifestError, best_prefix, read_manifest
from .progress import ProgressFile
from .report import count_by_severity, counts_text, result_label, write_reports
from .scan import ScanError, scan_tree
from .verify import verify


def main(argv=None):
    # Never crash on an unusual character when printing to a terminal that can't show it.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    args = _parser().parse_args(argv)
    try:
        commands = {"compare": _compare, "make": _make, "check": _check}
        return commands[args.command](args)
    except (ConfigError, ManifestError, ScanError) as error:
        print(f"manifest-doctor: error: {error}", file=sys.stderr)
        return 2


def _parser():
    parser = argparse.ArgumentParser(prog="manifest-doctor",
                                     description="Read-only manifest verification with probable-cause diagnosis.")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="verify a folder against one or more manifests")
    check.add_argument("tree", help="the folder to check (never modified)")
    check.add_argument("--manifest", action="append", required=True, help="manifest file (repeat for several)")
    check.add_argument("--algorithm", choices=["md5", "sha256"])
    check.add_argument("--prefix-mode", dest="prefix_mode", choices=["suggest", "auto", "off"])
    check.add_argument("--strip-prefix", dest="strip_prefix")
    check.add_argument("--name-rules", dest="name_rules", choices=["windows", "strict"])
    check.add_argument("--hash-extras", dest="hash_extras", action="store_true", default=None)
    check.add_argument("--profile", help="named workflow profile from the settings file")
    check.add_argument("--config", default="manifest-doctor.toml", help="settings file (default: %(default)s)")
    check.add_argument("--out", default="manifest-doctor-report", help="where report folders go")
    check.add_argument("--sqlite", action="store_true", help="also write findings.sqlite")
    check.add_argument("--progress-file", dest="progress_file",
                       help="keep a small JSON file up to date with how far the check has got (for apps)")
    compare = commands.add_parser("compare", help="compare two versions of a checksum list, earlier and later "
                                                  "(reads only the two lists)")
    compare.add_argument("earlier", help="the earlier list")
    compare.add_argument("later", help="the later list")
    compare.add_argument("--algorithm", choices=["md5", "sha256"], default="md5")
    compare.add_argument("--out", default="manifest-doctor-report", help="where comparison folders go")
    make = commands.add_parser("make", help="make a checksum list from the source, before a copy "
                                            "(reads the source only)")
    make.add_argument("source", help="the folder to list (never modified)")
    make.add_argument("--out", required=True, help="the list file to write (never overwritten; not in the source)")
    make.add_argument("--algorithm", choices=["md5", "sha256"], default="md5")
    return parser


def _make(args):
    made = make_list(args.source, args.out, args.algorithm)
    clutter = f"; {made.left_out} system files left out" if made.left_out else ""
    print(f"LIST WRITTEN: {made.files} files ({args.algorithm}){clutter}")
    print(f"  {made.path}")
    print("  This list was made from the source. It proves what the source held when it was read, "
          "not that any copy matches: check the copy against it.")
    return 0


def _compare(args):
    comparison = compare_lists(args.earlier, args.later, args.algorithm)
    folder = write_comparison(comparison, Path(args.out))
    counts = (f"{len(comparison.changed)} changed, {len(comparison.renamed)} renamed or moved, "
              f"{len(comparison.only_earlier)} only in the earlier list, {len(comparison.only_later)} only in the "
              f"later list, {len(comparison.cannot_tell)} {'group' if len(comparison.cannot_tell) == 1 else 'groups'} "
              f"that can't be told apart; "
              f"{len(comparison.unchanged)} unchanged")
    print(f"RESULT: {result_text(comparison)} ({counts})")
    for note in comparison.notes + ([comparison.hint] if comparison.hint else []):
        print(f"  {note}")
    print(f"Results: {folder}")
    return 0 if comparison.identical else 1


def _check(args):
    cli_values = {k: getattr(args, k) for k in ("algorithm", "prefix_mode", "name_rules", "hash_extras")
                  if getattr(args, k) is not None}
    settings, sources = resolve_settings(cli_values, args.config, args.profile)

    tree, out = Path(args.tree), Path(args.out)
    if out.resolve().is_relative_to(tree.resolve()):
        # A report written inside the delivery would itself become an "extra" file.
        raise ScanError(f"report folder {out} is inside the folder being checked; choose another --out")
    if args.progress_file and Path(args.progress_file).resolve().is_relative_to(tree.resolve()):
        # Same reason: it would turn up as an "extra" file in the delivery.
        raise ScanError(f"progress file {args.progress_file} is inside the folder being checked; "
                        "choose another --progress-file")

    if args.strip_prefix is None and settings["prefix_mode"] == "suggest":
        stop_message = _absolute_path_stop(args.manifest, tree, settings["algorithm"])
        if stop_message:
            print(f"manifest-doctor: stopped: {stop_message}", file=sys.stderr)
            return 2

    progress = ProgressFile(args.progress_file) if args.progress_file else None
    result = verify(tree, args.manifest, algorithm=settings["algorithm"],
                    prefix_mode=settings["prefix_mode"], strip_prefix=args.strip_prefix,
                    name_rules=settings["name_rules"], hash_extras=settings["hash_extras"], progress=progress)

    for finding in result.findings:
        finding.severity = settings["severity"].get(finding.code, finding.severity)
    failing = {ERROR} if settings["fail_on"] == "error" else {ERROR, WARNING}
    exit_code = 1 if any(f.severity in failing for f in result.findings) else 0

    folder = write_reports(result, out, settings, sources, exit_code, sqlite=args.sqlite)
    if progress:
        progress.finish()  # "finished" only once the reports are on disk
    _print_summary(result, exit_code, folder)
    return exit_code


def _absolute_path_stop(manifest_paths, tree, algorithm):
    """In suggest mode: if manifest paths are absolute, stop and say exactly what to type."""
    manifests = [read_manifest(p, algorithm, prefix_mode="suggest") for p in manifest_paths]
    flagged = [m for m in manifests if any(f.code == "ABSOLUTE_PATHS_DETECTED" for f in m.findings)]
    if not flagged:
        return None
    disk = [f.path for f in scan_tree(tree).files]
    messages = []
    for m in flagged:
        if m.suggested_prefix is None:
            messages.append(f"{m.manifest} mixes absolute and relative paths; "
                            "choose what to remove with --strip-prefix, or use --prefix-mode off")
            continue
        paths = [e.path for e in m.entries]
        prefix, matched = best_prefix(paths, disk)
        fit = (f"{matched} of {len(paths)} manifest paths then match files in the folder" if matched
               else "no prefix makes these paths match files in the folder; check you chose the right folder")
        messages.append(f'{m.manifest} uses absolute paths. Re-run with --strip-prefix "{prefix}" ({fit}), '
                        "or use --prefix-mode auto")
    return "\n".join(messages)


def _print_summary(result, exit_code, folder):
    counts = count_by_severity(result.findings)
    print(f"RESULT: {result_label(exit_code, counts)} ({counts_text(counts)})")
    for cause in result.causes:
        print(f"  {cause.severity}: {cause.summary}")
    print(f"Reports: {folder}")
