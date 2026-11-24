# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Locate ffmpeg and fpcalc: the project's tools folder first, then PATH."""
from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"


@lru_cache(maxsize=None)
def find(name: str) -> str | None:
    """The path of the program `name` anywhere under the project's `tools` folder, or on `PATH` when the folder lacks
    it. It's None when neither has it, and it caches every answer."""
    exe = f"{name}.exe"
    if TOOLS.exists():
        for p in sorted(TOOLS.rglob(exe)):
            return str(p)
    return shutil.which(name)


def ffmpeg() -> str | None:
    """The path of `ffmpeg`, or None when `find` can't find it. It encodes the library's lossy formats, and it cuts a
    later stretch of a recording for a second fingerprint try."""
    return find("ffmpeg")


def fpcalc() -> str | None:
    """The path of `fpcalc`, the Chromaprint program that fingerprints a recording for AcoustID, or None when `find`
    can't find it."""
    return find("fpcalc")
