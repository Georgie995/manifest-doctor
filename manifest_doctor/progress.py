"""An optional progress file, so an app can show how far a check has got (--progress-file).

Off unless asked for. It only ever writes its own small JSON file, and a problem writing it
never stops or changes the check: the report is what matters, the progress file is a courtesy.
"""

import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path


class ProgressFile:
    def __init__(self, path, clock=time.monotonic, min_interval=0.25):
        self.path = Path(path)
        self._clock = clock
        self._min_interval = min_interval    # a few writes a second is plenty for a progress bar
        self._last_write = None
        self._warned = False
        self._lock = threading.Lock()        # a held-back update is written from its own thread
        self._catch_up = None
        self._finished = False
        self.state = {"stage": "preparing", "files_done": 0, "files_total": 0,
                      "bytes_done": 0, "bytes_total": 0, "current_file": None}
        self._write(force=True)

    def start_hashing(self, files_total, bytes_total):
        self.state.update(stage="hashing", files_total=files_total, bytes_total=bytes_total)
        self._write(force=True)

    def file_started(self, relative):
        self.state["current_file"] = relative
        self._write()

    def bytes_read(self, n):
        self.state["bytes_done"] += n
        self._write()

    def file_done(self):
        self.state["files_done"] += 1
        self._write()

    def finish(self):
        self.state["stage"] = "finished"
        with self._lock:
            self._finished = True               # a held-back update still due is refused (see _write)
        for _ in range(3):  # the last word matters most, so try again if a reader had it open
            if self._write(force=True):
                return
            time.sleep(0.05)

    def _write(self, force=False, catching_up=False):
        with self._lock:
            if catching_up:
                self._catch_up = None
                if self._finished:
                    return False
            now = self._clock()
            if not force and self._last_write is not None and now - self._last_write < self._min_interval:
                self._hold_back(now)
                return False
            self.state["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            temp = self.path.with_name(f".{self.path.name}.tmp")
            try:
                temp.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
                os.replace(temp, self.path)  # readers see the old file or the new one, never half of one
            except OSError as error:
                # Skipped, not fatal: e.g. the app was reading the file at that moment. Try again next time.
                temp.unlink(missing_ok=True)
                if not self._warned:
                    print(f"manifest-doctor: warning: can't write progress file {self.path} ({error}); "
                          "the check carries on", file=sys.stderr)
                    self._warned = True
                return False
            self._last_write = now
            return True

    def _hold_back(self, now):
        """A write skipped to keep writes few still lands a moment later, even if nothing else happens.
        If reading gets stuck the instant a new file starts, no further update will come, and the app
        must still learn which file it is stuck on (ClearSum's stuck warning names it)."""
        if self._catch_up is None and not self._finished:
            wait = max(0.0, self._min_interval - (now - self._last_write))
            self._catch_up = threading.Timer(wait, self._write, kwargs={"force": True, "catching_up": True})
            self._catch_up.daemon = True        # never keeps manifest-doctor running after the check
            self._catch_up.start()
