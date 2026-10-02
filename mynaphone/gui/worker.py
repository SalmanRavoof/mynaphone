# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs the asyncio recorder on a Qt thread and relays its events as signals."""
from __future__ import annotations

import asyncio
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
    event = Signal(dict)
    log = Signal(str)
    failed = Signal(str)

    def __init__(self, config_path: str, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.recorder: Recorder | None = None
        self._paused = False
        self._harvest: bool | None = None

    def run(self) -> None:
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

    def stop(self) -> None:
        if self.recorder is not None:
            self.recorder.request_stop()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if self.recorder is not None:
            self.recorder.set_paused(paused)

    def set_harvest(self, on: bool) -> None:
        self._harvest = on
        if self.recorder is not None:
            self.recorder.set_harvest(on)
