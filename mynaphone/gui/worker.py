# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs the asyncio recorder on a Qt thread and relays its events as signals."""
from __future__ import annotations

import asyncio
import gc
import logging

from PySide6.QtCore import QThread, Signal

from ..config import Config
from ..daemon import Recorder


class _QtLogHandler(logging.Handler):
    def __init__(self, signal):
        super().__init__(level=logging.INFO)
        self.signal = signal
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record):
        try:
            self.signal.emit(self.format(record))
        except Exception:
            pass


class RecorderWorker(QThread):
    """A Qt thread that runs the recorder on an asyncio loop of its own. Its signals pass the recorder's events and
    answers to the window, with the app's log lines from `INFO` up and the error if the recorder crashes.
    `set_paused` and `set_harvest` can come before the recorder exists, and `run` applies them when it makes one."""
    event = Signal(dict)
    log = Signal(str)
    failed = Signal(str)
    answer = Signal(int, object, str)       # a question's token, its answer, and the error when there's none

    def ask(self, make, token: int) -> bool:
        """Run `make(recorder)`, a coroutine, on the recorder's loop; the answer comes back as the answer signal.
        False when the recorder isn't running."""
        rec = self.recorder
        if rec is None:
            return False
        fut = asyncio.run_coroutine_threadsafe(make(rec), rec.loop)

        def done(f):
            try:
                self.answer.emit(token, f.result(), "")
            except Exception as e:
                self.answer.emit(token, None, str(e) or type(e).__name__)
        fut.add_done_callback(done)
        return True

    def __init__(self, config_path: str, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.recorder: Recorder | None = None
        self._paused = False
        self._harvest: bool | None = None

    def run(self) -> None:
        """Load `config_path` and run the recorder on a new event loop until it stops, or emit `failed` if it
        crashes. Qt calls it on the new thread after `start`."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        handler = _QtLogHandler(self.log)
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            cfg = Config.load(self.config_path)
            self.recorder = Recorder(cfg, loop)
            self.recorder.on_event = self.event.emit
            if self._paused:
                self.recorder.paused = True
            if self._harvest is not None:
                self.recorder.harvest = self._harvest
            loop.run_until_complete(self.recorder.run())
        except Exception as e:
            logging.getLogger("mynaphone").exception("recorder crashed")
            self.failed.emit(str(e))
        finally:
            root.removeHandler(handler)
            self.recorder = None
            try:
                loop.close()
            except Exception:
                pass
            # the recorder's objects, Windows' media-session objects among them, sit in reference cycles; free them
            # here on the thread that made them, before Python starts shutting down
            gc.collect()

    def stop(self) -> None:
        """Ask the recorder to shut down, if there is one. The window calls it for the Stop button and when the app
        quits."""
        if self.recorder is not None:
            self.recorder.request_stop()

    def set_paused(self, paused: bool) -> None:
        """Pause or resume the recorder, now or once `run` makes it. While paused it starts no new takes."""
        self._paused = paused
        if self.recorder is not None:
            self.recorder.set_paused(paused)

    def set_harvest(self, on: bool) -> None:
        """Set harvest mode, now or once `run` makes the recorder. In harvest mode the recorder tells the player to
        skip an archived song, unless `upgrade_on_higher_tier` lets a higher tier replace it."""
        self._harvest = on
        if self.recorder is not None:
            self.recorder.set_harvest(on)
