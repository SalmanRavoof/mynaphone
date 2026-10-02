# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Audio capture engines with a pre-roll ring buffer.

Two engines share the same interface:

* ProcessCapture  - per-app capture through the native helper (tools/mynaphone-capture.exe), which
                    uses Windows' process-loopback API. Only the target app's audio is recorded, so
                    notifications and other apps can never bleed into a take.
* LoopbackCapture - whole-output-device WASAPI loopback through PortAudio (PyAudioWPatch).

Audio is kept in a short ring buffer at all times; when a take begins, ring content from the
requested start time onward is prepended so a late track-change event loses nothing.
"""
from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

log = logging.getLogger("mynaphone.capture")

HELPER = Path(__file__).resolve().parent.parent / "tools" / "mynaphone-capture.exe"


@dataclass
class Take:
    rate: int
    channels: int
    t_begin: float                      # monotonic time the take logically starts
    chunks: list[np.ndarray] = field(default_factory=list)
    overflows: int = 0
    device_changes: int = 0
    t_end: float | None = None

    def audio(self) -> np.ndarray:
        if not self.chunks:
            return np.zeros((0, self.channels), dtype=np.float32)
        return np.concatenate(self.chunks)

    @property
    def seconds(self) -> float:
        return sum(len(c) for c in self.chunks) / float(self.rate)


class _RingCapture:
    """Shared ring-buffer / take bookkeeping. Subclasses feed _push(chunk, glitch)."""

    def __init__(self, preroll_seconds: float):
        self.preroll = preroll_seconds
        self.rate = 0
        self.channels = 2
        self.device_name = ""
        self._ring: deque[tuple[float, np.ndarray]] = deque()
        self._ring_seconds = 0.0
        self._lock = threading.Lock()
        self._take: Take | None = None

    def _push(self, chunk: np.ndarray, glitch: bool = False) -> None:
        now = time.monotonic()
        with self._lock:
            if self._take is not None:
                if glitch:
                    self._take.overflows += 1
                self._take.chunks.append(chunk)
            self._ring.append((now, chunk))
            self._ring_seconds += len(chunk) / self.rate
            while self._ring_seconds > self.preroll and len(self._ring) > 1:
                _, old = self._ring.popleft()
                self._ring_seconds -= len(old) / self.rate

    def _note_restart(self) -> None:
        with self._lock:
            if self._take is not None:
                self._take.device_changes += 1
            self._ring.clear()
            self._ring_seconds = 0.0

    @property
    def ring_seconds(self) -> float:
        with self._lock:
            return self._ring_seconds

    def begin_take(self, t_begin: float) -> Take:
        with self._lock:
            take = Take(rate=self.rate, channels=self.channels, t_begin=t_begin)
            for t_chunk, chunk in self._ring:
                if t_chunk >= t_begin:
                    take.chunks.append(chunk)
            self._take = take
            return take

    def end_take(self) -> Take | None:
        with self._lock:
            take, self._take = self._take, None
            if take is not None:
                take.t_end = time.monotonic()
            return take

    @property
    def recording(self) -> bool:
        return self._take is not None

    @property
    def healthy(self) -> bool:
        return True


# ----------------------------------------------------------------------------- per-process

def root_pid(process_name: str) -> int | None:
    """Pid of the top-most process with this image name (the one whose parent is not the same app)."""
    import psutil
    name = process_name.lower()
    procs = []
    for p in psutil.process_iter(["name", "ppid"]):
        try:
            if (p.info["name"] or "").lower() == name:
                procs.append(p)
        except Exception:
            continue
    if not procs:
        return None
    pids = {p.pid for p in procs}
    roots = [p for p in procs if p.info["ppid"] not in pids]
    return (roots or procs)[0].pid


class ProcessCapture(_RingCapture):
    def __init__(self, process_name: str, rate: int = 48000, preroll_seconds: float = 3.0):
        super().__init__(preroll_seconds)
        self.process_name = process_name
        self.rate = rate
        self.channels = 2
        self.device_name = f"per-app capture of {process_name}"
        self.pid: int | None = None
        self.proc: subprocess.Popen | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._alive = False

    @staticmethod
    def available() -> bool:
        return HELPER.exists()

    def start(self) -> None:
        if not HELPER.exists():
            raise RuntimeError(f"capture helper missing: {HELPER}")
        self._stop.clear()
        self._thread = threading.Thread(target=self._supervise, name=f"capture-{self.process_name}", daemon=True)
        self._thread.start()
        log.info("per-app capture armed for %s at %d Hz", self.process_name, self.rate)

    def stop(self) -> None:
        self._stop.set()
        self._kill()

    @property
    def healthy(self) -> bool:
        return self._alive

    def _kill(self) -> None:
        p, self.proc = self.proc, None
        self._alive = False
        if p is None:
            return
        try:
            if p.stdin:
                p.stdin.close()
        except Exception:
            pass
        try:
            p.wait(timeout=2)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass

    def _supervise(self) -> None:
        """Keep a helper attached to the app's current process; wait while the app is not running."""
        while not self._stop.is_set():
            pid = root_pid(self.process_name)
            if pid is None:
                if self._alive:
                    log.info("%s closed; waiting for it", self.process_name)
                    self._kill()
                self._stop.wait(3.0)
                continue
            if self.proc is not None and self.proc.poll() is None and pid == self.pid:
                self._stop.wait(2.0)
                continue
            if self.proc is not None:
                self._note_restart()
                self._kill()
            self.pid = pid
            try:
                self._spawn(pid)
            except Exception as e:
                log.error("could not start capture helper for %s: %s", self.process_name, e)
                self._stop.wait(5.0)

    def _spawn(self, pid: int) -> None:
        self.proc = subprocess.Popen(
            [str(HELPER), "--pid", str(pid), "--rate", str(self.rate), "--channels", str(self.channels)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=self._read_stderr, args=(self.proc,), daemon=True).start()
        threading.Thread(target=self._read_audio, args=(self.proc,), daemon=True).start()

    def _read_stderr(self, p: subprocess.Popen) -> None:
        for raw in p.stderr:
            line = raw.decode(errors="ignore").strip()
            if line.startswith("READY"):
                self._alive = True
                log.info("capturing %s (pid %s) at %d Hz, %d ch", self.process_name, self.pid, self.rate, self.channels)
            elif line.startswith("FLAGS"):
                with self._lock:
                    if self._take is not None:
                        self._take.overflows += 1
                log.debug("capture packet flags: %s", line)
            elif line.startswith("EXIT"):
                self._alive = False
                if "done" not in line:
                    log.warning("capture helper for %s: %s", self.process_name, line)

    def _read_audio(self, p: subprocess.Popen) -> None:
        frame_bytes = self.channels * 4
        chunk_bytes = frame_bytes * (self.rate // 10)
        buf = b""
        while True:
            data = p.stdout.read(chunk_bytes)
            if not data:
                break
            buf += data
            while len(buf) >= chunk_bytes:
                part, buf = buf[:chunk_bytes], buf[chunk_bytes:]
                self._push(np.frombuffer(part, dtype=np.float32).reshape(-1, self.channels).copy())
        if buf:
            usable = len(buf) - (len(buf) % frame_bytes)
            if usable:
                self._push(np.frombuffer(buf[:usable], dtype=np.float32).reshape(-1, self.channels).copy())
        self._alive = False


# ----------------------------------------------------------------------------- whole device

class LoopbackCapture(_RingCapture):
    def __init__(self, device: str = "default", preroll_seconds: float = 3.0):
        super().__init__(preroll_seconds)
        self.device_pref = device
        self.pa = None
        self.stream = None
        self._stop = threading.Event()
        self._monitor: threading.Thread | None = None

    def _pick_loopback(self):
        import pyaudiowpatch as pyaudio
        assert self.pa is not None
        wasapi = self.pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        if self.device_pref.lower() == "default":
            out = self.pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
            wanted = out["name"]
            for d in self.pa.get_loopback_device_info_generator():
                if d["name"].startswith(wanted):
                    return d
            raise RuntimeError(f"no loopback endpoint for default output '{wanted}'")
        for d in self.pa.get_loopback_device_info_generator():
            if self.device_pref.lower() in d["name"].lower():
                return d
        for i in range(self.pa.get_device_count()):
            d = self.pa.get_device_info_by_index(i)
            if d["maxInputChannels"] > 0 and self.device_pref.lower() in d["name"].lower():
                return d
        raise RuntimeError(f"capture device '{self.device_pref}' not found")

    def _default_output_name(self) -> str:
        try:
            import pyaudiowpatch as pyaudio
            pa = pyaudio.PyAudio()
            try:
                w = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
                return pa.get_device_info_by_index(w["defaultOutputDevice"])["name"]
            finally:
                pa.terminate()
        except Exception:
            return ""

    def start(self) -> None:
        self._open()
        self._stop.clear()
        self._monitor = threading.Thread(target=self._monitor_loop, name="capture-monitor", daemon=True)
        self._monitor.start()

    def _open(self) -> None:
        import pyaudiowpatch as pyaudio
        self.pa = pyaudio.PyAudio()
        dev = self._pick_loopback()
        self.rate = int(dev["defaultSampleRate"])
        self.channels = max(1, min(2, int(dev["maxInputChannels"])))
        self.device_name = dev["name"]
        self.stream = self.pa.open(
            format=pyaudio.paFloat32, channels=self.channels, rate=self.rate, input=True,
            input_device_index=dev["index"], frames_per_buffer=self.rate // 10,
            stream_callback=self._callback,
        )
        log.info("capturing '%s' at %d Hz, %d ch", self.device_name, self.rate, self.channels)

    def _close(self) -> None:
        try:
            if self.stream is not None:
                self.stream.stop_stream()
                self.stream.close()
        except Exception:
            pass
        try:
            if self.pa is not None:
                self.pa.terminate()
        except Exception:
            pass
        self.stream = None
        self.pa = None

    def stop(self) -> None:
        self._stop.set()
        self._close()

    def _monitor_loop(self) -> None:
        while not self._stop.wait(5.0):
            try:
                if self.device_pref.lower() == "default":
                    current = self._default_output_name()
                    if current and not self.device_name.startswith(current):
                        log.warning("default output changed to '%s'; reopening capture", current)
                        self._reopen()
                        continue
                if self.stream is not None and not self.stream.is_active():
                    log.warning("capture stream inactive; reopening")
                    self._reopen()
            except Exception as e:
                log.error("capture monitor: %s", e)

    def _reopen(self) -> None:
        self._note_restart()
        self._close()
        try:
            self._open()
        except Exception as e:
            log.error("reopen failed: %s", e)

    def _callback(self, in_data, frame_count, time_info, status):
        import pyaudiowpatch as pyaudio
        chunk = np.frombuffer(in_data, dtype=np.float32).reshape(-1, self.channels).copy()
        self._push(chunk, glitch=bool(status))
        return (None, pyaudio.paContinue)


def list_devices() -> list[str]:
    import pyaudiowpatch as pyaudio
    pa = pyaudio.PyAudio()
    out = []
    try:
        w = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        default = pa.get_device_info_by_index(w["defaultOutputDevice"])["name"]
        out.append(f"default output: {default}")
        for d in pa.get_loopback_device_info_generator():
            out.append(f"loopback: {d['name']}  ({int(d['defaultSampleRate'])} Hz)")
        for i in range(pa.get_device_count()):
            d = pa.get_device_info_by_index(i)
            if d["maxInputChannels"] > 0 and "[Loopback]" not in d["name"] and d["hostApi"] == w["index"]:
                out.append(f"input: {d['name']}  ({int(d['defaultSampleRate'])} Hz)")
    finally:
        pa.terminate()
    return out
