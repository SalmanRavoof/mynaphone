# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Free-space estimate: how many average songs fit on the chosen drive, working space included."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

AVERAGE_SONG_SECONDS = 270          # typical film song / pop track, 4.5 minutes
FLAC_MB_PER_SONG = 31.0             # 16-bit 48 kHz capture of a 4.5-minute song
RESERVE_GB = 2.0                    # never plan to fill the drive completely
INBOX_SONGS = 20                    # takes that may wait in the inbox while offline
DISCARDS_PER_DAY = 10               # rejected takes kept for inspection


@dataclass
class Estimate:
    """A drive's free space, from `estimate`, and how many songs fit in it. `songs` counts the songs of `per_song_mb`
    each that fit after a 2 GB reserve and `working_mb` of working space for the recorder. `format_label` names the
    library format, such as FLAC or AAC 256 kbps."""
    drive: str
    free_bytes: int
    total_bytes: int
    per_song_mb: float
    working_mb: float
    songs: int
    format_label: str

    @property
    def free_gb(self) -> float:
        """The drive's free space in decimal gigabytes."""
        return self.free_bytes / 1e9


def per_song_mb(fmt: str, bitrate_kbps: int, bit_depth: int = 16) -> float:
    """The megabytes a 4.5-minute song takes in `fmt`. FLAC counts as 31 MB, or 46.5 MB at a 24-bit `bit_depth`, and
    other formats go by `bitrate_kbps`."""
    if fmt == "flac":
        return FLAC_MB_PER_SONG * (1.5 if bit_depth == 24 else 1.0)
    return bitrate_kbps * AVERAGE_SONG_SECONDS / 8 / 1000.0


def estimate(folder: Path, fmt: str, bitrate_kbps: int, keep_discards_days: int = 3,
             bit_depth: int = 16) -> Estimate | None:
    """Songs that fit in the folder's drive after a reserve and the recorder's working space."""
    try:
        probe = folder
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        u = shutil.disk_usage(probe)
    except OSError:
        return None
    song = per_song_mb(fmt, bitrate_kbps, bit_depth)
    working = FLAC_MB_PER_SONG * (INBOX_SONGS + DISCARDS_PER_DAY * max(0, keep_discards_days))
    usable_mb = u.free / 1e6 - RESERVE_GB * 1000 - working
    songs = max(0, int(usable_mb / song)) if song > 0 else 0
    label = "FLAC" if fmt == "flac" else f"{fmt.upper()} {bitrate_kbps} kbps"
    return Estimate(drive=str(probe.drive or probe), free_bytes=u.free, total_bytes=u.total, per_song_mb=song,
                    working_mb=working, songs=songs, format_label=label)


def describe(est: Estimate | None) -> str:
    """How many songs fit on the drive in `est` and about how many hours that is, as a sentence, or that none fit.
    Without `est`, it says it couldn't read the drive."""
    if est is None:
        return "Could not read the drive."
    if est.songs <= 0:
        return f"{est.drive} has {est.free_gb:.1f} GB free, which is not enough once working space is set aside."
    hours = est.songs * AVERAGE_SONG_SECONDS / 3600
    return (f"{est.drive} has {est.free_gb:.0f} GB free: room for about {est.songs:,} songs as {est.format_label} "
            f"(roughly {hours:,.0f} hours), after keeping {est.working_mb / 1000:.1f} GB "
            f"for recordings in progress and "
            f"{RESERVE_GB:.0f} GB spare.")
