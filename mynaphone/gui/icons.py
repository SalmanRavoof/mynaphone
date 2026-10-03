# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Mynaphone mark from the designer's exports, and the sidebar icons drawn from Windows' icon font."""
from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# PNG exports of the designer's SVG source files (assets/mark/svg); to change the mark, edit those and re-export
MARK_DIR = Path(__file__).resolve().parent / "assets" / "mark"
MARK_SIZES = (16, 20, 24, 32, 48, 56, 64, 128, 256, 512)
MARK_STATES = {"idle": "listening", "recording": "recording", "paused": "paused", "stopped": "stopped"}
# At tray and taskbar sizes the designer's eye is about 3.5 px across at 24 px, too small to see turn red.
# Up to SMALL_PX the mark is drawn from its SVG with the yellow band and the eye scaled up around the eye.
SMALL_PX = 48
BAND_SCALE = 1.5
EYE_SCALE = 2.0


def _small_svg(state: str, variant: str) -> str | None:
    """The designer's SVG with a bigger eye, or None when its layout isn't the one this expects."""
    try:
        svg = (MARK_DIR / "svg" / f"mynaphone-{state}-{variant}.svg").read_text(encoding="utf-8")
        eye = json.loads((MARK_DIR / "geometry.json").read_text(encoding="utf-8"))["eye"]
        cx, cy = float(eye["cx"]), float(eye["cy"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    # the bill is the path clipped to the head; the band through the eye is the unclipped path in its colour
    bill = re.search(r'<path\b[^>]*clip-path="url\(#head-clip\)"[^>]*/>', svg)
    colour = re.search(r'fill="(#[0-9a-fA-F]{6})"', bill.group(0)) if bill else None
    band = re.search(rf'<path fill="{colour.group(1)}" d="[^"]*"/>', svg) if colour else None
    dot = re.search(r"<circle\b[^>]*/>", svg)
    if band is None or dot is None:
        return None

    def around(k: float) -> str:
        return f"translate({cx:g} {cy:g}) scale({k:g}) translate({-cx:g} {-cy:g})"

    bigger = (f'<g clip-path="url(#head-clip)"><g transform="{around(BAND_SCALE)}">{band.group(0)}</g></g>'
              f'<g transform="{around(EYE_SCALE)}">{dot.group(0)}</g>')
    return svg.replace(band.group(0), "").replace(dot.group(0), bigger)


def _render(svg: str, px: int) -> QPixmap:
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(p, QRectF(0, 0, px, px))
    p.end()
    return QPixmap.fromImage(img)


@cache
def _mark(state: str, variant: str) -> QIcon:
    icon = QIcon()
    small = _small_svg(state, variant)
    for size in MARK_SIZES:
        if small is not None and size <= SMALL_PX:
            icon.addPixmap(_render(small, size))
        else:
            icon.addFile(str(MARK_DIR / "png" / state / f"mynaphone-{state}-{variant}-{size}.png"),
                         QSize(size, size))
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
