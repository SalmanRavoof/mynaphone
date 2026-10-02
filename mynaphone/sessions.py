# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Foreign-audio monitor: watches Windows per-app audio sessions during a take.

Endpoint loopback records the whole mix, so a notification chime or another app's sound ends up
inside the capture. Windows exposes every app's output as an audio session with a peak meter, so
we poll those and record any non-source process that produced sound above a threshold.
"""
from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field

log = logging.getLogger("mynaphone.sessions")


@dataclass
class ForeignSound:
    t: float            # monotonic time
    app: str
    peak_db: float


@dataclass
class ForeignReport:
    events: list[ForeignSound] = field(default_factory=list)

    @property
    def apps(self) -> list[str]:
        seen: list[str] = []
        for e in self.events:
            if e.app not in seen:
                seen.append(e.app)
        return seen

    @property
    def max_db(self) -> float:
        return max((e.peak_db for e in self.events), default=-120.0)


def app_session_volume(process_name: str) -> tuple[float, bool] | None:
    """(volume 0..1, muted) of the app's slider in the Windows Volume Mixer, or None if no session."""
    try:
        import comtypes
        from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
        try:
            comtypes.CoInitialize()
        except Exception:
            pass
        name = process_name.lower()
        for s in AudioUtilities.GetAllSessions():
            proc = s.Process
            if proc is None:
                continue
            try:
                pname = proc.name().lower()
            except Exception:
                continue
            if pname == name or pname.endswith(name):
                v = s._ctl.QueryInterface(ISimpleAudioVolume)
                return float(v.GetMasterVolume()), bool(v.GetMute())
    except Exception as e:
        log.debug("session volume lookup failed: %s", e)
    return None


class ForeignAudioMonitor(threading.Thread):
    def __init__(self, source_names: list[str], threshold_db: float = -120.0, interval: float = 0.2):
        super().__init__(name="foreign-audio-monitor", daemon=True)
        self.sources = {s.lower() for s in source_names}
        self.threshold = threshold_db
        self.interval = interval
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._events: list[ForeignSound] = []
        self._last_log: dict[str, float] = {}
        self.available = False
        self.my_pid = os.getpid()

    def stop(self) -> None:
        self._stop.set()

    def events_since(self, t0: float) -> ForeignReport:
        with self._lock:
            return ForeignReport([e for e in self._events if e.t >= t0])

    def forget_before(self, t0: float) -> None:
        with self._lock:
            self._events = [e for e in self._events if e.t >= t0]

    OWN = {"mynaphone-capture.exe"}

    def _is_source(self, name: str) -> bool:
        n = name.lower()
        return n in self.OWN or any(n == s or n.endswith(s) for s in self.sources)

    def run(self) -> None:
        try:
            import comtypes
            from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
        except Exception as e:
            log.warning("foreign-audio monitor unavailable: %s", e)
            return
        try:
            comtypes.CoInitialize()
        except Exception:
            pass
        self.available = True
        sessions = []
        refreshed = 0.0
        while not self._stop.wait(self.interval):
            now = time.monotonic()
            try:
                if now - refreshed > 2.0 or not sessions:
                    sessions = AudioUtilities.GetAllSessions()
                    refreshed = now
                for s in sessions:
                    try:
                        if s.State != 1:          # AudioSessionStateActive
                            continue
                        proc = s.Process
                        if proc is not None and proc.pid == self.my_pid:
                            continue
                        name = proc.name() if proc is not None else (s.DisplayName or "System sounds")
                        if name.startswith("@"):
                            name = "System sounds"
                        if self._is_source(name):
                            continue
                        peak = s._ctl.QueryInterface(IAudioMeterInformation).GetPeakValue()
                        if peak <= 0:
                            continue
                        db = 20.0 * math.log10(peak)
                        # threshold <= -100 means "any sound at all"
                        if self.threshold <= -100 or db >= self.threshold:
                            with self._lock:
                                self._events.append(ForeignSound(now, name, db))
                                if len(self._events) > 5000:
                                    self._events = self._events[-2500:]
                            if now - self._last_log.get(name, 0) > 5.0:
                                self._last_log[name] = now
                                log.info("other app making sound: %s (%.0f dBFS)", name, db)
                    except Exception:
                        continue
            except Exception as e:
                log.debug("session poll failed: %s", e)
                sessions = []
        try:
            comtypes.CoUninitialize()
        except Exception:
            pass
