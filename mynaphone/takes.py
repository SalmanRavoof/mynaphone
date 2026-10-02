# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finalizing a take: trimming, verdict, FLAC writing and provisional tagging."""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf
from mutagen.flac import FLAC, Picture

log = logging.getLogger("mynaphone.takes")

SILENCE = 10 ** (-60 / 20)       # -60 dBFS: anything below is treated as silence for trimming
AUDIBLE = 10 ** (-45 / 20)       # -45 dBFS: clearly audible, so the song has begun
HOLE = 10 ** (-80 / 20)          # -80 dBFS: what a player sends while it waits or is paused
HOLE_MS = 300                    # a stretch this long inside the music spoils the take


@dataclass
class TakeMeta:
    app: str
    artist: str = ""
    title: str = ""
    album: str = ""
    album_artist: str = ""
    track_number: int = 0
    disc_number: int = 0
    expected_ms: int = 0
    source_uri: str = ""
    album_uri: str = ""
    artist_uris: list[str] = field(default_factory=list)
    quality_tier: str = "unknown"
    quality_raw: dict | None = None
    cover: bytes | None = None
    cover_url: str = ""
    started_at: str = ""
    ended_at: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class Verdict:
    keep: bool
    reasons: list[str]
    captured_ms: int
    wall_ms: int
    trimmed_lead_ms: int = 0


def trim(audio: np.ndarray, rate: int, expected_ms: int, lead_window_s: float, tolerance_s: float
         ) -> tuple[np.ndarray, int]:
    """Cut leading silence (within lead_window) and truncate to the expected duration.

    Returns (audio, trimmed_lead_ms).
    """
    if len(audio) == 0:
        return audio, 0
    mono = np.max(np.abs(audio), axis=1)
    window = min(len(mono), int(lead_window_s * rate))
    idx = np.argmax(mono[:window] > SILENCE) if window else 0
    if window and not (mono[:window] > SILENCE).any():
        idx = window
    audio = audio[idx:]
    lead_ms = int(idx * 1000 / rate)
    if expected_ms > 0:
        limit = int((expected_ms / 1000.0 + 0.3) * rate)
        audio = audio[:limit]
        # strip only the silence that lies beyond the published duration; the track keeps its
        # own trailing silence so gapless albums line up
        floor = int(expected_ms / 1000.0 * rate)
        m = np.max(np.abs(audio), axis=1)
        last = len(m)
        while last > floor and m[last - 1] <= SILENCE:
            last -= 1
        audio = audio[:last]
    return audio, lead_ms


def longest_hole_ms(audio: np.ndarray, rate: int, tail_s: float = 10.0) -> int:
    """The longest stretch of near-digital silence between the song's first clearly audible moment and its
    last tail_s seconds, which are left out because songs end quietly.

    A player that pauses mid-song leaves a hole like this in the capture. One that stalls while it loads
    usually sends nothing at all, so the song comes out whole and only runs late.
    """
    blk = max(1, rate // 100)                          # 10 ms blocks
    n = len(audio) // blk
    if n == 0:
        return 0
    peaks = np.max(np.abs(audio[: n * blk]), axis=1).reshape(n, blk).max(axis=1)
    loud = np.flatnonzero(peaks > AUDIBLE)
    if len(loud) == 0:
        return 0
    quiet = peaks[loud[0]: max(int(loud[0]), n - int(tail_s * rate / blk))] < HOLE
    if not quiet.any():
        return 0
    edges = np.diff(np.concatenate(([0], quiet.astype(np.int8), [0])))
    longest = int((np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)).max())
    return longest * blk * 1000 // rate


def judge(meta: TakeMeta, captured_s: float, wall_s: float, flags: dict, cfg) -> Verdict:
    reasons: list[str] = []
    tol = cfg.rules.duration_tolerance_seconds
    exp_s = meta.expected_ms / 1000.0
    # A stall only spoils the file when it left a hole in the music (see longest_hole_ms). Without the
    # audio to look at, assume it did.
    hole = flags.get("hole_ms")
    spoiled = hole is None or hole >= HOLE_MS
    if meta.expected_ms <= 0:
        reasons.append("no_duration")
    elif exp_s < cfg.rules.min_duration_seconds:
        reasons.append("too_short")
    if flags.get("start_position_ms", 0) > 1500:
        reasons.append(f"started_mid_track:{flags['start_position_ms']}ms")
    if flags.get("paused") and cfg.rules.discard_on_pause:
        reasons.append("paused")
    if flags.get("seek") and cfg.rules.discard_on_seek:
        reasons.append("seek")
    if flags.get("buffering"):
        if spoiled:
            reasons.append("buffering")
        else:
            log.info("%s stalled, but the audio has no hole in it; keeping the take", meta.title)
    if flags.get("overflows", 0):
        reasons.append(f"capture_overflow:{flags['overflows']}")
    if flags.get("device_changes", 0):
        reasons.append("device_changed")
    if flags.get("ended_early"):
        reasons.append(flags["ended_early"])
    if flags.get("mixer_volume") is not None:
        reasons.append(f"mixer_volume:{flags['mixer_volume']}")
    if flags.get("app_volume") is not None:
        reasons.append(f"app_volume:{flags['app_volume']}")
    fa = flags.get("foreign_audio")
    if fa and cfg.rules.discard_on_foreign_audio and not fa.get("isolated"):
        reasons.append("foreign_audio:" + ",".join(fa.get("apps", [])))
    if meta.expected_ms > 0:
        if abs(captured_s - exp_s) > tol:
            reasons.append(f"length_mismatch:{captured_s:.1f}s_vs_{exp_s:.1f}s")
        if wall_s - exp_s > tol + 1.0 and spoiled:
            reasons.append(f"stalled:{wall_s - exp_s:.1f}s_extra")
        if exp_s - wall_s > tol:
            reasons.append(f"cut_short:{exp_s - wall_s:.1f}s_missing")
    return Verdict(keep=not reasons, reasons=reasons, captured_ms=int(captured_s * 1000), wall_ms=int(wall_s * 1000))


_bad = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(s: str, limit: int = 80) -> str:
    s = _bad.sub("_", s).strip(" .")
    return (s or "untitled")[:limit]


def write_flac(path: Path, audio: np.ndarray, rate: int, bit_depth: int) -> None:
    subtype = "PCM_24" if bit_depth == 24 else "PCM_16"
    if bit_depth == 16:
        # TPDF dither before truncating float32 to 16-bit
        audio = audio + (np.random.random(audio.shape) + np.random.random(audio.shape) - 1.0) / 32768.0
    audio = np.clip(audio, -1.0, 1.0)
    sf.write(str(path), audio, rate, subtype=subtype)


def tag_flac(path: Path, meta: TakeMeta, verdict: Verdict, rate: int, bit_depth: int) -> None:
    f = FLAC(str(path))
    f.delete()
    f["TITLE"] = meta.title
    if meta.artist:
        f["ARTIST"] = meta.artist
    if meta.album:
        f["ALBUM"] = meta.album
    if meta.album_artist:
        f["ALBUMARTIST"] = meta.album_artist
    if meta.track_number:
        f["TRACKNUMBER"] = str(meta.track_number)
    if meta.disc_number:
        f["DISCNUMBER"] = str(meta.disc_number)
    f["MYNAPHONE_SOURCE_APP"] = meta.app
    if meta.source_uri:
        f["MYNAPHONE_SOURCE_URI"] = meta.source_uri
    f["MYNAPHONE_QUALITY_TIER"] = meta.quality_tier
    f["MYNAPHONE_CAPTURED_AT"] = meta.started_at
    f["MYNAPHONE_CAPTURE_FORMAT"] = f"{rate}Hz/{bit_depth}bit float-loopback"
    f["MYNAPHONE_STAGE"] = "inbox"
    f["COMMENT"] = "Captured by mynaphone; metadata provisional until post-processing."
    if meta.cover:
        pic = Picture()
        pic.type = 3
        pic.mime = "image/jpeg" if meta.cover[:3] == b"\xff\xd8\xff" else "image/png"
        pic.data = meta.cover
        f.clear_pictures()
        f.add_picture(pic)
    f.save()


def sidecar(path: Path, meta: TakeMeta, verdict: Verdict, flags: dict, rate: int, bit_depth: int) -> None:
    doc = {
        "meta": {k: v for k, v in meta.__dict__.items() if k != "cover"},
        "verdict": verdict.__dict__,
        "flags": flags,
        "capture": {"rate": rate, "bit_depth": bit_depth},
        "written_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    path.with_suffix(".json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def output_path(root: Path, meta: TakeMeta) -> Path:
    stem = (f"{safe_name(meta.artist or 'Unknown Artist')} - {safe_name(meta.title or 'Unknown Title')} "
            f"[{uuid.uuid4().hex[:8]}]")
    return root / f"{stem}.flac"
