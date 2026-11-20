# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Wanted list: albums you don't have whole and want to, nearest to whole first. Pick one to see its missing
songs, then let Mynaphone play them in Spotify and record them."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSplitter, QVBoxLayout

from .. import albums as A
from ..store import Store
from .album_panel import AlbumPanel, AlbumTable


def intro_text(min_songs: int) -> str:
    who = (f"Albums you have {min_songs} or more songs from, and the ones you added" if min_songs > 0
           else "The albums you added")
    return (f"{who}, with the nearest to whole at the top. Pick one to see what's missing, and Mynaphone can play "
            "those songs in Spotify and record them.")


def summary_text(wanted: list[A.Album], average_ms: int) -> str:
    if not wanted:
        return "Nothing on the list. Add an album from the Library's Albums view with Want this album."
    left = sum(a.to_record for a in wanted)
    minutes = sum(A.minutes_to_record(a, average_ms) for a in wanted)
    hours = f"about {minutes // 60} hours" if minutes >= 120 else f"about {minutes} minutes"
    return (f"{len(wanted)} {'album' if len(wanted) == 1 else 'albums'}, {left} "
            f"{'song' if left == 1 else 'songs'} to record, {hours}.")


class WantedDialog(QDialog):
    def __init__(self, win, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.wanted: list[A.Album] = []
        self.current: str | None = None
        self.setWindowTitle("Wanted albums")
        self.setMinimumSize(980, 600)
        self.resize(1040, 720)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)
        self.intro = QLabel(intro_text(win.cfg.albums.wanted_min_songs))
        self.intro.setWordWrap(True)
        self.intro.setObjectName("muted")
        lay.addWidget(self.intro)
        self.summary = QLabel("")
        self.summary.setObjectName("small")
        lay.addWidget(self.summary)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        self.table = AlbumTable()
        self.table.setMinimumWidth(300)
        self.table.itemSelectionChanged.connect(self._picked)
        split.addWidget(self.table)
        side = QScrollArea()
        side.setWidgetResizable(True)
        side.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.panel = AlbumPanel(win)
        self.panel.changed.connect(lambda: self.reload(read=False))
        self.panel.recording.connect(self.accept)
        side.setWidget(self.panel)
        split.addWidget(side)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 5)
        split.setSizes([380, 560])
        lay.addWidget(split, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        btns.addWidget(close)
        lay.addLayout(btns)
        self.reload()

    def reload(self, read: bool = True) -> None:
        st = Store(self.win.cfg.paths.db_path)
        found = A.build(st)
        average = A.average_song_ms(st)
        self.wanted = A.wanted_list(found, self.win.cfg.albums.wanted_min_songs)
        if self.current is None or A.find(self.wanted, self.current) is None:
            # the album on show left the list (you took it off, or it's whole): show the first one
            self.current = self.wanted[0].uri if self.wanted else None
            read = True
        self.summary.setText(summary_text(self.wanted, average))
        self.table.fill(self.wanted, self.current, average)
        album = A.find(found, self.current) if self.current else None
        self.panel.show_album(album, read=read)

    def _picked(self) -> None:
        uri = self.table.selected_uri()
        if uri is not None and uri != self.current:
            self.current = uri
            self.panel.show_album(A.find(self.wanted, uri))
