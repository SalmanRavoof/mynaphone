# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Locate ffmpeg and fpcalc: the project's tools folder first, then PATH."""
from __future__ import annotations

import shutil
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"

_found: dict[str, str] = {}


def find(name: str) -> str | None:
    """The path of the program `name` anywhere under the project's `tools` folder, or else on `PATH`. It remembers
    only the paths it finds, so it's None until one of them has it."""
    if name in _found:
        return _found[name]
    exe = f"{name}.exe"
    path = next((str(p) for p in sorted(TOOLS.rglob(exe))), None) if TOOLS.exists() else None
    path = path or shutil.which(name)
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
