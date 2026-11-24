# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Locate ffmpeg and fpcalc: the project's tools folder first, then PATH."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"

_found: dict[str, str] = {}


def find(name: str) -> str | None:
    """The path of the program `name` anywhere under the project's `tools` folder, or else on `PATH`. It's None
    until one of them has it. It remembers a path it finds until the file there is gone, and it skips `tools/dl`,
    where setup-tools unpacks a download before it moves it into place."""
    path = _found.get(name)
    if path and os.path.isfile(path):
        return path
    exe = f"{name}.exe"
    found = [p for p in sorted(TOOLS.rglob(exe)) if TOOLS / "dl" not in p.parents] if TOOLS.exists() else []
    path = str(found[0]) if found else shutil.which(name)
    if path:
        _found[name] = path
    return path


def ffmpeg() -> str | None:
    """The path of `ffmpeg`, or None when `find` can't find it. It encodes the library's lossy formats, and it cuts a
    later stretch of a recording for a second fingerprint try."""
    return find("ffmpeg")


def fpcalc() -> str | None:
    """The path of `fpcalc`, the Chromaprint program that fingerprints a recording for AcoustID, or None when `find`
    can't find it."""
    return find("fpcalc")
