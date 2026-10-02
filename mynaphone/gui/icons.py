# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Mynaphone mark from the designer's exports, and the sidebar icons drawn from Windows' icon font."""
from __future__ import annotations

from functools import cache
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap

# PNG exports of the designer's SVG source files (assets/mark/svg); to change the mark, edit those and re-export
MARK_DIR = Path(__file__).resolve().parent / "assets" / "mark"
MARK_SIZES = (16, 20, 24, 32, 48, 56, 64, 128, 256, 512)
MARK_STATES = {"idle": "listening", "recording": "recording", "paused": "paused", "stopped": "stopped"}


@cache
def _mark(state: str, variant: str) -> QIcon:
    icon = QIcon()
    for size in MARK_SIZES:
        icon.addFile(str(MARK_DIR / "png" / state / f"mynaphone-{state}-{variant}-{size}.png"), QSize(size, size))
    return icon


def app_icon(state: str = "idle", tile: bool = False) -> QIcon:
    """The mark: a myna's head in profile with its yellow eye patch and bill.

    The eye is the status light. It's dark while the app listens and red only while a song is being
    recorded; nothing else moves. Paused greys the patch and bill, and stopped greys the whole bird.

    With `tile` the bird sits on a rounded paper square, for the tray and the title bar, where the bare
    ink bird would vanish on a dark taskbar. Qt picks the export nearest each size and display scale.
    """
    return _mark(MARK_STATES.get(state, "listening"), "tile" if tile else "bare")


# Segoe MDL2 Assets glyphs, present on every Windows 10 and 11 install
NAV_GLYPHS = {
    "Status": "",        # home
    "Activity": "",      # history
    "Library": "",       # library
    "Settings": "",      # settings
    "Setup check": "",   # check list
    "Set up": "",        # repair
}


def _glyph(char: str, colour: str, size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    f = QFont("Segoe MDL2 Assets")
    f.setPixelSize(int(size * 0.8))
    p.setFont(f)
    p.setPen(QColor(colour))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, char)
    p.end()
    return pm


def nav_icon(name: str, size: int = 18) -> QIcon:
    """Sidebar icon in three tones: resting, hovered, selected (ochre)."""
    char = NAV_GLYPHS.get(name, "")
    icon = QIcon()
    if not char or "Segoe MDL2 Assets" not in QFontDatabase.families():
        return icon
    icon.addPixmap(_glyph(char, "#a9a397", size), QIcon.Normal)
    icon.addPixmap(_glyph(char, "#f3efe6", size), QIcon.Active)
    icon.addPixmap(_glyph(char, "#f3b43b", size), QIcon.Selected)
    return icon
