# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""The app's look, taken from the common myna: an ink-dark body, a warm paper canvas and one ochre
highlight where the bird has its yellow eye patch. Flat shapes, no gradients, consistent heights."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication, QWidget

INK = "#1c1b19"            # sidebar, primary buttons, headings
INK_HOVER = "#33312c"
INK_RAISED = "#2a2825"     # hovered sidebar row
INK_SELECTED = "#34322d"   # selected sidebar row
SIDE_TEXT = "#cfc9bd"
SIDE_MUTED = "#8d877b"
SIDE_BRIGHT = "#f3efe6"
OCHRE = "#f3b43b"          # highlight on dark
ACCENT = "#c9880f"         # highlight on light: focus rings, progress, marks
ACCENT_SOFT = "#fbefd2"
TEXT = "#1c1b19"
MUTED = "#6b665c"
BORDER = "#d9d3c7"
BORDER_SOFT = "#e9e4da"
CANVAS = "#f4f1ea"
CARD = "#ffffff"
CARD_TINT = "#faf8f3"
RED = "#c8373e"
RED_SOFT = "#fbe7e7"
GREEN = "#2f7d4f"
GREEN_SOFT = "#e4f1e8"
AMBER = "#9a6700"
AMBER_SOFT = "#fbefd2"
GREY_SOFT = "#ece8e0"


def _assets() -> dict[str, str]:
    """Draw the few glyphs the stylesheet needs (check mark, chevron) and return file paths."""
    d = Path(tempfile.gettempdir()) / "mynaphone-ui"
    d.mkdir(parents=True, exist_ok=True)
    out = {}

    def save(name: str, pm: QPixmap) -> None:
        p = d / f"{name}.png"
        pm.save(str(p), "PNG")
        out[name] = str(p).replace("\\", "/")

    pm = QPixmap(16, 16)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(SIDE_BRIGHT), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPolyline(QPolygonF([QPointF(3.5, 8.5), QPointF(6.5, 11.5), QPointF(12.5, 5)]))
    p.end()
    save("check", pm)

    pm = QPixmap(12, 12)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(MUTED), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPolyline(QPolygonF([QPointF(2.5, 4.5), QPointF(6, 8), QPointF(9.5, 4.5)]))
    p.end()
    save("chevron", pm)
    return out


def build_qss(a: dict[str, str]) -> str:
    return f"""
* {{ font-family: "Segoe UI"; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QWidget#canvas {{ background: {CANVAS}; }}

QFrame#card {{ background: {CARD}; border: 1px solid {BORDER_SOFT}; border-radius: 10px; }}
QLabel {{ background: transparent; }}
QLabel#h1 {{ font-size: 19pt; font-weight: 600; color: {INK}; }}
QLabel#h2 {{ font-size: 12pt; font-weight: 600; color: {INK}; }}
QLabel#title {{ font-size: 16pt; font-weight: 600; color: {INK}; }}
QLabel#stat {{ font-size: 24pt; font-weight: 600; color: {INK}; }}
QLabel#eyebrow {{ color: {MUTED}; font-size: 8pt; font-weight: 700; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#small {{ color: {MUTED}; font-size: 9pt; }}
QLabel#cover {{ background: {GREY_SOFT}; border: none; border-radius: 10px; }}

QLabel#pill {{ border-radius: 11px; padding: 1px 10px; font-size: 9pt; font-weight: 600; min-height: 20px; }}
QLabel#pill[tone="off"] {{ background: {GREY_SOFT}; color: {MUTED}; }}
QLabel#pill[tone="ok"] {{ background: {GREEN_SOFT}; color: {GREEN}; }}
QLabel#pill[tone="warn"] {{ background: {AMBER_SOFT}; color: {AMBER}; }}
QLabel#pill[tone="rec"] {{ background: {RED_SOFT}; color: {RED}; }}

QWidget#sidebar {{ background: {INK}; }}
QWidget#sidebar QLabel {{ color: {SIDE_MUTED}; }}
QLabel#brand {{ color: {SIDE_BRIGHT}; font-size: 13pt; font-weight: 600; }}
QLabel#sidestate {{ color: {SIDE_TEXT}; font-weight: 600; }}
QListWidget#nav {{ background: transparent; border: none; outline: none; }}
QListWidget#nav::item {{ height: 36px; padding-left: 10px; border-radius: 7px; margin: 2px 10px; color: {SIDE_TEXT}; }}
QListWidget#nav::item:hover {{ background: {INK_RAISED}; color: {SIDE_BRIGHT}; }}
QListWidget#nav::item:selected {{ background: {INK_SELECTED}; color: {OCHRE}; font-weight: 600; }}

QPushButton {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 7px; \
padding: 0 14px; min-height: 30px; color: {INK}; }}
QPushButton:hover {{ background: {CARD_TINT}; border-color: #c9c2b4; }}
QPushButton:pressed {{ background: {GREY_SOFT}; }}
QPushButton:disabled {{ color: #a39d91; border-color: {BORDER_SOFT}; background: {CARD_TINT}; }}
QPushButton#primary {{ background: {INK}; border-color: {INK}; color: {SIDE_BRIGHT}; font-weight: 600; }}
QPushButton#primary:hover {{ background: {INK_HOVER}; border-color: {INK_HOVER}; }}
QPushButton#primary:disabled {{ background: #8f8b83; border-color: #8f8b83; color: {SIDE_BRIGHT}; }}
QPushButton#danger {{ background: {CARD}; border-color: {BORDER}; color: {RED}; font-weight: 600; }}
QPushButton#danger:hover {{ background: {RED_SOFT}; border-color: #e3b4b6; }}
QPushButton:checked {{ background: {AMBER_SOFT}; border-color: {ACCENT}; color: {AMBER}; }}
QToolButton {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 7px; min-height: 28px; padding: 0 10px; }}
QToolButton:hover {{ background: {CARD_TINT}; }}

QLineEdit, QComboBox, QSpinBox {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 7px; \
padding: 0 8px; min-height: 30px; selection-background-color: {INK}; selection-color: {SIDE_BRIGHT}; }}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: #c9c2b4; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 2px solid {ACCENT}; padding: 0 7px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 26px; border: none; }}
QComboBox::down-arrow {{ image: url("{a['chevron']}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {CARD}; border: 1px solid {BORDER}; \
selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT}; outline: none; padding: 4px; }}

QCheckBox {{ spacing: 8px; min-height: 24px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; \
border: 1px solid {BORDER}; border-radius: 4px; background: {CARD}; }}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {INK}; border-color: {INK}; image: url("{a['check']}"); }}

QProgressBar {{ background: {GREY_SOFT}; border: none; border-radius: 2px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}

QTableWidget, QTreeWidget {{ background: {CARD}; border: 1px solid {BORDER_SOFT}; border-radius: 8px; \
gridline-color: transparent; alternate-background-color: {CARD_TINT}; \
selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT}; outline: none; }}
QTableWidget::item, QTreeWidget::item {{ padding: 4px 8px; border: none; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {CARD}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER}; \
padding: 7px 8px; font-size: 9pt; font-weight: 700; }}
QTableCornerButton::section {{ background: {CARD}; border: none; }}

QPlainTextEdit {{ background: {CARD_TINT}; border: 1px solid {BORDER_SOFT}; border-radius: 8px; \
padding: 6px; color: {MUTED}; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #cfc8ba; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #b8b0a0; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #cfc8ba; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

QSplitter::handle {{ background: transparent; }}

QMenu {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; }}
QMenu::separator {{ height: 1px; background: {BORDER_SOFT}; margin: 6px 4px; }}
QToolTip {{ background: {INK}; color: {SIDE_BRIGHT}; border: none; padding: 6px 8px; }}
QFrame#tip {{ background: {INK}; border-radius: 8px; }}
QLabel#tiptext {{ color: {SIDE_BRIGHT}; font-size: 9pt; }}
"""


def set_tone(widget: QWidget, tone: str) -> None:
    """Switch a pill label between off / ok / warn / rec and repaint it."""
    widget.setProperty("tone", tone)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(CANVAS))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(CARD))
    pal.setColor(QPalette.AlternateBase, QColor(CARD_TINT))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(CARD))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(ACCENT_SOFT))
    pal.setColor(QPalette.HighlightedText, QColor(TEXT))
    pal.setColor(QPalette.ToolTipBase, QColor(INK))
    pal.setColor(QPalette.ToolTipText, QColor(SIDE_BRIGHT))
    pal.setColor(QPalette.PlaceholderText, QColor(MUTED))
    app.setPalette(pal)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(build_qss(_assets()))
