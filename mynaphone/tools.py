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
    exe = f"{name}.exe"
    if TOOLS.exists():
        for p in sorted(TOOLS.rglob(exe)):
            return str(p)
    return shutil.which(name)


def ffmpeg() -> str | None:
    return find("ffmpeg")


def fpcalc() -> str | None:
    return find("fpcalc")
