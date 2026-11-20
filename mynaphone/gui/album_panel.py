# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Albums in the window: a list of them with how many of each album's songs you have, and one album's page, with its
missing songs, a button to record them and one to want it whole. The Library page and the Wanted list both use
them. An album's songs come from Spotify through the recorder and stay in the index for its count."""
from __future__ import annotations

import datetime as dt
import itertools
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .. import albums as A, metadata
from ..store import Store
from . import theme

KIND_NAMES = {"album": "Album", "ep": "EP", "compilation": "Compilation"}
READ_AGAIN_DAYS = 7         # an album's songs are read from Spotify again after this long
_tokens = itertools.count(1_000_000)


def _label(text: str, name: str | None = None, wrap: bool = True) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


def length(ms: int) -> str:
    s = round((ms or 0) / 1000)
    return f"{s // 60}:{s % 60:02d}" if s else ""


def songs(n: int) -> str:
    return f"{n} {'song' if n == 1 else 'songs'}"


def count_text(album: A.Album) -> str:
    if album.whole:
        text = f"You have all {album.total} of its songs." if album.total > 1 else "You have its one song."
    else:
        text = f"You have {album.have} of its {album.total} songs."
    if album.bonus:
        text += f" You also have {songs(album.bonus)} from another edition of it."
    if album.unplayable:
        text += (f" Spotify can't play {album.unplayable} of the missing "
                 f"{'song' if album.unplayable == 1 else 'songs'} where you are.")
    return text


def wanted_text(album: A.Album, min_songs: int) -> str:
    if album.whole:
        return ""
    if album.wanted == 0:
        return "You took it off your Wanted list."
    if album.wanted == 1:
        return "It's on your Wanted list, since you added it."
    if A.on_wanted_list(album, min_songs):
        return f"It's on your Wanted list, since you have {min_songs} or more of its songs."
    return "It's not on your Wanted list."


def stale(tracks_at: str | None) -> bool:
    try:
        then = dt.datetime.fromisoformat(tracks_at)
    except (TypeError, ValueError):
        return True
    return dt.datetime.now(dt.timezone.utc) - then > dt.timedelta(days=READ_AGAIN_DAYS)


class AlbumTable(QTableWidget):
    """Albums, one a row: a wide column for the album, which wraps, and a narrow one for how many songs you have."""

    def __init__(self, parent=None):
        super().__init__(0, 2, parent)
        self.setHorizontalHeaderLabels(["Album", "Songs"])
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Fixed)
        hh.setStretchLastSection(False)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.ElideNone)
        self.verticalHeader().hide()
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setWordWrap(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()
        # the viewport settles after this event; measure the rows again once it has
        QTimer.singleShot(0, self.fit)

    def fit(self) -> None:
        w = self.viewport().width()
        if w > 0:
            count = max(self.horizontalHeader().sectionSizeHint(1), self.sizeHintForColumn(1))
            self.setColumnWidth(0, max(80, w - count))
            self.setColumnWidth(1, count)
        self.resizeRowsToContents()

    def fill(self, albums: list[A.Album], current: str | None, average_ms: int = 0) -> None:
        """List `albums`, keeping `current` selected. With `average_ms`, each row's tip says how long its missing
        songs take to record."""
        self.blockSignals(True)
        self.setRowCount(0)
        keep = None
        for a in albums:
            i = self.rowCount()
            self.insertRow(i)
            name = QTableWidgetItem(f"{a.artist} - {a.name}" if a.artist else a.name)
            name.setData(Qt.UserRole, a.uri)
            name.setToolTip(name.text())
            have = QTableWidgetItem(f"{a.have} of {a.total}")
            have.setForeground(QBrush(QColor(theme.GREEN if a.whole else theme.AMBER)))
            tip = f"You have {a.have} of its {a.total} songs."
            if average_ms and a.to_record:
                tip += f" The missing ones take about {A.minutes_to_record(a, average_ms)} minutes to record."
            have.setToolTip(tip)
            self.setItem(i, 0, name)
            self.setItem(i, 1, have)
            if a.uri == current:
                keep = i
        if keep is not None:
            self.selectRow(keep)
        self.blockSignals(False)
        self.fit()
        QTimer.singleShot(0, self.fit)

    def selected_uri(self) -> str | None:
        rows = self.selectionModel().selectedRows()
        return self.item(rows[0].row(), 0).data(Qt.UserRole) if rows else None


class AlbumPanel(QFrame):
    changed = Signal()          # the album's count or its place on the Wanted list changed
    recording = Signal()        # its missing songs have started recording

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self.album: A.Album | None = None
        self._waiting: dict[int, str] = {}      # token -> the album asked for
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)
        top = QHBoxLayout()
        self.cover = QLabel()
        self.cover.setObjectName("cover")
        self.cover.setFixedSize(96, 96)
        self.cover.setAlignment(Qt.AlignCenter)
        top.addWidget(self.cover, 0, Qt.AlignTop)
        text = QVBoxLayout()
        self.title = _label("Select an album", "h2")
        self.title.setMinimumWidth(100)
        self.facts = _label("", "small")
        self.count = _label("", "muted")
        self.wanted = _label("", "small")
        for w in (self.title, self.facts, self.count, self.wanted):
            text.addWidget(w)
        text.addStretch(1)
        top.addLayout(text, 1)
        lay.addLayout(top)

        btns = QHBoxLayout()
        self.btn_record = QPushButton("Record the missing songs")
        self.btn_record.setObjectName("primary")
        self.btn_record.setToolTip("Plays the album in Spotify from the first song you don't have and jumps past "
                                   "the ones you have. Picking something else in Spotify stops it.")
        self.btn_record.clicked.connect(self.record)
        self.btn_want = QPushButton("Want this album")
        self.btn_want.setToolTip("Puts the album on your Wanted list, or takes it off.")
        self.btn_want.clicked.connect(self.toggle_wanted)
        self.btn_open = QPushButton("Open in Spotify")
        self.btn_open.setToolTip("Opens the album in Spotify.")
        self.btn_open.clicked.connect(self.open_in_spotify)
        btns.addWidget(self.btn_want)
        btns.addWidget(self.btn_open)
        btns.addStretch(1)
        lay.addLayout(btns)

        lay.addWidget(_label("Songs", "h2"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Song", "Length", ""])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setMinimumHeight(180)
        lay.addWidget(self.table, 1)
        self.note = _label("", "small")
        lay.addWidget(self.note)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(self.btn_record)
        lay.addLayout(bottom)
        self.win.worker_answer.connect(self._answered)
        self.show_album(None)

    # -- showing an album ----------------------------------------------------------------

    def show_album(self, album: A.Album | None, read: bool = True) -> None:
        self.album = album
        self._set_buttons()
        if album is None:
            self.title.setText("Select an album")
            for w in (self.facts, self.count, self.wanted, self.note):
                w.setText("")
            self.table.setRowCount(0)
            self._show_cover(None)
            return
        self.title.setText(album.name)
        facts = [KIND_NAMES.get(album.kind, "Album")]
        if album.year:
            facts.append(str(album.year))
        if album.artist:
            facts.append(album.artist)
        self.facts.setText("  ·  ".join(facts))
        min_songs = self.win.cfg.albums.wanted_min_songs
        self.count.setText(count_text(album))
        self.wanted.setText(wanted_text(album, min_songs))
        self._fill_songs(album)
        self._show_cover(album)
        if read and (not album.tracks or stale(self._tracks_at(album.uri))):
            self.read_from_spotify()

    def _set_buttons(self) -> None:
        album = self.album
        on = album is not None
        self.btn_record.setEnabled(on and album.to_record > 0 and self.win.job is None)
        self.btn_want.setEnabled(on and not album.whole)
        self.btn_open.setEnabled(on)
        listed = on and A.on_wanted_list(album, self.win.cfg.albums.wanted_min_songs)
        self.btn_want.setText("Take it off the Wanted list" if listed else "Want this album")

    def _tracks_at(self, uri: str) -> str | None:
        row = Store(self.win.cfg.paths.db_path).album_rows().get(uri)
        return row["tracks_at"] if row is not None else None

    def _fill_songs(self, album: A.Album) -> None:
        self.table.setRowCount(0)
        if album.tracks:
            for t, mine in zip(album.tracks, album.held):
                artists = ", ".join(a for a in t.get("artists") or [] if a)
                name = t.get("name", "")
                if mine is not None:
                    status, colour = "In your library", theme.GREEN
                elif t.get("playable", True):
                    status, colour = "Missing", theme.AMBER
                else:
                    status, colour = "Spotify can't play it here", theme.MUTED
                self._add_row(name, length(t.get("duration_ms") or 0), status, colour,
                              f"{artists} - {name}" if artists else name)
            self.note.setText("")
            return
        for s in sorted(album.songs, key=lambda s: (s["album_uri"] != album.uri, s["disc_number"],
                                                    s["track_number"] or 999, s["title"])):
            other = s["album_uri"] != album.uri
            self._add_row(s["title"], length(s["duration_ms"]), "From another edition" if other else "In your library",
                          theme.MUTED if other else theme.GREEN, f"{s['artist']} - {s['title']}")
        self.note.setText("These are your songs from it. The missing ones show here once Mynaphone reads the album "
                          "from Spotify, which needs the recorder running and Spotify open.")

    def _add_row(self, name: str, when: str, status: str, colour: str, tip: str) -> None:
        i = self.table.rowCount()
        self.table.insertRow(i)
        items = [QTableWidgetItem(name), QTableWidgetItem(when), QTableWidgetItem(status)]
        items[0].setToolTip(tip)
        items[2].setForeground(QBrush(QColor(colour)))
        for c, it in enumerate(items):
            self.table.setItem(i, c, it)

    def _show_cover(self, album: A.Album | None) -> None:
        for s in (album.songs if album is not None else []):
            if s["file_path"] and Path(s["file_path"]).exists():
                cover, _ = metadata.read_file_extras(Path(s["file_path"]))
                pm = QPixmap()
                if cover and pm.loadFromData(cover[0]):
                    self.cover.setPixmap(pm.scaled(96, 96, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
                    return
        self.cover.setPixmap(QPixmap())
        self.cover.setText("no cover")

    # -- reading its songs from Spotify ------------------------------------------------------

    def read_from_spotify(self) -> None:
        album = self.album
        if album is None:
            return
        token = next(_tokens)
        self._waiting[token] = album.uri
        if not album.tracks:
            self.note.setText("Reading the album's songs from Spotify...")
        if not self.win.ask_recorder(lambda rec: rec.check_playlist(album.uri), token):
            self._waiting.pop(token, None)
            if not album.tracks:
                self.note.setText("These are your songs from it. To see the ones you're missing, start the recorder "
                                  "with Spotify open, and Mynaphone reads the album from Spotify.")

    @Slot(int, object, str)
    def _answered(self, token: int, result, error: str) -> None:
        uri = self._waiting.pop(token, None)
        if uri is None or self.album is None or self.album.uri != uri:
            return
        if error:
            if not self.album.tracks:
                self.note.setText(f"Mynaphone couldn't read the album from Spotify ({error}). It tries again the "
                                  "next time you open the album with Spotify open.")
            return
        if not (result or {}).get("tracks"):
            if not self.album.tracks:
                self.note.setText("Spotify didn't list any songs for this album.")
            return
        self.changed.emit()                 # its songs are in the index now, so it's counted again

    # -- the buttons ------------------------------------------------------------------------

    def record(self) -> None:
        album = self.album
        if album is None or self.win.job is not None:
            return
        self.win.start_playlist(album.uri, album.name, keep_file=False)
        self.btn_record.setEnabled(False)
        self.note.setText("Mynaphone is playing the album in Spotify. The Status page shows how it's going.")
        self.recording.emit()

    def toggle_wanted(self) -> None:
        album = self.album
        if album is None:
            return
        on = A.on_wanted_list(album, self.win.cfg.albums.wanted_min_songs)
        Store(self.win.cfg.paths.db_path).set_wanted(album.uri, not on)
        self.changed.emit()

    def open_in_spotify(self) -> None:
        if self.album is not None:
            os.startfile(self.album.uri)
