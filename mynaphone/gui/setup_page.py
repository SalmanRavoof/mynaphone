# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""First-run setup: everything a new user needs, done from inside the app."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import storage, tools
from ..capture import HELPER
from . import theme


def label(text: str, name: str | None = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


def card() -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(8)
    return f, lay


class _Runner(QThread):
    line = Signal(str)
    done = Signal(int)

    def __init__(self, args: list[str], parent=None):
        super().__init__(parent)
        self.args = args

    def run(self) -> None:
        try:
            p = subprocess.Popen([sys.executable, "-m", "mynaphone", *self.args], stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, bufsize=1,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for ln in p.stdout:
                self.line.emit(ln.rstrip("\r\n"))
            self.done.emit(p.wait())
        except Exception as e:
            self.line.emit(str(e))
            self.done.emit(1)


class SetupPage(QScrollArea):
    """Shown on first run, and reachable later from the sidebar as 'Set up'."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.runner: _Runner | None = None
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(12)

        # 1 tools
        f, c = card()
        c.addWidget(label("1. Encoding and fingerprinting tools", "h2"))
        c.addWidget(label("Downloads ffmpeg and Chromaprint into the app's tools folder and builds the per-app "
                          "capture helper. About 115 MB. Nothing is installed system-wide.", "muted", wrap=True))
        row = QHBoxLayout()
        self.tools_status = label("", "state")
        self.btn_tools = QPushButton("Download and build")
        self.btn_tools.setObjectName("primary")
        self.btn_tools.clicked.connect(self.run_tools)
        self.btn_tools.setToolTip("Download ffmpeg and Chromaprint into the tools folder and build the capture helper. "
                                  "About 115 MB.")
        row.addWidget(self.tools_status, 1)
        row.addWidget(self.btn_tools)
        c.addLayout(row)
        self.tools_log = label("", "small", wrap=True)
        c.addWidget(self.tools_log)
        lay.addWidget(f)

        # 2 key
        f, c = card()
        c.addWidget(label("2. AcoustID application key", "h2"))
        c.addWidget(label("Song identification uses AcoustID, which asks each app to register. "
                          "It is free: create an account, register an application named Mynaphone, "
                          "and paste the application key here.", "muted", wrap=True))
        row = QHBoxLayout()
        self.key = QLineEdit(self.win.cfg.identify.acoustid_key)
        self.key.setPlaceholderText("paste the application API key")
        self.key.setEchoMode(QLineEdit.Password)
        btn_open = QPushButton("Open acoustid.org")
        btn_open.clicked.connect(lambda: webbrowser.open("https://acoustid.org/my-applications"))
        self.btn_key = QPushButton("Save key")
        self.btn_key.clicked.connect(self.save_key)
        self.btn_key.setToolTip("Store the AcoustID application key in config.toml.")
        btn_open.setToolTip("Open the AcoustID applications page in your browser to register and copy the key.")
        row.addWidget(self.key, 1)
        row.addWidget(btn_open)
        row.addWidget(self.btn_key)
        c.addLayout(row)
        self.key_status = label("", "small", wrap=True)
        c.addWidget(self.key_status)
        c.addWidget(label("Optional: a Last.fm API key. Genres come from Apple's catalog and MusicBrainz, and "
                          "with this key Last.fm's tags fill in the songs both lack. It's free: log in at "
                          "last.fm, create an API account with any name, and paste the API key here. "
                          "The shared secret isn't needed.", "muted", wrap=True))
        row = QHBoxLayout()
        self.lastfm_key = QLineEdit(self.win.cfg.identify.lastfm_api_key)
        self.lastfm_key.setPlaceholderText("paste the Last.fm API key")
        self.lastfm_key.setEchoMode(QLineEdit.Password)
        btn_lastfm = QPushButton("Open last.fm")
        btn_lastfm.clicked.connect(lambda: webbrowser.open("https://www.last.fm/api/account/create"))
        btn_lastfm.setToolTip("Open Last.fm's API account page in your browser to create a key.")
        self.btn_lastfm = QPushButton("Save key")
        self.btn_lastfm.clicked.connect(self.save_lastfm_key)
        self.btn_lastfm.setToolTip("Store the Last.fm API key in config.toml.")
        row.addWidget(self.lastfm_key, 1)
        row.addWidget(btn_lastfm)
        row.addWidget(self.btn_lastfm)
        c.addLayout(row)
        self.lastfm_status = label("", "small", wrap=True)
        c.addWidget(self.lastfm_status)
        lay.addWidget(f)

        # 3 folder
        f, c = card()
        c.addWidget(label("3. Where the music goes", "h2"))
        row = QHBoxLayout()
        self.folder = QLineEdit(str(self.win.cfg.paths.library_dir))
        btn_pick = QToolButton()
        btn_pick.setText("Browse")
        btn_pick.setMinimumWidth(70)
        btn_pick.clicked.connect(self.pick_folder)
        self.btn_folder = QPushButton("Use this folder")
        self.btn_folder.clicked.connect(self.save_folder)
        self.btn_folder.setToolTip("Save this as the library folder. Existing files are not moved.")
        row.addWidget(self.folder, 1)
        row.addWidget(btn_pick)
        row.addWidget(self.btn_folder)
        c.addLayout(row)
        self.space = label("", "muted", wrap=True)
        c.addWidget(self.space)
        self.folder.textChanged.connect(lambda _t: self.update_space())
        lay.addWidget(f)

        # 4 bridges
        f, c = card()
        c.addWidget(label("4. Spotify and browser bridges (recommended)", "h2"))
        c.addWidget(label("The Spotify bridge gives exact track ids, the real quality tier, buffering alerts and "
                          "Spotify's own synced lyrics. It needs Spicetify, a free tool that customises "
                          "the Spotify app. The browser extension does the same for YouTube.", "muted", wrap=True))
        row = QHBoxLayout()
        self.spice_status = label("", "state")
        self.btn_spice = QPushButton("Install Spotify bridge")
        self.btn_spice.clicked.connect(self.run_spicetify)
        self.btn_spice.setToolTip("Copy the bridge extension into Spicetify and apply it. Spotify restarts once.")
        btn_spice_site = QPushButton("Get Spicetify")
        btn_spice_site.clicked.connect(lambda: webbrowser.open("https://spicetify.app/docs/getting-started"))
        row.addWidget(self.spice_status, 1)
        row.addWidget(btn_spice_site)
        row.addWidget(self.btn_spice)
        c.addLayout(row)
        self.spice_log = label("", "small", wrap=True)
        c.addWidget(self.spice_log)
        ext_dir = Path(__file__).resolve().parent.parent.parent / "browser-extension"
        c.addWidget(label(f"Browser extension: in Chrome open chrome://extensions, switch on Developer mode, "
                          f"select Load unpacked and choose {ext_dir}. "
                          f"Then tick the YouTube option in Settings.", "small", wrap=True))
        btn_ext = QPushButton("Open the extension folder")
        btn_ext.clicked.connect(lambda: os.startfile(str(ext_dir)))
        btn_ext.setToolTip("Open the folder to load in chrome://extensions with Developer mode on.")
        c.addWidget(btn_ext, 0, Qt.AlignLeft)
        lay.addWidget(f)

        done = QHBoxLayout()
        done.addStretch(1)
        self.btn_done = QPushButton("Go to Status")
        self.btn_done.setObjectName("primary")
        self.btn_done.clicked.connect(lambda: self.win.nav.setCurrentRow(0))
        done.addWidget(self.btn_done)
        lay.addLayout(done)
        lay.addStretch(1)
        self.setWidget(body)
        self.refresh()

    # -- state ------------------------------------------------------------------------------

    def refresh(self) -> None:
        have_ffmpeg, have_fpcalc, have_helper = tools.ffmpeg() is not None, tools.fpcalc() is not None, HELPER.exists()
        if have_ffmpeg and have_fpcalc and have_helper:
            self.tools_status.setText("Done")
            self.tools_status.setStyleSheet(f"color: {theme.GREEN};")
            self.btn_tools.setText("Rebuild")
            self.btn_tools.setObjectName("")
        else:
            missing = [n for n, ok in (("ffmpeg", have_ffmpeg), ("Chromaprint", have_fpcalc),
                                       ("capture helper", have_helper)) if not ok]
            self.tools_status.setText("Missing: " + ", ".join(missing))
            self.tools_status.setStyleSheet(f"color: {theme.AMBER};")
        self.key_status.setText("Key saved." if self.win.cfg.identify.acoustid_key.strip()
                                else "No key yet. Without it songs are filed with Spotify's tags only.")
        self.lastfm_status.setText("Last.fm key saved." if self.win.cfg.identify.lastfm_api_key.strip()
                                   else "No Last.fm key. Genres come from Apple and MusicBrainz only.")
        appdata = Path(os.environ.get("APPDATA", ""))
        ext = appdata / "spicetify" / "Extensions" / "mynaphone.js"
        if shutil.which("spicetify") is None:
            self.spice_status.setText("Spicetify not installed")
            self.spice_status.setStyleSheet(f"color: {theme.AMBER};")
            self.btn_spice.setEnabled(False)
        elif ext.exists():
            self.spice_status.setText("Done")
            self.spice_status.setStyleSheet(f"color: {theme.GREEN};")
            self.btn_spice.setText("Reinstall")
            self.btn_spice.setEnabled(True)
        else:
            self.spice_status.setText("Spicetify found; bridge not installed")
            self.spice_status.setStyleSheet(f"color: {theme.AMBER};")
            self.btn_spice.setEnabled(True)
        self.update_space()

    @property
    def complete(self) -> bool:
        return (tools.ffmpeg() is not None and tools.fpcalc() is not None
                and bool(self.win.cfg.identify.acoustid_key.strip()))

    def update_space(self) -> None:
        c = self.win.cfg
        est = storage.estimate(Path(self.folder.text() or "."), c.library.format, c.library.bitrate,
                               c.rules.keep_discards_days, c.capture.bit_depth)
        self.space.setText(storage.describe(est))

    # -- actions ----------------------------------------------------------------------------

    def _run(self, args: list[str], log_label: QLabel, button: QPushButton) -> None:
        if self.runner is not None and self.runner.isRunning():
            return
        button.setEnabled(False)
        log_label.setText("Working...")
        self.runner = _Runner(args, self)
        self.runner.line.connect(lambda s: log_label.setText(s[-200:]))
        self.runner.done.connect(lambda code: (button.setEnabled(True),
                                               log_label.setText("Done." if code == 0
                                                                 else f"Failed (exit {code}); see the log."),
                                               self.refresh()))
        self.runner.start()

    @Slot()
    def run_tools(self) -> None:
        self._run(["setup-tools"], self.tools_log, self.btn_tools)

    @Slot()
    def run_spicetify(self) -> None:
        self._run(["install-spicetify", "--apply"], self.spice_log, self.btn_spice)

    @Slot()
    def save_key(self) -> None:
        self.win.cfg.identify.acoustid_key = self.key.text().strip()
        self.win.cfg.save()
        self.refresh()

    @Slot()
    def save_lastfm_key(self) -> None:
        self.win.cfg.identify.lastfm_api_key = self.lastfm_key.text().strip()
        self.win.cfg.save()
        self.refresh()

    @Slot()
    def pick_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose the library folder", self.folder.text())
        if d:
            self.folder.setText(d.replace("/", "\\"))

    @Slot()
    def save_folder(self) -> None:
        p = Path(self.folder.text().strip())
        if not str(p):
            return
        p.mkdir(parents=True, exist_ok=True)
        self.win.cfg.paths.library_dir = p
        self.win.cfg.save()
        try:
            self.win.settings.ed_library.edit.setText(str(p))
        except Exception:
            pass
        self.space.setText(storage.describe(
            storage.estimate(p, self.win.cfg.library.format, self.win.cfg.library.bitrate,
                             self.win.cfg.rules.keep_discards_days, self.win.cfg.capture.bit_depth)) + " Saved.")
