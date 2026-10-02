# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Main window, tray icon and settings UI."""
from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import time
import winreg
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QtMsgType,
    Slot,
    qInstallMessageHandler,
)
from PySide6.QtGui import QAction, QBrush, QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..capture import list_devices
from ..config import Config
from ..store import Store, local_time
from . import theme, verify
from .icons import app_icon, nav_icon
from .library_page import LibraryPage
from .setup_page import SetupPage as FirstRunPage
from .worker import RecorderWorker

log = logging.getLogger("mynaphone.gui")

# Win32 calls for MainWindow._check_painted, on a private handle so their signatures stay local
_user32 = ctypes.WinDLL("user32")
_user32.WindowFromPoint.argtypes = [wintypes.POINT]
_user32.WindowFromPoint.restype = wintypes.HWND
_user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetAncestor.restype = wintypes.HWND
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsIconic.argtypes = [wintypes.HWND]
GA_ROOT = 2

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "Mynaphone"
COVER = 96
COVER_MARK = 80   # the mark in a cover tile with no art: the bird spans about three-quarters of the tile

# (label, format, kbps). The first entry is the recommended default.
FORMAT_CHOICES = [
    ("AAC 256 kbps (M4A), recommended", "aac", 256),
    ("AAC 320 kbps (M4A)", "aac", 320),
    ("AAC 192 kbps (M4A)", "aac", 192),
    ("MP3 320 kbps", "mp3", 320),
    ("MP3 256 kbps", "mp3", 256),
    ("Opus 160 kbps (smallest; not for cars)", "opus", 160),
    ("Opus 128 kbps (smallest; not for cars)", "opus", 128),
    ("FLAC (lossless, about 3x larger)", "flac", 0),
]


# ----------------------------------------------------------------------------- helpers

def _fmt_ms(ms: int) -> str:
    s = max(0, int((ms or 0) // 1000))
    return f"{s // 60}:{s % 60:02d}"


def _json_list(s) -> list:
    try:
        v = json.loads(s) if isinstance(s, str) else s
        return v if isinstance(v, list) else [str(v)]
    except Exception:
        return [str(s)] if s else []


def _humanize(reason: str) -> str:
    key, _, rest = str(reason).partition(":")
    if key == "foreign_audio":
        return f"another app made sound ({rest})" if rest else "another app made sound"
    if key == "mixer_volume":
        return f"app at {rest}% in the Windows Volume Mixer"
    if key == "app_volume":
        return f"app's own volume at {rest}%"
    return {
        "paused": "paused during the song", "seek": "seeked within the song", "buffering": "playback stalled",
        "started_mid_track": "started mid-song", "length_mismatch": "length did not match",
        "too_long": "longer than a song (podcast or mix?)",
        "stalled": "took longer than the song", "cut_short": "ended early", "too_short": "too short to be a song",
        "no_duration": "no duration reported", "already_archived": "already in the archive",
        "already_archived_skipped": "already in the archive, skipped",
        "paused_by_user": "recording paused", "capture_overflow": "audio dropout",
        "device_changed": "output device changed",
        "stopped": "playback stopped", "session_gone": "player closed", "shutdown": "recorder stopped",
        "overrun": "no track change seen",
    }.get(key, key)


def _detail(reasons) -> tuple[str, str]:
    """(one-line cell text, full text for the hover tip) for a list of discard reasons.

    The first reason is the cause; the rest are what followed from it, so the cell names the
    cause and counts the rest.
    """
    words = [_humanize(x) for x in reasons if x]
    if not words:
        return "", ""
    full = ", ".join(words)
    short = words[0] if len(words) == 1 else f"{words[0]}, and {len(words) - 1} more"
    return short, full


def _rounded(pm: QPixmap, size: int, radius: int = 6) -> QPixmap:
    src = pm.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(path)
    x = (src.width() - size) // 2
    y = (src.height() - size) // 2
    p.drawPixmap(-x, -y, src)
    p.end()
    return out


class _Tip(QWidget):
    """The app's own tooltip: a rounded ink card under the control, faded in, never at the cursor."""

    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame()
        self.frame.setObjectName("tip")
        fl = QVBoxLayout(self.frame)
        fl.setContentsMargins(11, 7, 11, 8)
        self.text = QLabel()
        self.text.setObjectName("tiptext")
        self.text.setWordWrap(True)
        self.text.setMaximumWidth(340)
        fl.addWidget(self.text)
        lay.addWidget(self.frame)
        self.anim = QPropertyAnimation(self, b"windowOpacity", self)
        self.anim.setDuration(130)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)

    def show_under(self, text: str, rect_global) -> None:
        self.text.setText(text)
        self.adjustSize()
        x = rect_global.left()
        y = rect_global.bottom() + 8
        screen = QApplication.screenAt(rect_global.center()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        if x + self.width() > area.right() - 8:
            x = area.right() - 8 - self.width()
        if y + self.height() > area.bottom() - 8:
            y = rect_global.top() - 8 - self.height()
        self.move(max(area.left() + 8, x), y)
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            self.anim.stop()
            self.anim.setStartValue(0.0)
            self.anim.setEndValue(1.0)
            self.anim.start()


class _TipFilter(QObject):
    """Routes every tooltip through _Tip, and swallows them all when tooltips are switched off."""

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self.tip = _Tip()
        self.owner = None

    def _hide(self) -> None:
        self.owner = None
        if self.tip.isVisible():
            self.tip.hide()

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.ToolTip:
            if not self.win.cfg.app.show_tooltips or not isinstance(obj, QWidget):
                return True
            text, rect = "", None
            view = (obj.parent() if isinstance(obj.parent(), QAbstractItemView) and obj is obj.parent().viewport()
                    else None)
            if view is not None:
                idx = view.indexAt(event.pos())
                if idx.isValid():
                    text = idx.data(Qt.ToolTipRole) or ""
                    r = view.visualRect(idx)
                    rect = QRect(obj.mapToGlobal(r.topLeft()), r.size())
            else:
                text = obj.toolTip()
                rect = QRect(obj.mapToGlobal(obj.rect().topLeft()), obj.rect().size())
            if text and rect is not None:
                self.owner = obj
                self.tip.show_under(text, rect)
            else:
                self._hide()
            return True
        if self.owner is not None:
            if (t in (QEvent.Leave, QEvent.MouseButtonPress, QEvent.KeyPress, QEvent.Wheel, QEvent.Hide,
                      QEvent.WindowDeactivate, QEvent.FocusOut)
                    and (obj is self.owner or t in (QEvent.WindowDeactivate, QEvent.KeyPress))):
                self._hide()
            elif t == QEvent.MouseMove and obj is self.owner and isinstance(obj.parent(), QAbstractItemView):
                # moving to another row in a list: let the next ToolTip event re-anchor the tip
                idx = obj.parent().indexAt(event.pos())
                if not idx.isValid() or (idx.data(Qt.ToolTipRole) or "") != self.tip.text.text():
                    self._hide()
        return False


class _NoWheel(QObject):
    """Stops spin boxes and dropdowns from changing value when the mouse wheel scrolls the page."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and not obj.hasFocus():
            event.ignore()
            return True
        return False


def no_wheel(widget: QWidget) -> QWidget:
    widget.setFocusPolicy(Qt.StrongFocus)
    f = _NoWheel(widget)
    widget.installEventFilter(f)
    return widget


def card(parent=None) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame(parent)
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(10)
    return f, lay


def label(text: str, name: str | None = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


class _OneLine(QLabel):
    """A label that stays on one line: text too long for it ends in an ellipsis, with all of it in the tooltip."""

    def __init__(self, text: str, name: str):
        super().__init__(text)
        self.setObjectName(name)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, event) -> None:
        rect = self.contentsRect()
        shown = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, rect.width())
        self.setToolTip(self.text() if shown != self.text() else "")
        p = QPainter(self)
        self.style().drawItemText(p, rect, int(self.alignment()), self.palette(), self.isEnabled(), shown,
                                  self.foregroundRole())


def verdict_colour(verdict: str) -> QColor | None:
    return {"keep": QColor(theme.GREEN), "discard": QColor(theme.RED), "skip": QColor(theme.MUTED),
            "filed": QColor(theme.ACCENT)}.get(verdict)


VERDICT_LABELS = {"keep": "Kept", "discard": "Discarded", "skip": "Skipped", "filed": "Filed"}


# ----------------------------------------------------------------------------- pages

class StatusPage(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # now-playing card: a row (cover + text) sized below for its busiest state, then the transport row
        self.card, c = card()
        c.setSpacing(12)
        row_box = QWidget()
        top = QHBoxLayout(row_box)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(18)
        self.cover = QLabel()
        self.cover.setObjectName("cover")
        self.cover.setFixedSize(COVER, COVER)
        self.cover.setAlignment(Qt.AlignCenter)
        top.addWidget(self.cover, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setContentsMargins(0, 2, 0, 2)
        text.setSpacing(4)
        self.state = label("Stopped", "pill")
        self.state.setProperty("tone", "off")
        state_row = QHBoxLayout()
        state_row.setContentsMargins(0, 0, 0, 0)
        state_row.addWidget(self.state)
        state_row.addStretch(1)
        self.title = _OneLine("", "title")
        self.sub = _OneLine("Press Start to begin listening for music.", "muted")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setFixedHeight(4)
        self.progress.hide()
        self.timing = label("", "small")
        text.addLayout(state_row)
        text.addWidget(self.title)
        text.addWidget(self.sub)
        text.addStretch(1)
        text.addWidget(self.progress)
        text.addWidget(self.timing)
        top.addLayout(text, 1)
        c.addWidget(row_box)
        self._row, self._text_lay = row_box, text
        row_box.setMinimumHeight(COVER)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.btn_start = QPushButton("Start")
        self.btn_start.setObjectName("primary")
        self.btn_start.setMinimumWidth(104)
        self.btn_start.clicked.connect(win.toggle_running)
        self.btn_start.setToolTip("Start or stop the recorder. "
                                  "While it runs, every complete song from your sources is captured.")
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setCheckable(True)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setMinimumWidth(90)
        self.btn_pause.toggled.connect(win.set_paused)
        self.btn_pause.setToolTip("Keep listening but start no new recordings until you resume.")
        self.device = label("", "small")
        self.bridge = label("", "small")
        self.chain = label("", "small")
        self.chain.setWordWrap(True)
        bottom.addWidget(self.btn_start)
        bottom.addWidget(self.btn_pause)
        bottom.addSpacing(8)
        bottom.addWidget(self.chain, 1)
        c.addLayout(bottom)
        # harvest mode: a labeled switch on its own line, since it changes what Spotify plays
        self.btn_harvest = QCheckBox("Skip songs already in the library, "
                                     "so an unattended playlist records only new ones")
        self.btn_harvest.setChecked(win.cfg.rules.harvest_mode)
        self.btn_harvest.setToolTip("Harvest mode. "
                                    "When an archived song starts, Spotify is told to skip to the next one. "
                                    "Turn it off while you are listening yourself.")
        self.btn_harvest.toggled.connect(win.set_harvest)
        c.addWidget(self.btn_harvest)
        lay.addWidget(self.card)

        # counts
        row = QHBoxLayout()
        row.setSpacing(12)
        self.tiles = {}
        for key, title in (("inbox", "Waiting in the inbox"), ("library", "In the library"),
                           ("discarded", "Discarded"), ("skipped", "Skipped")):
            f, cl = card()
            cl.setContentsMargins(18, 14, 18, 14)
            cl.setSpacing(2)
            v = label("0", "stat")
            t = label(title.upper(), "eyebrow")
            cl.addWidget(t)
            cl.addWidget(v)
            self.tiles[key] = v
            row.addWidget(f, 1)
        lay.addLayout(row)

        # recent takes
        f, cl = card()
        head = QHBoxLayout()
        head.addWidget(label("Recent", "h2"))
        head.addStretch(1)
        more = QPushButton("See all activity")
        more.setToolTip("Open the Activity page: every kept, discarded and filed take, with reasons, "
                        "plus the live log.")
        more.clicked.connect(lambda: win.nav.setCurrentRow(1))
        head.addWidget(more)
        cl.addLayout(head)
        self.recent = QTableWidget(0, 3)
        self.recent.setHorizontalHeaderLabels(["Time", "Song", "Result"])
        hh = self.recent.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.recent.setWordWrap(False)
        self.recent.verticalHeader().hide()
        self.recent.setEditTriggers(QTableWidget.NoEditTriggers)
        self.recent.setSelectionMode(QTableWidget.NoSelection)
        self.recent.setFocusPolicy(Qt.NoFocus)
        self.recent.setShowGrid(False)
        self.recent.setAlternatingRowColors(True)
        self.recent.setFixedHeight(6 * 30 + 32)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        cl.addWidget(self.recent)
        lay.addWidget(f)
        lay.addStretch(1)
        self.set_cover(None)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._size_now_playing()

    def _size_now_playing(self) -> None:
        """Give the now-playing row the height of its busiest state (title, progress bar and timing all
        showing), measured once the theme's fonts apply, so the title is never squeezed and the card keeps
        its height when a song starts."""
        saved = (self.title.text(), self.sub.text(), self.timing.text(), self.progress.isHidden())
        self.title.setText("Ág")
        self.sub.setText("Ág")
        self.timing.setText("0:00 / 0:00")
        self.progress.show()
        self._text_lay.invalidate()
        need = self._text_lay.sizeHint().height()
        self.title.setText(saved[0])
        self.sub.setText(saved[1])
        self.timing.setText(saved[2])
        self.progress.setHidden(saved[3])
        self._row.setMinimumHeight(max(COVER, need))

    def set_cover(self, data: bytes | None, state: str = "idle") -> None:
        """The song's cover art, or the mark in the recorder's state (eye red while recording) without one."""
        if data:
            pm = QPixmap()
            if pm.loadFromData(data):
                self.cover.setPixmap(_rounded(pm, COVER))
                return
        self.cover.setPixmap(app_icon(state).pixmap(COVER_MARK, COVER_MARK))

    def set_recent(self, rows: list[tuple[str, str, str]]) -> None:
        self.recent.setRowCount(0)
        for when, song, verdict in rows[:6]:
            r = self.recent.rowCount()
            self.recent.insertRow(r)
            items = [QTableWidgetItem(when), QTableWidgetItem(song), QTableWidgetItem(
                {"keep": "Kept", "discard": "Discarded", "skip": "Skipped"}.get(verdict, verdict))]
            col = verdict_colour(verdict)
            if col:
                items[2].setForeground(QBrush(col))
            items[1].setToolTip(song)
            for i, it in enumerate(items):
                self.recent.setItem(r, i, it)


class ActivityPage(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)

        f, cl = card()
        head = QHBoxLayout()
        head.addWidget(label("Takes", "h2"))
        head.addStretch(1)
        self.summary = label("", "small")
        head.addWidget(self.summary)
        cl.addLayout(head)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Time", "Song", "Result", "Detail"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setMaximumSectionSize(300)      # a long YouTube title must not crowd out the reason
        self.table.setWordWrap(False)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        cl.addWidget(self.table, 1)
        split.addWidget(f)

        f2, cl2 = card()
        cl2.addWidget(label("Log", "h2"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(800)
        font = self.log.font()
        font.setFamily("Cascadia Mono")
        font.setPointSize(9)
        self.log.setFont(font)
        cl2.addWidget(self.log, 1)
        split.addWidget(f2)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)

    def add_row(self, when: str, song: str, verdict: str, detail) -> None:
        """`detail` is a string, or a (cell text, hover text) pair for a discard with several reasons."""
        short, full = detail if isinstance(detail, tuple) else (detail, detail)
        self.table.insertRow(0)
        items = [QTableWidgetItem(when), QTableWidgetItem(song),
                 QTableWidgetItem(VERDICT_LABELS.get(verdict, verdict)), QTableWidgetItem(short)]
        col = verdict_colour(verdict)
        if col:
            items[2].setForeground(QBrush(col))
        items[1].setToolTip(song)
        items[3].setToolTip(full)
        for i, it in enumerate(items):
            self.table.setItem(0, i, it)
        while self.table.rowCount() > 300:
            self.table.removeRow(self.table.rowCount() - 1)


class SettingsPage(QScrollArea):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(12)
        cfg = win.cfg

        # folders
        f, c = card()
        c.addWidget(label("Folders", "h2"))
        form = self._form()
        self.ed_inbox = self._path_field(cfg.paths.inbox_dir)
        self.ed_library = self._path_field(cfg.paths.library_dir)
        self._row(form, "Inbox", self.ed_inbox,
                  "Complete, verified takes wait here as FLAC until they are tagged and filed.")
        self._row(form, "Library", self.ed_library, "The organized collection: Soundtracks and Artists folders.")
        c.addLayout(form)
        self.space = label("", "muted", wrap=True)
        c.addWidget(self.space)
        lay.addWidget(f)
        self.ed_library.edit.textChanged.connect(lambda _t: self.update_space())
        QTimer.singleShot(0, self.update_space)

        # capture
        f, c = card()
        c.addWidget(label("Capture", "h2"))
        form = self._form()
        self.cb_mode = no_wheel(QComboBox())
        self.cb_mode.addItems(["Per app (only the music app's own sound)", "Whole output device"])
        self.cb_mode.setMinimumWidth(360)
        self.cb_mode.setCurrentIndex(0 if cfg.capture.mode == "process" else 1)
        self.cb_mode.setToolTip("Per app records only the music app's own sound. "
                                "Whole device records everything the PC plays.")
        self._row(form, "Capture method", self.cb_mode,
                  "Per app records just Spotify's audio, so notifications and other apps can never end up in a take. "
                  "Whole device is the older method and needs the other-apps rule below.")
        self.ck_youtube = QCheckBox("Also record YouTube and YouTube Music playing in Chrome or Edge")
        browsers = {"chrome.exe", "msedge.exe"}
        self.ck_youtube.setChecked(any(s.lower() in browsers for s in cfg.rules.sources))
        box = QWidget()
        bv = QVBoxLayout(box)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(2)
        bv.addWidget(self.ck_youtube)
        h = label("Needs the Mynaphone browser extension "
                  "(browser-extension folder, loaded via chrome://extensions with Developer mode). "
                  "Only music videos and YouTube Music tracks are recorded; other videos are ignored.",
                  "small", wrap=True)
        h.setContentsMargins(24, 0, 0, 0)
        bv.addWidget(h)
        form.addRow("", box)
        self.cb_device = no_wheel(QComboBox())
        self.cb_device.setMinimumWidth(360)
        self.cb_device.setToolTip("Device mode only: which output device to record. Ignored in per-app mode.")
        self._fill_devices()
        self.cb_device.setEnabled(cfg.capture.mode != "process")
        self.cb_mode.currentIndexChanged.connect(lambda i: self.cb_device.setEnabled(i == 1))
        self.cb_depth = no_wheel(QComboBox())
        self.cb_depth.addItems(["16-bit", "24-bit"])
        self.cb_depth.setFixedWidth(140)
        self.cb_depth.setCurrentIndex(1 if cfg.capture.bit_depth == 24 else 0)
        self.cb_depth.setToolTip("16-bit for Spotify Free, Premium and YouTube. "
                                 "24-bit only for Spotify's lossless tier.")
        self.cb_format = no_wheel(QComboBox())
        self.cb_format.setFixedWidth(300)
        self.cb_format.setToolTip("Format of the files in your library. AAC 256 plays in cars and on phones. "
                                  "Applies to new songs.")
        for text, fmt, kbps in FORMAT_CHOICES:
            self.cb_format.addItem(text, (fmt, kbps))
        idx = next((i for i, (_, f, k) in enumerate(FORMAT_CHOICES)
                    if f == cfg.library.format and (f == "flac" or k == cfg.library.bitrate)), None)
        if idx is None:
            idx = next((i for i, (_, f, _k) in enumerate(FORMAT_CHOICES) if f == cfg.library.format), 0)
        self.cb_format.setCurrentIndex(idx)
        self._row(form, "Capture device", self.cb_device,
                  "Usually the Windows default output. "
                  "Pick \"CABLE Output\" if you route Spotify through VB-CABLE for a bit-exact lossless chain.")
        self._row(form, "Bit depth", self.cb_depth,
                  "16-bit is right for Spotify Free and Premium and for YouTube. "
                  "Choose 24-bit only for Spotify Lossless.")
        self._row(form, "Library format", self.cb_format,
                  "AAC 256 is the safe choice: cars, iPhones and Android all play it, about 9 MB a song. "
                  "MP3 plays anywhere at a larger size. Opus is the smallest but most cars cannot play it. "
                  "Lossless-tier captures always stay FLAC. Changing this affects new songs only.")
        self.cb_format.currentIndexChanged.connect(lambda _i: self.update_space())
        self.cb_depth.currentIndexChanged.connect(lambda _i: self.update_space())
        c.addLayout(form)
        lay.addWidget(f)

        # rules
        f, c = card()
        c.addWidget(label("What counts as a complete song", "h2"))
        form = self._form()
        self.sp_min = no_wheel(QSpinBox())
        self.sp_min.setRange(10, 600)
        self.sp_min.setSuffix(" seconds")
        self.sp_min.setFixedWidth(140)
        self.sp_min.setButtonSymbols(QSpinBox.NoButtons)
        self.sp_min.setValue(int(cfg.rules.min_duration_seconds))
        self.sp_min.setToolTip("Anything shorter than this is never recorded.")
        self._row(form, "Minimum length", self.sp_min, "Anything shorter is ignored: ads, jingles, stray clips.")
        self.ck_pause = self._check(form, "Discard a take if playback was paused", cfg.rules.discard_on_pause,
                                    "A pause leaves a gap in the recording, so the take can't be trusted.")
        self.ck_seek = self._check(form, "Discard a take if you seeked within the song", cfg.rules.discard_on_seek,
                                   "Jumping forward or back means part of the song was never captured.")
        self.ck_foreign = self._check(form, "Discard a take if any other app made any sound",
                                      cfg.rules.discard_on_foreign_audio,
                                      "A notification chime, a browser tab, a game: "
                                      "anything else that plays while a song records gets mixed in, "
                                      "so the take is rejected and the app is named in the reason.")
        self.ck_upgrade = self._check(form, "Re-record archived songs when they play at a higher quality tier",
                                      cfg.quality.upgrade_on_higher_tier,
                                      "After a Spotify upgrade the collection refreshes itself as you listen; "
                                      "the older copy is replaced.")
        self.ck_harvest = self._check(form, "Skip songs already in the library (harvest mode)", cfg.rules.harvest_mode,
                                      "For unattended runs. "
                                      "When an archived song starts, Spotify is told to skip to the next one, "
                                      "so a long queue records only what's new. "
                                      "Turn it off while you listen yourself, or songs you own will jump away. "
                                      "Also on the Status page and in the tray menu.")
        self.sp_keep = no_wheel(QSpinBox())
        self.sp_keep.setRange(0, 60)
        self.sp_keep.setSuffix(" days")
        self.sp_keep.setFixedWidth(140)
        self.sp_keep.setButtonSymbols(QSpinBox.NoButtons)
        self.sp_keep.setValue(cfg.rules.keep_discards_days)
        self.sp_keep.setToolTip("How long rejected recordings stay in the discard folder before they are deleted.")
        self._row(form, "Keep rejected takes", self.sp_keep,
                  "Rejected recordings stay in the discard folder this long, with a note on why, then are deleted.")
        c.addLayout(form)
        lay.addWidget(f)

        # app
        f, c = card()
        c.addWidget(label("Application", "h2"))
        form = self._form()
        self.ck_autostart = self._check(form, "Start recording when the app opens", cfg.app.autostart_recording)
        self.ck_tray = self._check(form, "Closing the window keeps it running in the tray", cfg.app.close_to_tray)
        self.ck_minimized = self._check(form, "Open minimized to the tray", cfg.app.start_minimized)
        self.ck_login = self._check(form, "Start with Windows", win.login_item_present(),
                                    "Adds an entry to your user's startup list. Nothing is installed system-wide.")
        self.ck_tooltips = self._check(form, "Show tooltips when the mouse rests on a control", cfg.app.show_tooltips,
                                       "Short explanations like this one, for every button and setting.")
        c.addLayout(form)
        lay.addWidget(f)

        row = QHBoxLayout()
        self.saved = label("", "small")
        row.addWidget(self.saved)
        row.addStretch(1)
        btn = QPushButton("Save settings")
        btn.setObjectName("primary")
        btn.clicked.connect(win.save_settings)
        btn.setToolTip("Write these settings to config.toml. Capture settings apply the next time you press Start.")
        row.addWidget(btn)
        lay.addLayout(row)
        lay.addStretch(1)
        self.setWidget(body)

    def update_space(self) -> None:
        from .. import storage
        try:
            fmt, kbps = self.cb_format.currentData() or ("aac", 256)
            depth = 24 if self.cb_depth.currentIndex() == 1 else 16
            est = storage.estimate(Path(self.ed_library.edit.text() or "."), fmt, kbps,
                                   self.win.cfg.rules.keep_discards_days, depth)
            self.space.setText(storage.describe(est))
        except Exception as e:
            self.space.setText(f"Could not estimate free space: {e}")

    @staticmethod
    def _form() -> QFormLayout:
        form = QFormLayout()
        form.setContentsMargins(0, 4, 0, 0)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(14)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        return form

    @staticmethod
    def _row(form: QFormLayout, name: str, widget: QWidget, help_text: str | None = None) -> None:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        v.addWidget(widget, 0, Qt.AlignLeft if widget.maximumWidth() < 10000 else Qt.Alignment())
        if help_text:
            v.addWidget(label(help_text, "small", wrap=True))
        lbl = QLabel(name)
        lbl.setMinimumWidth(130)
        lbl.setContentsMargins(0, 6, 0, 0)
        form.addRow(lbl, box)

    @staticmethod
    def _check(form: QFormLayout, text: str, checked: bool, help_text: str | None = None) -> QCheckBox:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        cb = QCheckBox(text)
        cb.setChecked(checked)
        v.addWidget(cb)
        if help_text:
            h = label(help_text, "small", wrap=True)
            h.setContentsMargins(24, 0, 0, 0)
            v.addWidget(h)
        form.addRow("", box)
        return cb

    def _path_field(self, initial: Path) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        edit = QLineEdit(str(initial))
        btn = QToolButton()
        btn.setText("Browse")
        btn.setMinimumWidth(70)

        def pick():
            d = QFileDialog.getExistingDirectory(self, "Choose folder", edit.text())
            if d:
                edit.setText(d.replace("/", "\\"))
        btn.clicked.connect(pick)
        lay.addWidget(edit, 1)
        lay.addWidget(btn)
        box.edit = edit
        return box

    def _fill_devices(self) -> None:
        self.cb_device.clear()
        self.cb_device.addItem("Windows default output", "default")
        try:
            for line in list_devices():
                if line.startswith("loopback: "):
                    name = line[len("loopback: "):].split("  (")[0].replace(" [Loopback]", "")
                    self.cb_device.addItem(name, name)
                elif line.startswith("input: "):
                    name = line[len("input: "):].split("  (")[0]
                    self.cb_device.addItem(f"{name} (input)", name)
        except Exception:
            pass
        idx = self.cb_device.findData(self.win.cfg.capture.device)
        self.cb_device.setCurrentIndex(idx if idx >= 0 else 0)


class RowList(QWidget):
    """Rows of (name, status, wrapping detail) with hairline separators; wraps where tables elide."""

    def __init__(self, columns: tuple[int, int] = (170, 70)):
        super().__init__()
        self.columns = columns
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(0)
        self.grid.setColumnMinimumWidth(0, columns[0])
        self.grid.setColumnMinimumWidth(1, columns[1])
        if columns[1] == 0:
            self.grid.setColumnStretch(0, 1)
            self.grid.setColumnStretch(2, 1)
        else:
            self.grid.setColumnStretch(2, 1)
        self._n = 0

    def clear(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._n = 0

    def add(self, name: str, status: str, detail: str, colour: str | None = None) -> None:
        r = self._n * 2
        if self._n:
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setStyleSheet(f"color: {theme.BORDER_SOFT};")
            self.grid.addWidget(line, r - 1, 0, 1, 3)
        n = QLabel(name)
        n.setWordWrap(True)
        n.setContentsMargins(0, 8, 0, 8)
        s = QLabel(status)
        s.setContentsMargins(0, 8, 0, 8)
        if colour:
            s.setStyleSheet(f"color: {colour}; font-weight: 600;")
        d = label(detail, "muted", wrap=True)
        d.setContentsMargins(0, 8, 0, 8)
        for col, w in enumerate((n, s, d)):
            w.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            self.grid.addWidget(w, r, col)
        self._n += 1

    def finish(self) -> None:
        self.grid.setRowStretch(self._n * 2, 1)


class SetupPage(QScrollArea):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(12)

        f, c = card()
        head = QHBoxLayout()
        head.addWidget(label("Automatic checks", "h2"))
        head.addStretch(1)
        self.btn = QPushButton("Run checks")
        self.btn.setObjectName("primary")
        self.btn.clicked.connect(self.run)
        self.btn.setToolTip("Check the capture device, audio processing, Spotify, the bridges, "
                            "volume sliders and free disk space.")
        head.addWidget(self.btn)
        c.addLayout(head)
        c.addWidget(label("Looks at this PC: the capture device, audio processing, Spotify, "
                          "the Spicetify bridge and free disk space.", "muted", wrap=True))
        self.rows = RowList()
        self.rows.add("", "", "Press Run checks.")
        c.addWidget(self.rows)
        lay.addWidget(f)

        f2, c2 = card()
        c2.addWidget(label("Confirm once in Spotify", "h2"))
        c2.addWidget(label("These can't be read from outside the app. Open Spotify's settings and check them by eye; "
                           "they only need to be right once.", "muted", wrap=True))
        manual = RowList(columns=(170, 0))
        for name, want in verify.MANUAL_CHECKS:
            manual.add(name, "", want)
        c2.addWidget(manual)
        lay.addWidget(f2)
        lay.addStretch(1)
        self.setWidget(body)
        self.checked = False

    @Slot()
    def run(self) -> None:
        self.btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            results = verify.run_all(self.win.cfg, self.win.bridge_connected)
        finally:
            QApplication.restoreOverrideCursor()
            self.btn.setEnabled(True)
        labels = {verify.OK: "OK", verify.WARN: "Check", verify.FAIL: "Problem", verify.INFO: "Info"}
        colours = {verify.FAIL: theme.RED, verify.WARN: theme.AMBER, verify.OK: theme.GREEN}
        self.rows.clear()
        for r in results:
            self.rows.add(r.name, labels[r.status], r.detail, colours.get(r.status))
        self.checked = True


# ----------------------------------------------------------------------------- window

class MainWindow(QMainWindow):
    def __init__(self, config_path: Path, start_minimized: bool = False):
        super().__init__()
        self.config_path = Path(config_path)
        self.cfg = Config.load(self.config_path)
        self.worker: RecorderWorker | None = None
        self.bridge_connected: bool | None = None
        self.recording_since: float | None = None
        self.recording_song: tuple[str, str] | None = None     # (artist, title) of the take on screen
        self.recording_expected_ms = 0
        self._quitting = False
        self._tray_hint_shown = False

        self.setWindowTitle("Mynaphone")
        self.setWindowIcon(app_icon("stopped", tile=True))
        self.resize(1040, 680)
        self.setMinimumSize(860, 560)

        canvas = QWidget()
        canvas.setObjectName("canvas")
        root = QHBoxLayout(canvas)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # sidebar
        side = self.sidebar = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(208)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 14, 0, 14)
        sl.setSpacing(8)
        # no brand row: the window's own title bar already shows the mark and the name
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setIconSize(QSize(18, 18))
        nav_tips = {
            "Status": "What is recording right now, counts, and the last few takes.",
            "Activity": "Every take with its verdict and reason, and the live log.",
            "Library": "Your filed songs, what each one is still missing, and an editor to fix details by hand.",
            "Settings": "Folders, capture, format, rules and app behavior.",
            "Setup check": "Automatic checks of this PC plus the Spotify settings to confirm by eye.",
            "Set up": "The first-run steps: tools, AcoustID key, library folder, bridges.",
        }
        for text in ("Status", "Activity", "Library", "Settings", "Setup check", "Set up"):
            item = QListWidgetItem(nav_icon(text), text, self.nav)
            item.setToolTip(nav_tips[text])
        self.nav.setCurrentRow(0)
        self.nav.setFixedHeight(6 * 40 + 8)
        sl.addWidget(self.nav)
        sl.addStretch(1)
        self.side_state = label("Stopped", "sidestate")
        self.side_state.setContentsMargins(18, 0, 0, 0)
        sl.addWidget(self.side_state)
        self.side_harvest = label("Harvest mode on" if self.cfg.rules.harvest_mode else "", "small")
        self.side_harvest.setContentsMargins(18, 0, 0, 0)
        sl.addWidget(self.side_harvest)
        ver = label(f"version {__version__}", "small")
        ver.setContentsMargins(18, 0, 0, 0)
        sl.addWidget(ver)
        root.addWidget(side)

        # pages
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(26, 20, 26, 20)
        cl.setSpacing(6)
        self.page_title = label("Status", "h1")
        self.page_sub = label("", "muted")
        self.page_sub.setWordWrap(True)
        cl.addWidget(self.page_title)
        cl.addWidget(self.page_sub)
        cl.addSpacing(8)
        self._page_heads = {
            0: ("Status", "What the recorder is doing right now, and the last few takes."),
            1: ("Activity", "Every take with its verdict and the reason, plus the live log."),
            2: ("Library", "Your filed songs, what each one is still missing, and the editor."),
            3: ("Settings", "Folders, capture, format, rules and how the app behaves."),
            4: ("Setup check", "Automatic checks of this PC, plus the Spotify settings to confirm by eye."),
            5: ("Set up", "Four short steps. Each shows whether it is done, and you can come back here any time."),
        }
        self.pages = QStackedWidget()
        self.status = StatusPage(self)
        self.activity = ActivityPage(self)
        self.library = LibraryPage(self)
        self.settings = SettingsPage(self)
        self.setup = SetupPage(self)
        self.firstrun = FirstRunPage(self)
        for p in (self.status, self.activity, self.library, self.settings, self.setup, self.firstrun):
            self.pages.addWidget(p)
        cl.addWidget(self.pages)
        root.addWidget(content, 1)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.currentRowChanged.connect(self._set_page_head)
        self._set_page_head(self.nav.currentRow())
        self.setCentralWidget(canvas)

        self._build_tray()
        self._tip_filter = _TipFilter(self, self)
        QApplication.instance().installEventFilter(self._tip_filter)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self._load_recent()
        self._refresh_state_labels()
        self._setup_dev_shots()
        first_run = not self.firstrun.complete
        if first_run:
            self.nav.setCurrentRow(5)
        if self.cfg.app.autostart_recording and not first_run:
            QTimer.singleShot(300, self.start_recorder)
        self._blank_heals = 0
        if start_minimized and not first_run:
            QTimer.singleShot(0, self.hide)
        else:
            self.show()
            QTimer.singleShot(600, self._check_painted)

    def _set_page_head(self, i: int) -> None:
        title, sub = self._page_heads.get(i, ("", ""))
        self.page_title.setText(title)
        self.page_sub.setText(sub)

    def _setup_dev_shots(self) -> None:
        """Development aid: with MYNAPHONE_SHOT_DIR set, save an image of each page every few seconds."""
        shot_dir = os.environ.get("MYNAPHONE_SHOT_DIR")
        if not shot_dir:
            return
        Path(shot_dir).mkdir(parents=True, exist_ok=True)
        self._shot_i = 0

        plan = [(0, ""), (1, ""), (2, ""), (3, ""), (3, "b"), (4, ""), (5, "")]   # page index, suffix

        def shoot():
            i, suffix = plan[self._shot_i % len(plan)]
            self.nav.setCurrentRow(i)
            if i == 4 and not self.setup.checked:
                self.setup.run()
            if i == 2 and self.library.table.rowCount() and not self.library.table.selectedItems():
                self.library.table.selectRow(0)
            if i == 3:
                bar = self.settings.verticalScrollBar()
                bar.setValue(bar.maximum() if suffix else 0)
            QTimer.singleShot(400, lambda: self.grab().save(str(Path(shot_dir) / f"page{i}{suffix}.png")))
            self._shot_i += 1
        t = QTimer(self)
        t.setInterval(3000)
        t.timeout.connect(shoot)
        t.start()
        self._shot_timer = t

    # ------------------------------------------------------------------ data

    def _load_recent(self) -> None:
        try:
            st = Store(self.cfg.paths.db_path)
            rows = st.recent_takes(100)
            self.activity.table.setRowCount(0)
            compact = []
            for r in reversed(rows):
                detail = ""
                if r["verdict"] == "keep":
                    detail = f"{_fmt_ms(r['captured_ms'])} of {_fmt_ms(r['expected_ms'])}, {r['quality_tier'] or ''}"
                elif r["reasons"]:
                    detail = _detail(_json_list(r["reasons"]))
                when = local_time(r["started_at"])
                song = f"{r['artist']} - {r['title']}"
                self.activity.add_row(when, song, r["verdict"], detail)
                compact.insert(0, (when, song, r["verdict"]))
            self.status.set_recent(compact)
            s = st.summary()
            self.status.tiles["inbox"].setText(str(s["tracks_inbox"]))
            self.status.tiles["library"].setText(str(s["tracks_library"]))
            self.status.tiles["discarded"].setText(str(s["takes_discarded"]))
            self.status.tiles["skipped"].setText(str(s["takes_skipped"]))
            self.activity.summary.setText(f"{s['tracks_inbox']} in the inbox, {s['tracks_library']} in the library")
        except Exception as e:
            self.activity.summary.setText(f"could not read the index: {e}")

    # ------------------------------------------------------------------ settings

    @Slot()
    def save_settings(self) -> None:
        s = self.settings
        c = self.cfg
        c.paths.inbox_dir = Path(s.ed_inbox.edit.text())
        c.paths.library_dir = Path(s.ed_library.edit.text())
        c.capture.mode = "process" if s.cb_mode.currentIndex() == 0 else "device"
        c.capture.device = s.cb_device.currentData() or "default"
        browsers = ["chrome.exe", "msedge.exe"]
        base = [x for x in c.rules.sources if x.lower() not in browsers]
        c.rules.sources = base + (browsers if s.ck_youtube.isChecked() else [])
        c.capture.bit_depth = 24 if s.cb_depth.currentIndex() == 1 else 16
        fmt, kbps = s.cb_format.currentData() or ("aac", 256)
        c.library.format = fmt
        c.library.aac_bitrate = kbps
        c.rules.min_duration_seconds = float(s.sp_min.value())
        c.rules.discard_on_pause = s.ck_pause.isChecked()
        c.rules.discard_on_seek = s.ck_seek.isChecked()
        c.rules.discard_on_foreign_audio = s.ck_foreign.isChecked()
        c.rules.harvest_mode = s.ck_harvest.isChecked()
        c.rules.keep_discards_days = s.sp_keep.value()
        if self.status.btn_harvest.isChecked() != c.rules.harvest_mode:
            self.status.btn_harvest.setChecked(c.rules.harvest_mode)
        c.quality.upgrade_on_higher_tier = s.ck_upgrade.isChecked()
        c.app.autostart_recording = s.ck_autostart.isChecked()
        c.app.close_to_tray = s.ck_tray.isChecked()
        c.app.start_minimized = s.ck_minimized.isChecked()
        c.app.show_tooltips = s.ck_tooltips.isChecked()
        c.save()
        self._set_login_item(s.ck_login.isChecked())
        for d in (c.paths.inbox_dir, c.paths.library_dir):
            d.mkdir(parents=True, exist_ok=True)
        if self.worker is not None and self.worker.isRunning():
            s.saved.setText("Saved. Capture settings take effect the next time you press Start.")
        else:
            s.saved.setText("Saved.")

    def _login_command(self) -> str:
        pyw = Path(sys.executable).with_name("pythonw.exe")
        exe = pyw if pyw.exists() else Path(sys.executable)
        return f'"{exe}" -m mynaphone gui --config "{self.config_path}" --minimized'

    def login_item_present(self) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, RUN_NAME)
                return True
        except OSError:
            return False

    def _set_login_item(self, enabled: bool) -> None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                if enabled:
                    winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, self._login_command())
                else:
                    try:
                        winreg.DeleteValue(k, RUN_NAME)
                    except OSError:
                        pass
        except OSError as e:
            QMessageBox.warning(self, "Start with Windows", f"Could not update the startup entry: {e}")

    # ------------------------------------------------------------------ recorder control

    @Slot()
    def toggle_running(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.stop_recorder()
        else:
            self.start_recorder()

    def start_recorder(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        self.cfg = Config.load(self.config_path)
        self.worker = RecorderWorker(str(self.config_path), self)
        self.worker.event.connect(self.on_event)
        self.worker.log.connect(self.activity.log.appendPlainText)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.on_finished)
        self.worker.set_paused(self.status.btn_pause.isChecked())
        self.worker.set_harvest(self.status.btn_harvest.isChecked())
        self.worker.start()
        self.status.btn_start.setText("Stop")
        self.status.btn_start.setObjectName("danger")
        self.status.btn_start.style().unpolish(self.status.btn_start)
        self.status.btn_start.style().polish(self.status.btn_start)
        self.status.btn_pause.setEnabled(True)
        self.status.state.setText("Starting")
        theme.set_tone(self.status.state, "warn")
        self.status.sub.setText("Opening the capture device and hooking media sessions.")
        self._set_icon("idle")

    def stop_recorder(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.status.btn_start.setEnabled(False)
            self.status.state.setText("Stopping")
            theme.set_tone(self.status.state, "warn")

    @Slot(bool)
    def set_harvest(self, on: bool) -> None:
        if self.worker is not None:
            self.worker.set_harvest(on)
        if self.act_harvest.isChecked() != on:
            self.act_harvest.setChecked(on)
        self.cfg.rules.harvest_mode = on
        try:
            self.cfg.save()
        except Exception:
            pass
        self.settings.ck_harvest.setChecked(on)
        self.side_harvest.setText("Harvest mode on" if on else "")

    @Slot(bool)
    def set_paused(self, paused: bool) -> None:
        self.status.btn_pause.setText("Resume" if paused else "Pause")
        if self.worker is not None:
            self.worker.set_paused(paused)
        if self.act_pause.isChecked() != paused:
            self.act_pause.setChecked(paused)
        self._refresh_state_labels()

    @Slot(dict)
    def on_event(self, ev: dict) -> None:
        kind = ev.get("kind")
        st = self.status
        if kind == "started":
            name = str(ev.get("device", "")).replace(" [Loopback]", "")
            rate = int(ev.get("rate") or 0)
            st.device.setText(f"{name} · {rate / 1000:g} kHz" if rate else name)
            self._refresh_chain()
        elif kind == "bridge":
            self.bridge_connected = bool(ev.get("connected"))
            st.bridge.setText("Spotify bridge connected" if self.bridge_connected else "Spotify bridge not connected")
            self._refresh_chain()
        elif kind == "recording":
            self.recording_since = float(ev.get("t_event") or time.monotonic())
            self.recording_expected_ms = int(ev.get("expected_ms") or 0)
            self.recording_song = (ev.get("artist", ""), ev.get("title", ""))
            st.state.setText("Recording")
            theme.set_tone(st.state, "rec")
            st.title.setText(ev.get("title", ""))
            album = ev.get("album") or ""
            st.sub.setText(f"{ev.get('artist', '')}" + (f"  ·  {album}" if album else ""))
            st.progress.setValue(0)
            st.progress.show()
            st.set_cover(None, "recording")
            self.side_state.setText("Recording")
            self._set_icon("recording")
            self.tray.setToolTip(f"Mynaphone: recording {ev.get('artist')} - {ev.get('title')}")
        elif kind == "cover":
            if ev.get("title") == st.title.text():
                st.set_cover(ev.get("data"), "recording")
        elif kind in ("kept", "discarded", "skipped"):
            # the next song starts recording before this one is written out, so this verdict can
            # arrive while the next song is on screen; only the on-screen song's verdict ends its display
            if self.recording_song == (ev.get("artist", ""), ev.get("title", "")):
                self.recording_since = None
                self.recording_song = None
                st.progress.setValue(0)
                st.progress.hide()
                st.timing.setText("")
            when = time.strftime("%H:%M")
            song = f"{ev.get('artist')} - {ev.get('title')}"
            if kind == "kept":
                verdict, detail = "keep", (f"{_fmt_ms(ev.get('captured_ms', 0))} of "
                                           f"{_fmt_ms(ev.get('expected_ms', 0))}, {ev.get('tier', '')}")
            elif kind == "discarded":
                verdict, detail = "discard", _detail(ev.get("reasons", []))
            else:
                verdict, detail = "skip", _humanize(ev.get("reason", ""))
            self.activity.add_row(when, song, verdict, detail)
            rows = [(when, song, verdict)]
            for r in range(min(5, st.recent.rowCount())):
                rows.append((st.recent.item(r, 0).text(), st.recent.item(r, 1).text(),
                             {"Kept": "keep", "Discarded": "discard", "Skipped": "skip"}.get(
                                 st.recent.item(r, 2).text(), "")))
            st.set_recent(rows)
            key = {"keep": "inbox", "discard": "discarded", "skip": "skipped"}[verdict]
            st.tiles[key].setText(str(int(st.tiles[key].text() or 0) + 1))
        elif kind == "filed":
            when = time.strftime("%H:%M")
            song = f"{ev.get('artist')} - {ev.get('title')}"
            rel = ev.get("path", "")
            try:
                rel = str(Path(rel).relative_to(self.cfg.paths.library_dir))
            except Exception:
                pass
            how = {"acoustid": "identified by fingerprint", "spotify": "Spotify tags",
                   "tags": "capture tags"}.get(ev.get("identified_by"), "")
            miss = ev.get("missing") or []
            from .. import metadata as _md
            gaps = ("missing " + ", ".join(_md.LABELS.get(x, x) for x in miss)) if miss else "all metadata present"
            self.activity.add_row(when, song, "filed", f"{rel}  ·  {how}; {gaps}")
            st.tiles["inbox"].setText(str(max(0, int(st.tiles["inbox"].text() or 0) - 1)))
            st.tiles["library"].setText(str(int(st.tiles["library"].text() or 0) + 1))
            self.library.reload()
        elif kind in ("refreshed", "lyrics"):
            self.library.reload()
        elif kind == "deferred":
            self.activity.log.appendPlainText(f"{time.strftime('%H:%M:%S')}  waiting to file "
                                              f"{Path(ev.get('path', '')).name}: {ev.get('error', '')}")
        elif kind == "idle":
            self.recording_since = None
            self.recording_song = None
            st.progress.setValue(0)
            st.progress.hide()
            st.timing.setText("")
            self._refresh_state_labels()
        elif kind == "paused":
            self._refresh_state_labels()
        elif kind == "stopped":
            self.recording_since = None
            self.recording_song = None
            st.progress.setValue(0)
            st.progress.hide()

    def _refresh_chain(self) -> None:
        parts = [p for p in (self.status.device.text(), self.status.bridge.text()) if p]
        self.status.chain.setText("  ·  ".join(parts))

    def _refresh_state_labels(self) -> None:
        st = self.status
        running = self.worker is not None and self.worker.isRunning()
        if not running:
            st.state.setText("Stopped")
            theme.set_tone(st.state, "off")
            st.title.setText("")
            st.sub.setText("Press Start to begin listening for music.")
            st.set_cover(None, "stopped")
            self.side_state.setText("Stopped")
            self._set_icon("stopped")
            self.tray.setToolTip("Mynaphone: stopped")
        elif st.btn_pause.isChecked():
            st.state.setText("Paused")
            theme.set_tone(st.state, "warn")
            st.title.setText("")
            st.sub.setText("Listening, but not recording. Press Resume to record the next song.")
            st.set_cover(None, "paused")
            self.side_state.setText("Paused")
            self._set_icon("paused")
            self.tray.setToolTip("Mynaphone: paused")
        elif self.recording_since is None:
            st.state.setText("Listening")
            theme.set_tone(st.state, "ok")
            st.title.setText("")
            st.sub.setText("Waiting for a song to start in Spotify.")
            st.set_cover(None)
            self.side_state.setText("Listening")
            self._set_icon("idle")
            self.tray.setToolTip("Mynaphone: listening")

    @Slot(str)
    def on_failed(self, msg: str) -> None:
        QMessageBox.critical(self, "Recorder stopped",
                             f"The recorder hit an error:\n\n{msg}\n\nSee the log on the Activity page.")

    @Slot()
    def on_finished(self) -> None:
        st = self.status
        st.btn_start.setText("Start")
        st.btn_start.setObjectName("primary")
        st.btn_start.style().unpolish(st.btn_start)
        st.btn_start.style().polish(st.btn_start)
        st.btn_start.setEnabled(True)
        st.btn_pause.setEnabled(False)
        st.device.setText("")
        st.bridge.setText("")
        st.chain.setText("")
        self.bridge_connected = None
        self._refresh_state_labels()
        self._load_recent()
        if self._quitting:
            QApplication.instance().quit()

    def _tick(self) -> None:
        if self.recording_since is not None and self.recording_expected_ms > 0:
            elapsed_ms = int((time.monotonic() - self.recording_since) * 1000)
            frac = min(1.0, elapsed_ms / self.recording_expected_ms)
            self.status.progress.setValue(int(frac * 1000))
            self.status.timing.setText(f"{_fmt_ms(elapsed_ms)} / {_fmt_ms(self.recording_expected_ms)}")

    # ------------------------------------------------------------------ tray

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(app_icon("stopped", tile=True), self)
        menu = QMenu()
        act_show = QAction("Open Mynaphone", self)
        act_show.triggered.connect(self.show_from_tray)
        self.act_toggle = QAction("Start recording", self)
        self.act_toggle.triggered.connect(self.toggle_running)
        self.act_pause = QAction("Pause recording", self)
        self.act_pause.setCheckable(True)
        self.act_pause.toggled.connect(self.status.btn_pause.setChecked)
        self.act_harvest = QAction("Skip songs already in the library", self)
        self.act_harvest.setCheckable(True)
        self.act_harvest.setChecked(self.cfg.rules.harvest_mode)
        self.act_harvest.toggled.connect(self.status.btn_harvest.setChecked)
        act_inbox = QAction("Open inbox folder", self)
        act_inbox.triggered.connect(lambda: os.startfile(str(self.cfg.paths.inbox_dir)))
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.quit_app)
        menu.addAction(act_show)
        menu.addSeparator()
        menu.addAction(self.act_toggle)
        menu.addAction(self.act_pause)
        menu.addAction(self.act_harvest)
        menu.addAction(act_inbox)
        menu.addSeparator()
        menu.addAction(act_quit)
        menu.aboutToShow.connect(self._sync_tray_menu)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.setToolTip("Mynaphone")
        self.tray.show()

    def _sync_tray_menu(self) -> None:
        running = self.worker is not None and self.worker.isRunning()
        self.act_toggle.setText("Stop recording" if running else "Start recording")
        self.act_pause.setEnabled(running)

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_from_tray()

    def _set_icon(self, state: str) -> None:
        ic = app_icon(state, tile=True)
        self.tray.setIcon(ic)
        self.setWindowIcon(ic)

    @Slot()
    def show_from_tray(self) -> None:
        self._blank_heals = 0
        self._show_and_check()

    def _show_and_check(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(600, self._check_painted)

    def _check_painted(self) -> None:
        """Now and then the window comes back from the tray as a blank white frame, and minimizing and restoring
        it brings the pages back. When the sidebar isn't on screen, this does that once and logs what it saw."""
        if not self.isVisible() or self.isMinimized():
            return
        seen = self._sidebar_on_screen()
        if seen is None:                 # another window covers the spot
            return
        if any(c.lightness() < 128 for c in seen):      # the sidebar is near-black, so the pages are there
            if self._blank_heals:
                log.info("the window filled in after minimizing and restoring it")
            return
        if self._blank_heals:
            log.warning("the window is still blank after minimizing and restoring it (%s)", self._window_facts(seen))
            return
        log.warning("the window came up blank, minimizing and restoring it (%s)", self._window_facts(seen))
        self._blank_heals += 1
        self.showMinimized()
        QTimer.singleShot(300, self._show_and_check)

    def _sidebar_on_screen(self) -> list[QColor] | None:
        """Three spots down the sidebar's left edge as the screen shows them, or None when another window is
        in front of any of them."""
        hwnd = int(self.winId())
        seen = []
        for frac in (0.25, 0.5, 0.75):
            p = self.sidebar.mapToGlobal(QPoint(4, round(self.sidebar.height() * frac)))
            screen = QApplication.screenAt(p)
            if screen is None:
                return None
            g, dpr = screen.geometry(), screen.devicePixelRatio()
            # Qt keeps each screen's top-left corner in physical pixels and scales from there
            phys = wintypes.POINT(round(g.x() + (p.x() - g.x()) * dpr), round(g.y() + (p.y() - g.y()) * dpr))
            hit = _user32.WindowFromPoint(phys)
            if not hit or _user32.GetAncestor(hit, GA_ROOT) != hwnd:
                return None
            img = screen.grabWindow(0, p.x() - g.x(), p.y() - g.y(), 1, 1).toImage()
            if img.isNull():
                return None
            seen.append(img.pixelColor(0, 0))
        return seen

    def _window_facts(self, seen: list[QColor]) -> str:
        hwnd = int(self.winId())
        scr = self.screen()
        handle = self.windowHandle()
        return (f"sidebar shows {' '.join(c.name() for c in seen)}; on {_screen_facts(scr)} of "
                f"{len(QApplication.screens())} screens; window {self.geometry().getRect()}, "
                f"{self.windowState()}, exposed {handle.isExposed() if handle else None}; Windows says visible "
                f"{bool(_user32.IsWindowVisible(hwnd))}, minimized {bool(_user32.IsIconic(hwnd))}, "
                f"in front {_user32.GetForegroundWindow() == hwnd}")

    @Slot()
    def hide_to_tray(self) -> None:
        self.hide()
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            self.tray.showMessage("Mynaphone", "Still running. Click the tray icon to open the window.",
                                  QSystemTrayIcon.Information, 3000)

    def closeEvent(self, event) -> None:
        if self._quitting:
            event.accept()
            return
        if self.cfg.app.close_to_tray and self.worker is not None and self.worker.isRunning():
            event.ignore()
            self.hide_to_tray()
        else:
            event.ignore()
            self.quit_app()

    @Slot()
    def quit_app(self) -> None:
        self._quitting = True
        self.tray.hide()
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            QTimer.singleShot(8000, QApplication.instance().quit)
        else:
            QApplication.instance().quit()


def _screen_facts(screen) -> str:
    g = screen.geometry()
    return f"{screen.name()} at {g.x()},{g.y()} {g.width()}x{g.height()} {screen.devicePixelRatio():g}x"


def _log_qt_messages() -> None:
    """Sends Qt's own warnings to the app's log, so a window that misbehaves leaves a trace."""
    qt_log = logging.getLogger("mynaphone.qt")
    levels = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
              QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
              QtMsgType.QtFatalMsg: logging.CRITICAL}

    def handler(kind, context, message) -> None:
        cat = context.category if context.category not in (None, "", "default") else ""
        qt_log.log(levels.get(kind, logging.WARNING), "%s%s", f"{cat}: " if cat else "", message)

    _log_qt_messages.handler = handler          # keep a reference for as long as Qt may call it
    qInstallMessageHandler(handler)


INSTANCE_NAME = f"mynaphone-{os.environ.get('USERNAME', 'user')}"


def _already_running() -> bool:
    """Ask a running copy to show its window. True if one answered."""
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_NAME)
    if not sock.waitForConnected(300):
        return False
    sock.write(b"show")
    sock.waitForBytesWritten(300)
    sock.disconnectFromServer()
    return True


def run_gui(config_path: Path, minimized: bool = False) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Mynaphone")
    app.setApplicationDisplayName("Mynaphone")
    app.setQuitOnLastWindowClosed(False)
    _log_qt_messages()
    # a screen that sleeps, wakes or is unplugged leaves a line, for when the window comes up blank
    app.screenAdded.connect(lambda s: log.info("screen added: %s", _screen_facts(s)))
    app.screenRemoved.connect(lambda s: log.info("screen removed: %s", s.name()))
    app.setWindowIcon(app_icon("stopped", tile=True))
    theme.apply_theme(app)
    # one copy at a time: a second launch just brings the first one's window back
    dev_shots = bool(os.environ.get("MYNAPHONE_SHOT_DIR"))
    if not dev_shots and _already_running():
        return 0
    cfg = Config.load(config_path)
    win = MainWindow(config_path, start_minimized=minimized or cfg.app.start_minimized)
    if not dev_shots:
        from PySide6.QtNetwork import QLocalServer
        QLocalServer.removeServer(INSTANCE_NAME)
        server = QLocalServer(win)
        if server.listen(INSTANCE_NAME):
            def on_conn():
                while server.hasPendingConnections():
                    conn = server.nextPendingConnection()
                    conn.readyRead.connect(win.show_from_tray)
                    conn.disconnected.connect(conn.deleteLater)
            server.newConnection.connect(on_conn)
        win._instance_server = server
    return app.exec()
