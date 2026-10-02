# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Programmatically drawn icons so the app ships with no image assets."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap, QPolygonF

INK = "#1c1b19"
INK_DIM = "#5b574f"
RING = "#ede7da"
OCHRE = "#e0a526"
OCHRE_DIM = "#8d877b"
RED = "#e5484d"


PAPER = "#f3efe6"


def app_icon(state: str = "idle", size: int = 64, tile: bool = False) -> QIcon:
    """The mark: a myna's head in profile, beak and yellow eye patch included, always in ink.

    The eye is the status dot. It is dark while the app listens and red only while a song is
    being recorded. Paused greys the eye patch; stopped greys the whole head.

    With `tile` the head sits on a rounded paper square, for the tray, the title bar and the dark
    sidebar, where a bare ink head would vanish.
    """
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    if tile:
        p.setBrush(QBrush(QColor(PAPER)))
        p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
        inset = size * 0.1
        p.translate(inset, inset)
        k = (size - 2 * inset) / 64.0
    else:
        k = size / 64.0
    head_colour = INK_DIM if state == "stopped" else INK
    eye_colour = RED if state == "recording" else RING if state == "stopped" else "#0b0b0a"
    patch_colour = OCHRE_DIM if state in ("stopped", "paused") else OCHRE

    # head: an egg shape, slightly taller than wide
    p.setBrush(QBrush(QColor(head_colour)))
    p.drawEllipse(QRectF(6 * k, 8 * k, 44 * k, 48 * k))

    # beak, pointing right, slightly open
    p.setBrush(QBrush(QColor(patch_colour)))
    p.drawPolygon(QPolygonF([QPointF(45 * k, 27 * k), QPointF(64 * k, 33 * k), QPointF(45 * k, 36 * k)]))
    p.drawPolygon(QPolygonF([QPointF(45 * k, 36 * k), QPointF(62 * k, 38 * k), QPointF(45 * k, 44 * k)]))

    # the bare yellow skin behind the eye, then the eye itself
    p.drawEllipse(QRectF(27 * k, 19 * k, 22 * k, 14 * k))
    p.setBrush(QBrush(QColor(eye_colour)))
    r = 4.8 * k
    p.drawEllipse(QRectF(39 * k - r, 26 * k - r, 2 * r, 2 * r))
    p.end()
    return QIcon(pm)


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
