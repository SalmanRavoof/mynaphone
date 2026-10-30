# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""The songs to play again: recordings that didn't make it all the way through, and that the library still lacks."""
from __future__ import annotations

import os
import urllib.parse
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..store import Store, local_time


def spotify_link(song: dict) -> str:
    """The song in Spotify: its own page when the take knew its Spotify id, else a search for it. Songs recorded
    before the Spotify bridge connected have no id."""
    uri = song.get("source_uri") or ""
    if uri.startswith("spotify:track:"):
        return uri
    return "spotify:search:" + urllib.parse.quote(f"{song.get('artist', '')} {song.get('title', '')}".strip())


class PlayAgainDialog(QDialog):
    def __init__(self, db_path: Path, detail, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self._detail = detail          # the window's wording for discard reasons
        self.songs: list[dict] = []
        self.setWindowTitle("Songs to play again")
        self.setMinimumSize(660, 380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)
        intro = QLabel("These songs didn't record all the way through, and they aren't in your library yet. "
                       "Play one again in Spotify and Mynaphone records it. If you skipped a song on purpose, "
                       "hide it.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        lay.addWidget(intro)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Song", "Why it didn't record", "Last try"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.itemDoubleClicked.connect(lambda _item: self.open_selected())
        self.table.itemSelectionChanged.connect(self._selection_changed)
        lay.addWidget(self.table, 1)

        btns = QHBoxLayout()
        self.btn_hide = QPushButton("Hide from the list")
        self.btn_hide.setToolTip("Takes the song off this list for good.")
        self.btn_hide.clicked.connect(self.hide_selected)
        self.btn_open = QPushButton("Open in Spotify")
        self.btn_open.setObjectName("primary")
        self.btn_open.setToolTip("Opens the song in Spotify. A song recorded before the Spotify bridge connected "
                                 "opens as a search.")
        self.btn_open.clicked.connect(self.open_selected)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        btns.addWidget(self.btn_hide)
        btns.addStretch(1)
        btns.addWidget(close)
        btns.addWidget(self.btn_open)
        lay.addLayout(btns)
        self.reload()

    def reload(self) -> None:
        self.songs = Store(self.db_path).songs_to_play_again()
        self.table.setRowCount(0)
        for song in self.songs:
            i = self.table.rowCount()
            self.table.insertRow(i)
            name = QTableWidgetItem(f"{song['artist']} - {song['title']}")
            name.setToolTip(song["album"] or name.text())
            short, full = self._detail(song["reasons"])
            if song["tries"] > 1:
                short = f"{short} ({song['tries']} tries)"
            why = QTableWidgetItem(short)
            why.setToolTip(full)
            when = QTableWidgetItem(local_time(song["last_try"], "%b %d"))
            for c, item in enumerate((name, why, when)):
                self.table.setItem(i, c, item)
        if self.songs:
            self.table.selectRow(0)
        self._selection_changed()

    def _selected(self) -> dict | None:
        rows = self.table.selectionModel().selectedRows()
        return self.songs[rows[0].row()] if rows else None

    def _selection_changed(self) -> None:
        on = self._selected() is not None
        self.btn_open.setEnabled(on)
        self.btn_hide.setEnabled(on)

    def open_selected(self) -> None:
        song = self._selected()
        if song is not None:
            os.startfile(spotify_link(song))

    def hide_selected(self) -> None:
        song = self._selected()
        if song is not None:
            Store(self.db_path).hide_retry(song["key"])
            self.reload()
