"""Tests for module 5: the command line, exit codes and the stop-and-suggest behaviour."""

import hashlib
import subprocess
import sys
from pathlib import Path

from delivery_verify.cli import main

PROJECT = Path(__file__).resolve().parents[1]


def md5(data):
    return hashlib.md5(data).hexdigest()


def delivery(tmp_path, files, manifest_lines):
    tree = tmp_path / "delivery"
    for relative, content in files.items():
        path = tree / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest = tmp_path / "m.md5"
    manifest.write_text("".join(line + "\n" for line in manifest_lines), encoding="utf-8")
    return tree, manifest


def run(tmp_path, tree, manifest, *extra):
    out = tmp_path / "reports"
    return main(["check", str(tree), "--manifest", str(manifest), "--out", str(out), *extra])


def test_clean_delivery_exits_0_and_writes_a_report(tmp_path, capsys):
    tree, manifest = delivery(tmp_path, {"a.mov": b"aaa"}, [f"{md5(b'aaa')}  a.mov"])
    assert run(tmp_path, tree, manifest) == 0
    [folder] = (tmp_path / "reports").iterdir()
    assert (folder / "report.json").exists()
    assert "CLEAN" in capsys.readouterr().out


def test_errors_exit_1(tmp_path, capsys):
    tree, manifest = delivery(tmp_path, {"a.mov": b"changed"}, [f"{md5(b'aaa')}  a.mov"])
    assert run(tmp_path, tree, manifest) == 1
    assert "PROBLEMS FOUND" in capsys.readouterr().out


def test_counts_are_grammatical(tmp_path, capsys):
    tree, manifest = delivery(tmp_path, {"a.mov": b"changed", "x.mov": b"z"}, [f"{md5(b'aaa')}  a.mov"])
    run(tmp_path, tree, manifest)
    assert "(1 error, 1 warning, 0 info)" in capsys.readouterr().out


def test_warnings_only_exit_0_by_default(tmp_path):
    tree, manifest = delivery(tmp_path, {"a.mov": b"aaa", "extra.mov": b"z"}, [f"{md5(b'aaa')}  a.mov"])
    assert run(tmp_path, tree, manifest) == 0


def test_profile_can_make_warnings_fail_and_change_severities(tmp_path):
    tree, manifest = delivery(tmp_path, {"a.mov": b"aaa", "extra.mov": b"z"}, [f"{md5(b'aaa')}  a.mov"])
    config = tmp_path / "settings.toml"
    config.write_text('[profiles.strict-wh]\nfail_on = "warning"\n'
                      '[profiles.no-extras]\nseverity.EXTRA = "ERROR"\n', encoding="utf-8")
    assert run(tmp_path, tree, manifest, "--config", str(config), "--profile", "strict-wh") == 1
    assert run(tmp_path, tree, manifest, "--config", str(config), "--profile", "no-extras") == 1


def test_unusable_manifest_exits_2_with_a_message(tmp_path, capsys):
    tree, _ = delivery(tmp_path, {"a.mov": b"aaa"}, ["x"])
    assert run(tmp_path, tree, tmp_path / "no_such_manifest.md5") == 2
    assert "cannot be read" in capsys.readouterr().err


def test_missing_folder_exits_2(tmp_path, capsys):
    _, manifest = delivery(tmp_path, {}, [f"{md5(b'aaa')}  a.mov"])
    assert run(tmp_path, tmp_path / "not_plugged_in", manifest) == 2
    assert "does not exist" in capsys.readouterr().err


def test_report_folder_inside_the_delivery_is_refused(tmp_path, capsys):
    tree, manifest = delivery(tmp_path, {"a.mov": b"aaa"}, [f"{md5(b'aaa')}  a.mov"])
    code = main(["check", str(tree), "--manifest", str(manifest), "--out", str(tree / "reports")])
    assert code == 2
    assert "inside the folder being checked" in capsys.readouterr().err
    assert not (tree / "reports").exists()  # nothing was written into the delivery


def test_absolute_paths_stop_with_a_suggestion_that_fits_the_folder(tmp_path, capsys):
    # Every manifest path is under D:/Deliveries/ShowA/, but the folder being checked still
    # contains ShowA/. The longest shared folder would strip one level too many (found in
    # Georgi's module 1 quiz), so the suggestion must be D:/Deliveries/.
    tree, manifest = delivery(tmp_path, {"ShowA/a.mov": b"aaa", "ShowA/b.mov": b"bbb"}, [
        f"{md5(b'aaa')}  D:\\Deliveries\\ShowA\\a.mov",
        f"{md5(b'bbb')}  D:\\Deliveries\\ShowA\\b.mov",
    ])
    assert run(tmp_path, tree, manifest) == 2
    err = capsys.readouterr().err
    assert '--strip-prefix "D:/Deliveries/"' in err
    assert "2 of 2" in err
    assert not (tmp_path / "reports").exists()


def test_following_the_suggestion_gives_a_clean_result(tmp_path):
    tree, manifest = delivery(tmp_path, {"ShowA/a.mov": b"aaa"}, [f"{md5(b'aaa')}  D:\\Deliveries\\ShowA\\a.mov"])
    assert run(tmp_path, tree, manifest, "--strip-prefix", "D:/Deliveries/") == 0


def test_auto_mode_strips_and_continues(tmp_path):
    tree, manifest = delivery(tmp_path, {"a.mov": b"aaa"}, [f"{md5(b'aaa')}  /Volumes/Drive01/a.mov"])
    assert run(tmp_path, tree, manifest, "--prefix-mode", "auto") == 0


def test_sqlite_flag_writes_the_database(tmp_path):
    tree, manifest = delivery(tmp_path, {"a.mov": b"aaa"}, [f"{md5(b'aaa')}  a.mov"])
    run(tmp_path, tree, manifest, "--sqlite")
    [folder] = (tmp_path / "reports").iterdir()
    assert (folder / "findings.sqlite").exists()


def test_tool_runs_as_a_real_command(tmp_path):
    tree, manifest = delivery(tmp_path, {"a.mov": b"aaa"}, [f"{md5(b'aaa')}  a.mov"])
    completed = subprocess.run(
        [sys.executable, "-m", "delivery_verify", "check", str(tree), "--manifest", str(manifest),
         "--out", str(tmp_path / "reports")],
        cwd=PROJECT, capture_output=True, text=True, encoding="utf-8")
    assert completed.returncode == 0, completed.stderr
