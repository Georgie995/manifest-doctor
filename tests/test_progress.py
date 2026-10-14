"""The opt-in progress file (for the Delivery Desk app): off by default, never able to stop a check."""

import hashlib
import json

from manifest_doctor import progress as progress_module
from manifest_doctor.cli import main
from manifest_doctor.hashing import hash_files
from manifest_doctor.progress import ProgressFile


def md5(data):
    return hashlib.md5(data).hexdigest()


def delivery(tmp_path, files):
    tree = tmp_path / "delivery"
    for relative, content in files.items():
        path = tree / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest = tmp_path / "m.md5"
    manifest.write_text("".join(f"{md5(c)}  {r}\n" for r, c in files.items()), encoding="utf-8")
    return tree, manifest


FILES = {"ShowA/clip_0001.mov": b"a" * 10, "ShowA/clip_0002.mov": b"b" * 20, "ShowA/clip_0003.mov": b"c" * 30}


def run(tmp_path, tree, manifest, *extra):
    return main(["check", str(tree), "--manifest", str(manifest), "--out", str(tmp_path / "reports"), *extra])


class Recorder:
    def __init__(self):
        self.calls = []

    def file_started(self, relative):
        self.calls.append(("start", relative))

    def bytes_read(self, n):
        self.calls.append(("bytes", n))

    def file_done(self):
        self.calls.append(("done",))


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_without_the_option_nothing_extra_is_written(tmp_path):
    tree, manifest = delivery(tmp_path, FILES)
    assert run(tmp_path, tree, manifest) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["delivery", "m.md5", "reports"]


def test_the_progress_file_ends_finished_with_every_file_and_byte_counted(tmp_path):
    tree, manifest = delivery(tmp_path, FILES)
    progress_path = tmp_path / "progress.json"
    assert run(tmp_path, tree, manifest, "--progress-file", str(progress_path)) == 0
    state = json.loads(progress_path.read_text(encoding="utf-8"))
    assert state["stage"] == "finished"
    assert (state["files_done"], state["files_total"]) == (3, 3)
    assert (state["bytes_done"], state["bytes_total"]) == (60, 60)
    assert not list(tmp_path.glob("*.tmp")) and not list(tmp_path.glob(".*.tmp"))


def test_hashing_reports_each_file_in_order_and_every_byte_read(tmp_path):
    tree, _ = delivery(tmp_path, FILES)
    recorder = Recorder()
    hash_files(tree, list(FILES), "md5", progress=recorder)
    starts = [c[1] for c in recorder.calls if c[0] == "start"]
    assert starts == sorted(FILES)
    assert sum(c[1] for c in recorder.calls if c[0] == "bytes") == 60
    assert sum(1 for c in recorder.calls if c[0] == "done") == 3


def test_an_unreadable_file_still_counts_as_done(tmp_path, monkeypatch):
    tree, _ = delivery(tmp_path, FILES)
    from manifest_doctor import hashing

    original = hashing.hash_file

    def failing(path, algorithm, *args, **kwargs):
        if path.name == "clip_0002.mov":
            raise PermissionError(13, "Permission denied")
        return original(path, algorithm, *args, **kwargs)

    monkeypatch.setattr(hashing, "hash_file", failing)
    recorder = Recorder()
    _, findings = hash_files(tree, list(FILES), "md5", progress=recorder)
    assert [f.code for f in findings] == ["UNREADABLE"]
    assert sum(1 for c in recorder.calls if c[0] == "done") == 3


def test_stages_are_preparing_then_hashing_then_finished(tmp_path):
    path = tmp_path / "p.json"
    progress = ProgressFile(path, clock=FakeClock())
    assert json.loads(path.read_text(encoding="utf-8"))["stage"] == "preparing"
    progress.start_hashing(files_total=2, bytes_total=50)
    state = json.loads(path.read_text(encoding="utf-8"))
    assert (state["stage"], state["files_total"], state["bytes_total"]) == ("hashing", 2, 50)
    progress.finish()
    assert json.loads(path.read_text(encoding="utf-8"))["stage"] == "finished"


def test_writes_are_limited_to_a_few_per_second_but_stage_changes_always_land(tmp_path):
    clock = FakeClock()
    path = tmp_path / "p.json"
    progress = ProgressFile(path, clock=clock, min_interval=0.25)
    progress.start_hashing(files_total=1, bytes_total=1000)
    progress.file_started("a.mov")
    for _ in range(100):
        progress.bytes_read(10)               # no time passes: too soon to write again
    assert json.loads(path.read_text(encoding="utf-8"))["bytes_done"] < 1000
    clock.now = 1.0
    progress.bytes_read(0)                    # enough time has passed: written
    state = json.loads(path.read_text(encoding="utf-8"))
    assert (state["bytes_done"], state["current_file"]) == (1000, "a.mov")


def test_a_moment_where_the_file_cannot_be_replaced_is_skipped_not_fatal(tmp_path, monkeypatch, capsys):
    clock = FakeClock()
    path = tmp_path / "p.json"
    progress = ProgressFile(path, clock=clock)
    real_replace = progress_module.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(13, "in use by another program")   # e.g. the app reading it right then
        return real_replace(src, dst)

    monkeypatch.setattr(progress_module.os, "replace", flaky)
    progress.start_hashing(files_total=1, bytes_total=5)     # skipped
    clock.now = 1.0
    progress.file_started("a.mov")                            # skipped again
    clock.now = 2.0
    progress.finish()                                        # this one lands
    assert json.loads(path.read_text(encoding="utf-8"))["stage"] == "finished"
    assert capsys.readouterr().err.count("progress file") == 1   # one warning, not one per write
    assert not list(tmp_path.glob(".*.tmp"))


def test_each_update_is_written_to_a_temporary_copy_then_swapped_in_whole(tmp_path, monkeypatch):
    swaps = []
    real_replace = progress_module.os.replace

    def recording(src, dst):
        swaps.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(progress_module.os, "replace", recording)
    path = tmp_path / "p.json"
    ProgressFile(path, clock=FakeClock()).finish()
    assert swaps and all(dst == str(path) and src != dst and src.endswith(".tmp") for src, dst in swaps)


def test_a_progress_file_that_cannot_be_written_never_stops_the_check(tmp_path, capsys):
    tree, manifest = delivery(tmp_path, FILES)
    assert run(tmp_path, tree, manifest, "--progress-file", str(tmp_path / "no" / "such" / "p.json")) == 0
    assert list((tmp_path / "reports").iterdir())                # the report was still written
    assert "progress file" in capsys.readouterr().err


def test_a_progress_file_inside_the_delivery_is_refused(tmp_path, capsys):
    tree, manifest = delivery(tmp_path, FILES)
    assert run(tmp_path, tree, manifest, "--progress-file", str(tree / "progress.json")) == 2
    assert "inside the folder being checked" in capsys.readouterr().err
    assert not (tree / "progress.json").exists()


# --- A held-back update still lands (for ClearSum's stuck warning, which names the file) --------------

def test_an_update_held_back_to_keep_writes_few_still_lands_a_moment_later(tmp_path):
    # If reading gets stuck the instant a new file starts, no further update will ever come, so the
    # held-back "now reading" must still be written: the app's warning has to name the right file.
    import time
    path = tmp_path / "p.json"
    progress = ProgressFile(path, min_interval=0.2)
    progress.start_hashing(files_total=2, bytes_total=20)    # written
    progress.file_started("ShowA/clip_0002.mov")             # too soon after that: held back...
    assert json.loads(path.read_text(encoding="utf-8"))["current_file"] is None
    time.sleep(0.6)                                          # ...and then nothing else happens
    assert json.loads(path.read_text(encoding="utf-8"))["current_file"] == "ShowA/clip_0002.mov"


def test_nothing_is_written_after_finished(tmp_path):
    # A late catch-up must never bring back a progress file the app has already tidied away.
    import time
    path = tmp_path / "p.json"
    progress = ProgressFile(path, min_interval=0.2)
    progress.start_hashing(files_total=1, bytes_total=10)
    progress.file_started("a.mov")                           # held back: a catch-up is due
    progress.finish()
    path.unlink()                                            # the app tidies it away
    time.sleep(0.6)
    assert not path.exists()
