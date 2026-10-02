# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Copy the library to a USB stick (or any folder), car-friendly: audio only unless asked, skip unchanged files."""
from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("mynaphone.export")

AUDIO = {".m4a", ".flac", ".mp3", ".opus"}


@dataclass
class ExportPlan:
    copy: list[tuple[Path, Path]] = field(default_factory=list)
    skip: int = 0
    remove: list[Path] = field(default_factory=list)
    bytes_to_copy: int = 0


def removable_drives() -> list[dict]:
    """Removable drives with their free space, for the picker."""
    import psutil
    out = []
    for part in psutil.disk_partitions(all=False):
        opts = (part.opts or "").lower()
        if "removable" not in opts and not part.device.upper().startswith(("E:", "F:", "G:", "H:")):
            continue
        try:
            u = shutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        out.append({"path": part.mountpoint, "fstype": part.fstype, "free": u.free, "total": u.total,
                    "removable": "removable" in opts})
    return out


def _same(src: Path, dst: Path) -> bool:
    try:
        a, b = src.stat(), dst.stat()
    except OSError:
        return False
    # FAT32 stores mtimes at 2 s resolution
    return a.st_size == b.st_size and abs(a.st_mtime - b.st_mtime) <= 2.5


def plan(library: Path, dest: Path, include_lyrics: bool = False, mirror: bool = False) -> ExportPlan:
    p = ExportPlan()
    wanted: set[Path] = set()
    for src in sorted(library.rglob("*")):
        if not src.is_file():
            continue
        ext = src.suffix.lower()
        if ext not in AUDIO and not (include_lyrics and ext == ".lrc"):
            continue
        rel = src.relative_to(library)
        dst = dest / rel
        wanted.add(dst)
        if _same(src, dst):
            p.skip += 1
        else:
            p.copy.append((src, dst))
            p.bytes_to_copy += src.stat().st_size
    if mirror and dest.exists():
        for f in dest.rglob("*"):
            if f.is_file() and f.suffix.lower() in AUDIO | {".lrc"} and f not in wanted:
                p.remove.append(f)
    return p


def run(p: ExportPlan, progress=None, should_stop=None) -> tuple[int, int]:
    """Execute a plan. progress(done_files, total_files, current_name); returns (copied, removed)."""
    total = len(p.copy) + len(p.remove)
    done = 0
    copied = removed = 0
    for src, dst in p.copy:
        if should_stop and should_stop():
            break
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(dst.suffix + ".part")
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
        copied += 1
        done += 1
        if progress:
            progress(done, total, dst.name)
    for f in p.remove:
        if should_stop and should_stop():
            break
        try:
            f.unlink()
            removed += 1
        except OSError as e:
            log.warning("could not remove %s: %s", f, e)
        done += 1
        if progress:
            progress(done, total, f.name)
    # prune empty folders left behind by removals
    for f in sorted({x.parent for x in p.remove}, key=lambda d: -len(d.parts)):
        try:
            if f.exists() and not any(f.iterdir()):
                f.rmdir()
        except OSError:
            pass
    return copied, removed
