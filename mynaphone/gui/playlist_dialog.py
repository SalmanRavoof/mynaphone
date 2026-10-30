# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Record a playlist: pick one of your Spotify playlists, or paste a playlist or album link, see how much of it the
library has, then save it as a playlist file or record the songs it's missing."""
from __future__ import annotations

import itertools
import re

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

_tokens = itertools.count(1)
_LINK = re.compile(r"(?:open\.spotify\.com/(?:intl-[a-z-]+/)?|spotify:)(playlist|album)[/:]([A-Za-z0-9]{22})")


def spotify_uri(text: str) -> str:
    """The playlist or album a pasted link points at, as a Spotify uri, or "" when it doesn't point at one."""
    m = _LINK.search(text or "")
    return f"spotify:{m.group(1)}:{m.group(2)}" if m else ""


def summary_text(checked: dict) -> str:
    total, have, todo, cant = (checked["total"], len(checked["have"]), len(checked["todo"]),
                               len(checked["unplayable"]))
    if not total:
        return "There are no songs in it."
    out = f"{have} of {total} songs are in your library."
    if todo:
        out += f" {todo} to record."
    else:
        out += " Nothing to record."
    if cant:
        out += f" {cant} {'song' if cant == 1 else 'songs'} Spotify can't play here, so they're left out."
    return out


class PlaylistDialog(QDialog):
    def __init__(self, win, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.items: list[dict] = []
        self.checked: dict | None = None
        self._waiting: dict[int, str] = {}      # token -> what was asked
        self.setWindowTitle("Record a playlist")
        self.setMinimumSize(620, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)
        intro = QLabel("Pick one of your Spotify playlists, or paste a link to a playlist or an album. Mynaphone "
                       "plays it in Spotify from the first song your library doesn't have, jumps past the ones it "
                       "has, and keeps a copy of the playlist in your library's Playlists folder.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        lay.addWidget(intro)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Playlist", "Songs"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._picked)
        lay.addWidget(self.table, 1)

        self.link = QLineEdit()
        self.link.setPlaceholderText("Or paste a Spotify link, such as https://open.spotify.com/playlist/...")
        self.link.textChanged.connect(self._pasted)
        lay.addWidget(self.link)
        self.summary = QLabel("Asking Spotify for your playlists...")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)

        btns = QHBoxLayout()
        self.btn_save = QPushButton("Save the playlist file")
        self.btn_save.setToolTip("Writes the playlist to your library's Playlists folder without recording anything. "
                                 "Songs you don't have yet are listed as notes in the file.")
        self.btn_save.clicked.connect(self.save)
        self.btn_record = QPushButton("Record the missing songs")
        self.btn_record.setObjectName("primary")
        self.btn_record.setToolTip("Plays the playlist in Spotify from the first song your library doesn't have. "
                                   "Picking something else in Spotify stops it.")
        self.btn_record.clicked.connect(self.record)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        btns.addWidget(self.btn_save)
        btns.addStretch(1)
        btns.addWidget(close)
        btns.addWidget(self.btn_record)
        lay.addLayout(btns)
        self._set_buttons()
        self.win.worker_answer.connect(self._answered)
        self._ask(lambda rec: rec.list_playlists(), "playlists")

    # -- asking the recorder ---------------------------------------------------------------

    def _ask(self, make, what: str) -> None:
        token = next(_tokens)
        self._waiting[token] = what
        if not self.win.ask_recorder(make, token):
            self._waiting.pop(token, None)
            self.summary.setText("Start the recorder first: the playlists come from Spotify through it.")

    @Slot(int, object, str)
    def _answered(self, token: int, result, error: str) -> None:
        what = self._waiting.pop(token, None)
        if what is None:
            return
        if error:
            self.summary.setText(f"Spotify didn't answer: {error}. Is Spotify open with the bridge connected?")
            self._set_buttons()
            return
        if what == "playlists":
            self._fill(result or {})
        elif what.startswith("check:"):
            if what[6:] == self._uri():
                self.checked = result
                self.summary.setText(summary_text(result))
        elif what == "save":
            self.summary.setText(f"Saved {result['path']}: {result['listed']} songs in it, "
                                 f"{result['missing']} still to record.")
        self._set_buttons()

    # -- the list ------------------------------------------------------------------------------

    def _fill(self, got: dict) -> None:
        self.items = ([got["liked"]] if got.get("liked") else []) + list(got.get("playlists") or [])
        self.table.setRowCount(0)
        for p in self.items:
            i = self.table.rowCount()
            self.table.insertRow(i)
            name = QTableWidgetItem(p.get("name") or p["uri"])
            name.setToolTip(" / ".join(x for x in (p.get("folder"), p.get("owner")) if x) or name.text())
            self.table.setItem(i, 0, name)
            self.table.setItem(i, 1, QTableWidgetItem(str(p.get("total") or 0)))
        self.summary.setText("Pick a playlist to see how much of it is in your library." if self.items
                             else "No playlists came back from Spotify. Paste a link instead.")

    def _uri(self) -> str:
        pasted = spotify_uri(self.link.text())
        if pasted:
            return pasted
        rows = self.table.selectionModel().selectedRows()
        return self.items[rows[0].row()]["uri"] if rows else ""

    def _name(self) -> str:
        if spotify_uri(self.link.text()):
            return "Playlist " + spotify_uri(self.link.text()).rsplit(":", 1)[-1][:8]
        rows = self.table.selectionModel().selectedRows()
        return (self.items[rows[0].row()].get("name") or "Playlist") if rows else "Playlist"

    def _picked(self) -> None:
        if self.table.selectionModel().selectedRows():
            self.link.blockSignals(True)
            self.link.clear()
            self.link.blockSignals(False)
        self._check()

    def _pasted(self, text: str) -> None:
        if spotify_uri(text):
            self.table.clearSelection()
            self._check()
        elif text.strip():
            self.checked = None
            self.summary.setText("That doesn't look like a link to a Spotify playlist or album.")
            self._set_buttons()

    def _check(self) -> None:
        uri = self._uri()
        self.checked = None
        self._set_buttons()
        if uri:
            self.summary.setText("Reading its songs from Spotify...")
            self._ask(lambda rec: rec.check_playlist(uri), "check:" + uri)

    def _set_buttons(self) -> None:
        ready = self.checked is not None and self.checked.get("uri") == self._uri()
        self.btn_save.setEnabled(ready)
        self.btn_record.setEnabled(ready and bool(self.checked["todo"]) and self.win.job is None)

    # -- the buttons -----------------------------------------------------------------------------

    def save(self) -> None:
        uri, name = self._uri(), self._name()
        self._ask(lambda rec: rec.save_playlist(uri, name), "save")

    def record(self) -> None:
        uri, name = self._uri(), self._name()
        self.win.start_playlist(uri, name)
        self.accept()
