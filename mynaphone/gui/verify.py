# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Setup checks shown on the Verify tab. Each check returns (status, detail)."""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import winreg
from dataclasses import dataclass
from pathlib import Path

from ..config import Config

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"


@dataclass
class Result:
    name: str
    status: str
    detail: str


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except Exception:
        return ""


def check_capture_device(cfg: Config) -> Result:
    if cfg.capture.mode == "process":
        from ..capture import HELPER, root_pid
        if not HELPER.exists():
            return Result("Capture", FAIL,
                          f"per-app capture helper missing at {HELPER}; switch to whole-device capture or rebuild it")
        running = [s for s in cfg.rules.sources if root_pid(s)]
        return Result("Capture", OK,
                      f"per-app capture of {', '.join(cfg.rules.sources)} at {cfg.capture.sample_rate or 48000} Hz"
                      + (f"; running now: {', '.join(running)}" if running
                         else "; none of the source apps is running yet"))
    try:
        import pyaudiowpatch as pyaudio
        pa = pyaudio.PyAudio()
        try:
            w = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            default = pa.get_device_info_by_index(w["defaultOutputDevice"])
            if cfg.capture.device.lower() == "default":
                for d in pa.get_loopback_device_info_generator():
                    if d["name"].startswith(default["name"]):
                        return Result("Capture device", OK, f"{default['name']} at {int(d['defaultSampleRate'])} Hz "
                                                            f"(follows Windows default)")
                return Result("Capture device", FAIL, f"no loopback endpoint for default output '{default['name']}'")
            for d in pa.get_loopback_device_info_generator():
                if cfg.capture.device.lower() in d["name"].lower():
                    return Result("Capture device", OK, f"{d['name']} at {int(d['defaultSampleRate'])} Hz")
            for i in range(pa.get_device_count()):
                d = pa.get_device_info_by_index(i)
                if d["maxInputChannels"] > 0 and cfg.capture.device.lower() in d["name"].lower():
                    return Result("Capture device", OK, f"{d['name']} at {int(d['defaultSampleRate'])} Hz (input)")
            return Result("Capture device", FAIL, f"'{cfg.capture.device}' not found")
        finally:
            pa.terminate()
    except Exception as e:
        return Result("Capture device", FAIL, str(e))


def check_default_format() -> Result:
    """Read the Windows default playback device's shared-mode format from the registry."""
    try:
        base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            i = 0
            found = []
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, sub) as k:
                        state = winreg.QueryValueEx(k, "DeviceState")[0]
                    if state != 1:
                        continue
                    with winreg.OpenKey(root, sub + r"\Properties") as pk:
                        name = winreg.QueryValueEx(pk, "{a45c254e-df1c-4efd-8020-67d146a850e0},2")[0]
                        fmt = winreg.QueryValueEx(pk, "{f19f064d-082c-4e27-bc73-6882a1bb8e4c},0")[0]
                    rate = int.from_bytes(fmt[12:16], "little")
                    bits = int.from_bytes(fmt[26:28], "little")
                    found.append(f"{name}: {rate} Hz / {bits}-bit")
                except OSError:
                    continue
        if not found:
            return Result("Playback format", WARN, "could not read device formats")
        return Result("Playback format", INFO,
                      "; ".join(found) + ". 44.1 kHz avoids resampling for Spotify; 48 kHz is fine for lossy sources.")
    except Exception as e:
        return Result("Playback format", WARN, str(e))


def check_enhancements() -> Result:
    out = _run(["sc", "query", "NahimicService"])
    procs = (_run(["tasklist", "/FI", "IMAGENAME eq NahimicSvc64.exe"])
             + _run(["tasklist", "/FI", "IMAGENAME eq NahimicService.exe"]))
    if "RUNNING" in out or "Nahimic" in procs:
        return Result("Audio enhancements", FAIL, "Nahimic is running; it processes audio before the capture point")
    return Result("Audio enhancements", OK,
                  "Nahimic absent. Keep 'Enable audio enhancements' unticked on the playback device.")


def check_spotify() -> Result:
    procs = _run(["tasklist", "/FI", "IMAGENAME eq Spotify.exe"])
    if "Spotify.exe" not in procs:
        return Result("Spotify", WARN, "not running")
    try:
        from .. import smtc as S

        async def probe():
            mgr = await S.Manager.request_async()
            for s in mgr.get_sessions():
                if (s.source_app_user_model_id or "").lower().startswith("spotify"):
                    return await S.snapshot(s)
            return None
        snap = asyncio.run(probe())
        if snap is None:
            return Result("Spotify", WARN, "running, but no media session yet (play something)")
        return Result("Spotify", OK, f"media session visible: {snap.describe()}")
    except Exception as e:
        return Result("Spotify", WARN, f"running; media-session probe failed: {e}")


def check_spicetify(cfg: Config, bridge_connected: bool | None) -> Result:
    appdata = Path(os.environ.get("APPDATA", ""))
    ext = appdata / "spicetify" / "Extensions" / "mynaphone.js"
    ini = appdata / "spicetify" / "config-xpui.ini"
    if not ext.exists():
        return Result("Spicetify bridge", WARN, "extension not installed (run install-spicetify). "
                                                "Recording still works via the Windows media session, "
                                                "but quality tier and exact track ids will be missing.")
    enabled = ini.exists() and "mynaphone.js" in ini.read_text(encoding="utf-8", errors="ignore")
    if not enabled:
        return Result("Spicetify bridge", WARN, "extension file present but not enabled in spicetify config")
    if bridge_connected is True:
        return Result("Spicetify bridge", OK, f"connected on port {cfg.bridge.port}")
    if bridge_connected is False:
        return Result("Spicetify bridge", WARN, "installed and enabled, but Spotify has not connected; "
                                                "restart Spotify or re-run 'spicetify apply' after a Spotify update")
    return Result("Spicetify bridge", INFO, "installed and enabled; connection is reported while the recorder runs")


def check_disk(cfg: Config) -> Result:
    from .. import storage
    try:
        est = storage.estimate(cfg.paths.library_dir, cfg.library.format, cfg.library.bitrate,
                               cfg.rules.keep_discards_days, cfg.capture.bit_depth)
        if est is None:
            return Result("Disk space", WARN, "could not read the library drive")
        status = OK if est.songs > 500 else (WARN if est.songs > 50 else FAIL)
        text = storage.describe(est)
        if cfg.paths.inbox_dir.drive != cfg.paths.library_dir.drive:
            u = shutil.disk_usage(cfg.paths.inbox_dir)
            text += f" The inbox drive {cfg.paths.inbox_dir.drive} has {u.free / 1e9:.0f} GB free."
        return Result("Disk space", status, text)
    except Exception as e:
        return Result("Disk space", WARN, str(e))


def check_ffmpeg() -> Result:
    from .. import tools
    ff, fp = tools.ffmpeg(), tools.fpcalc()
    if ff and fp:
        return Result("Tools", OK, "ffmpeg and Chromaprint found; songs can be encoded and identified")
    missing = " and ".join(n for n, v in (("ffmpeg", ff), ("Chromaprint", fp)) if not v)
    return Result("Tools", WARN, f"{missing} not found; run step 1 on the Set up page. Recording works without them, "
                                 "filing waits until they are there")


def run_all(cfg: Config, bridge_connected: bool | None) -> list[Result]:
    return [
        check_capture_device(cfg),
        check_default_format(),
        check_enhancements(),
        check_spotify(),
        check_spicetify(cfg, bridge_connected),
        check_app_volumes(cfg),
        check_disk(cfg),
        check_ffmpeg(),
    ]


def check_app_volumes(cfg: Config) -> Result:
    from ..sessions import app_session_volume
    low = []
    for src in cfg.rules.sources:
        v = app_session_volume(src)
        if v is None:
            continue
        vol, muted = v
        if muted or vol < 0.99:
            low.append(f"{src} at {0 if muted else int(round(vol * 100))}%")
    if low:
        return Result("Volume Mixer", WARN, "; ".join(low) + ". Set these apps to 100% in the Windows Volume Mixer; "
                                                             "takes started below 100% are rejected. "
                                                             "The master volume can stay anywhere.")
    return Result("Volume Mixer", OK, "source apps at 100% (or not playing yet). "
                                      "The Windows master volume and mute do not affect per-app capture.")


MANUAL_CHECKS = [
    ("Spotify > Audio quality > Streaming quality",
     "set explicitly (High on Free, Very High or Lossless on Premium), never Automatic"),
    ("Spotify > Audio quality > Auto adjust quality",
     "off, so a weak connection stalls instead of silently lowering the bitrate"),
    ("Spotify > Playback > Normalize volume", "off"),
    ("Spotify > Playback > Crossfade and Automix", "off"),
    ("Spotify > Playback > Equalizer and Mono audio", "off"),
    ("Spotify > Autoplay", "off, unless you want the queue to keep going on its own"),
    ("Spotify > Exclusive Mode (if shown)", "off; exclusive mode bypasses the capture point"),
    ("Spotify's own volume slider",
     "100 %. The Windows master volume can be anything; the Volume Mixer slider is checked automatically above."),
]
