# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Library page: every filed song, what it is missing, and an editor to fix things by hand. Its Albums view lists
the albums those songs come from, with how many of each album's songs you have."""
from __future__ import annotations

import json
import os
import unicodedata
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import albums as A, metadata
from ..store import Store
from . import theme
from .album_panel import AlbumPanel, AlbumTable


def label(text: str, name: str | None = None, wrap: bool = False) -> QLabel:
    """A `QLabel` showing `text`. A `name` becomes its object name for the theme's stylesheet, and `wrap` lets its
    text run onto more lines."""
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


def _fold(text: str) -> str:
    """Lower case with the accents taken off, so a search for "mananitas" finds "Las Mañanitas"."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


class _SearchBox(QLineEdit):
    """The search box over the song list. Esc clears it, and the down arrow or Enter moves to the first song it
    found."""

    def __init__(self, to_first_match):
        super().__init__()
        self.to_first_match = to_first_match

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape and self.text():
            self.clear()
        elif event.key() in (Qt.Key_Down, Qt.Key_Return, Qt.Key_Enter):
            self.to_first_match()
        else:
            super().keyPressEvent(event)


class _RefreshWorker(QThread):
    done = Signal(int, dict)
    failed = Signal(int, str)

    def __init__(self, cfg, db_path, track_id: int, lookup: bool, manual: dict | None, cover, lyrics, parent=None):
        super().__init__(parent)
        self.cfg, self.db_path, self.track_id = cfg, db_path, track_id
        self.lookup, self.manual, self.cover, self.lyrics = lookup, manual, cover, lyrics

    def run(self) -> None:
        try:
            st = Store(self.db_path)
            row = st.track(self.track_id)
            res = metadata.refresh_track(self.cfg, st, row, lookup=self.lookup, manual=self.manual,
                                         new_cover=self.cover, new_lyrics=self.lyrics, move=True)
            res.pop("ident", None)
            self.done.emit(self.track_id, res)
        except Exception as e:
            self.failed.emit(self.track_id, str(e))


class _WrapTable(QTableWidget):
    """A two-column table whose columns share the width and whose rows grow to show every word."""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()
        # the viewport settles after this event; measure the rows again once it has
        QTimer.singleShot(0, self.fit)

    def fit(self) -> None:
        w = self.viewport().width()
        if w > 0 and self.columnCount() == 2:
            first = int(w * 0.46)
            self.setColumnWidth(0, first)
            self.setColumnWidth(1, w - first)
        self.resizeRowsToContents()


class LibraryPage(QWidget):
    """The Library page of the main window `win`. The Songs and Albums buttons switch between the song list beside
    the editor and the album list beside an `AlbumPanel`. Save and Look up again write to the song's file on a worker
    thread."""
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.rows: dict[int, dict] = {}
        self._haystack: dict[int, str] = {}     # each song's words the search box looks in, folded by _fold
        self._counts = ""                       # the library's counts, shown under Songs while nothing is searched
        self.current_id: int | None = None
        self.albums: list[A.Album] = []
        self.current_album: str | None = None   # the album shown, by the Spotify id it's counted against
        self.worker: _RefreshWorker | None = None
        self._new_cover: tuple[bytes, str] | None = None
        self._loaded_lyrics = ""                # the open song's lyrics as the editor read them

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        # left: list
        left = QFrame()
        left.setObjectName("card")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(18, 16, 18, 16)
        head = QHBoxLayout()
        head.setSpacing(0)
        self.btn_songs = QPushButton("Songs")
        self.btn_songs.setToolTip("Your songs, with the details each one is still missing.")
        self.btn_albums = QPushButton("Albums")
        self.btn_albums.setToolTip("The albums your songs come from, with how many of each album's songs you have.")
        self.views = QButtonGroup(self)
        for i, b in enumerate((self.btn_songs, self.btn_albums)):
            b.setCheckable(True)
            b.setMinimumWidth(84)
            self.views.addButton(b, i)
            head.addWidget(b)
        self.btn_songs.setChecked(True)
        self.views.idToggled.connect(self._view_toggled)
        head.addStretch(1)
        self.btn_export = QPushButton("Export to USB")
        self.btn_export.clicked.connect(self.export_usb)
        self.btn_export.setToolTip("Copy the library to a USB stick or folder. Only new or changed files are written.")
        head.addWidget(self.btn_export)
        ll.addLayout(head)
        sub = QHBoxLayout()
        self.summary = label("", "small", wrap=True)
        sub.addWidget(self.summary, 1)
        sub.addStretch(1)
        self.only_incomplete = QCheckBox("Needs attention")
        self.only_incomplete.toggled.connect(self.reload)
        self.only_incomplete.setToolTip("List only songs with missing metadata.")
        sub.addWidget(self.only_incomplete)
        self.only_partial = QCheckBox("Incomplete")
        self.only_partial.toggled.connect(lambda _on: self.reload_albums())
        self.only_partial.setToolTip("List only the albums you don't have every song of.")
        self.only_partial.hide()
        sub.addWidget(self.only_partial)
        ll.addLayout(sub)
        self.search = _SearchBox(self.to_first_match)
        self.search.setPlaceholderText("Find a song")
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip("Type part of a title, artist, or album, and the list shows only the songs that "
                               "match. Press Esc to clear the box.")
        self.search.textChanged.connect(self._filter)
        ll.addWidget(self.search)
        self.table = _WrapTable(0, 2)
        self.table.setHorizontalHeaderLabels(["Song", "Missing"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Fixed)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hh.setStretchLastSection(False)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        self.table.itemSelectionChanged.connect(self._selected)
        self.album_table = AlbumTable()
        self.album_table.itemSelectionChanged.connect(self._album_selected)
        self.lists = QStackedWidget()
        self.lists.addWidget(self.table)
        self.lists.addWidget(self.album_table)
        ll.addWidget(self.lists, 1)
        split.addWidget(left)

        # right: editor
        right = QScrollArea()
        right.setWidgetResizable(True)
        right.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QFrame()
        body.setObjectName("card")
        rl = QVBoxLayout(body)
        rl.setContentsMargins(18, 16, 18, 16)
        rl.setSpacing(10)
        top = QHBoxLayout()
        self.cover = QLabel()
        self.cover.setObjectName("cover")
        self.cover.setFixedSize(96, 96)
        self.cover.setAlignment(Qt.AlignCenter)
        top.addWidget(self.cover, 0, Qt.AlignTop)
        tt = QVBoxLayout()
        self.ed_title_big = label("Select a song", "h2")
        self.ed_title_big.setWordWrap(True)
        self.ed_title_big.setMinimumWidth(100)
        self.path_label = label("", "small", wrap=True)
        self.missing_label = label("", "muted", wrap=True)
        tt.addWidget(self.ed_title_big)
        tt.addWidget(self.path_label)
        tt.addWidget(self.missing_label)
        tt.addStretch(1)
        top.addLayout(tt, 1)
        rl.addLayout(top)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.fields: dict[str, QLineEdit] = {}
        for key, lab in (("title", "Title"), ("artist", "Artist"), ("album", "Album"), ("album_artist", "Album artist"),
                         ("year", "Year"), ("track_number", "Track number"), ("track_total", "Track count"),
                         ("disc_number", "Disc number"), ("disc_total", "Disc count"), ("composers", "Composer"),
                         ("lyricists", "Lyricist"), ("genres", "Genre"), ("isrc", "ISRC"), ("label", "Label")):
            e = QLineEdit()
            if key in ("year", "track_number", "track_total", "disc_number", "disc_total"):
                e.setFixedWidth(120)
            self.fields[key] = e
            form.addRow(lab, e)
        self.kind = QComboBox()
        self.kind.addItems(["Decide automatically", "Soundtrack", "Album", "Single", "Compilation"])
        self.kind.setFixedWidth(220)
        self.kind.setToolTip("Force the song into the Soundtracks, Artists or Singles layout, or let the app decide.")
        form.addRow("Filed as", self.kind)
        self.instrumental = QComboBox()
        self.instrumental.addItems(["Decide automatically", "Yes, no vocals", "No, it has vocals"])
        self.instrumental.setFixedWidth(220)
        self.instrumental.setToolTip("An instrumental needs no lyrics or lyricist, so they stop showing as missing. "
                                     "The app decides from the title and album unless you choose.")
        form.addRow("Instrumental", self.instrumental)
        rl.addLayout(form)
        rl.addWidget(label("Lists such as composers or genres take several names separated by semicolons. "
                           "Fields you edit are kept even when the song is looked up again.", "small", wrap=True))

        rl.addWidget(label("Lyrics", "h2"))
        self.lyrics = QPlainTextEdit()
        self.lyrics.setPlaceholderText("Paste lyrics here. Timestamps like [01:23.45] make them synced.")
        self.lyrics.setMinimumHeight(140)
        rl.addWidget(self.lyrics)

        btns = QHBoxLayout()
        self.btn_cover = QPushButton("Cover image")
        self.btn_cover.clicked.connect(self.pick_cover)
        self.btn_cover.setToolTip("Choose a picture file to use as this song's cover.")
        self.btn_lookup = QPushButton("Look up again")
        self.btn_lookup.clicked.connect(lambda: self.apply(lookup=True))
        self.btn_lookup.setToolTip("Fingerprint the file again and query AcoustID, MusicBrainz and the lyrics sources. "
                                   "Your edits are kept.")
        self.btn_folder = QPushButton("Folder")
        self.btn_folder.clicked.connect(self.show_in_folder)
        self.btn_folder.setToolTip("Open the folder that holds this file.")
        self.btn_save = QPushButton("Save")
        self.btn_save.setObjectName("primary")
        self.btn_save.setMinimumWidth(90)
        self.btn_save.clicked.connect(lambda: self.apply(lookup=False))
        self.btn_save.setToolTip("Write your changes into the file's tags. "
                                 "Edited fields are protected from later lookups.")
        btns.addWidget(self.btn_cover)
        btns.addWidget(self.btn_lookup)
        btns.addWidget(self.btn_folder)
        btns.addStretch(1)
        btns.addWidget(self.btn_save)
        rl.addLayout(btns)
        self.status = label("", "small", wrap=True)
        rl.addWidget(self.status)
        rl.addStretch(1)
        right.setWidget(body)
        album_side = QScrollArea()
        album_side.setWidgetResizable(True)
        album_side.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.album_panel = AlbumPanel(win)
        self.album_panel.setMinimumWidth(0)
        self.album_panel.changed.connect(self._album_changed)
        album_side.setWidget(self.album_panel)
        self.sides = QStackedWidget()
        self.sides.addWidget(right)
        self.sides.addWidget(album_side)
        split.addWidget(self.sides)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 5)
        split.setSizes([400, 560])
        left.setMinimumWidth(300)
        body.setMinimumWidth(0)
        lay.addWidget(split, 1)
        self._set_editor_enabled(False)
        self.reload()

    # -- list ------------------------------------------------------------------------------

    @Slot(int, bool)
    def _view_toggled(self, view: int, on: bool) -> None:
        if not on:
            return
        albums = view == 1
        self.lists.setCurrentIndex(view)
        self.sides.setCurrentIndex(view)
        self.only_incomplete.setVisible(not albums)
        self.only_partial.setVisible(albums)
        self.search.setVisible(not albums)          # it finds songs
        self.reload()

    def showing_albums(self) -> bool:
        """True when the Albums view is on."""
        return self.views.checkedId() == 1

    @Slot()
    def reload(self) -> None:
        """Refill the song list from the index, or the album list in the Albums view. The editor reloads too, unless
        it has changes you haven't saved."""
        if self.showing_albums():
            self.reload_albums(read=False)
            return
        editing = self._has_unsaved_changes()
        try:
            st = Store(self.win.cfg.paths.db_path)
            rows = st.library_rows(only_incomplete=self.only_incomplete.isChecked())
            total = st.conn.execute("SELECT COUNT(*) FROM tracks WHERE state='library'").fetchone()[0]
            incomplete = st.conn.execute(
                "SELECT COUNT(*) FROM tracks WHERE state='library' AND missing_json IS NOT NULL "
                "AND missing_json != '[]'").fetchone()[0]
        except Exception as e:
            self.summary.setText(f"could not read the index: {e}")
            return
        self._counts = f"{total} songs in the library, {incomplete} with something missing"
        keep = self.current_id
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.rows.clear()
        self._haystack.clear()
        for r in rows:
            miss = json.loads(r["missing_json"] or "[]") if r["missing_json"] else []
            i = self.table.rowCount()
            self.table.insertRow(i)
            song = QTableWidgetItem(f"{r['artist']} - {r['title']}")
            song.setData(Qt.UserRole, int(r["id"]))
            song.setToolTip(r["album"] or "")
            m = QTableWidgetItem(", ".join(metadata.LABELS.get(x, x) for x in miss) if miss else "Complete")
            m.setToolTip(m.text())
            m.setForeground(QBrush(QColor(theme.AMBER if miss else theme.GREEN)))
            for c, it in enumerate((song, m)):
                self.table.setItem(i, c, it)
            self.rows[int(r["id"])] = dict(r)
            self._haystack[int(r["id"])] = _fold(" ".join(str(r[k] or "") for k in ("title", "artist", "album",
                                                                                    "album_artist")))
            if keep == int(r["id"]):
                self.table.selectRow(i)
        self.table.blockSignals(False)
        self._filter()
        self.table.fit()
        QTimer.singleShot(0, self.table.fit)
        if keep is not None and keep in self.rows and not editing:
            self._load(keep)

    def reload_albums(self, read: bool = True) -> None:
        """List the albums and count each one again. With `read`, the album on show may be read from Spotify again."""
        try:
            self.albums = A.build(Store(self.win.cfg.paths.db_path))
        except Exception as e:
            self.summary.setText(f"could not read the index: {e}")
            return
        whole = sum(1 for a in self.albums if a.whole)
        self.summary.setText(f"{len(self.albums)} albums, {whole} with every song")
        self.album_table.fill([a for a in self.albums if not (self.only_partial.isChecked() and a.whole)],
                              self.current_album)
        album = A.find(self.albums, self.current_album) if self.current_album else None
        self.album_panel.show_album(album, read=read)

    def _album_selected(self) -> None:
        uri = self.album_table.selected_uri()
        if uri is not None:
            self.current_album = uri
            self.album_panel.show_album(A.find(self.albums, uri))

    def _album_changed(self) -> None:
        self.reload_albums(read=False)
        self.win.refresh_wanted()

    @Slot()
    def _filter(self) -> None:
        """Show only the songs with every word typed in the search box somewhere in their title, artist, album or
        album artist, and say how many that is. The Albums view keeps its own counts."""
        words = _fold(self.search.text()).split()
        found = 0
        for i in range(self.table.rowCount()):
            hit = all(w in self._haystack.get(self.table.item(i, 0).data(Qt.UserRole), "") for w in words)
            if self.table.isRowHidden(i) == hit:        # touch only the rows that change, so typing stays quick
                self.table.setRowHidden(i, not hit)
            found += hit
        if self.showing_albums():
            return
        if not words:
            self.summary.setText(self._counts)
        elif found:
            self.summary.setText(f"{found} {'song matches' if found == 1 else 'songs match'} your search")
        else:
            self.summary.setText("No songs match your search")

    def to_first_match(self) -> None:
        """From the search box to the first song it found, open in the editor."""
        for i in range(self.table.rowCount()):
            if not self.table.isRowHidden(i):
                self.table.selectRow(i)
                self.table.setFocus(Qt.OtherFocusReason)
                return

    def _selected(self) -> None:
        items = self.table.selectedItems()
        if not items:
            return
        tid = items[0].data(Qt.UserRole)
        if tid is not None:
            self._load(int(tid))

    def _set_editor_enabled(self, on: bool) -> None:
        for w in list(self.fields.values()) + [self.kind, self.instrumental, self.lyrics, self.btn_cover,
                                               self.btn_lookup, self.btn_folder, self.btn_save]:
            w.setEnabled(on)

    def _load(self, tid: int) -> None:
        r = self.rows.get(tid)
        if not r:
            return
        self.current_id = tid
        self._new_cover = None
        ident = json.loads(r.get("identity_json") or "{}")
        manual = json.loads(r.get("manual_json") or "{}")
        self.ed_title_big.setText(f"{r['artist']} - {r['title']}")
        try:
            self.path_label.setText(str(Path(r["file_path"]).relative_to(self.win.cfg.paths.library_dir)))
        except Exception:
            self.path_label.setText(r["file_path"] or "")
        miss = json.loads(r.get("missing_json") or "[]")
        self.missing_label.setText(("Missing: " + ", ".join(metadata.LABELS.get(x, x) for x in miss)) if miss
                                   else "All metadata present.")
        for key, e in self.fields.items():
            v = manual.get(key, metadata.tagged_value(ident, key))     # what the file says, such as its film's album
            if isinstance(v, list):
                v = "; ".join(v)
            e.setText("" if v in (None, 0, "0") else str(v))
            e.setCursorPosition(0)
            e.setStyleSheet(f"border-color: {theme.ACCENT};" if key in manual else "")
        kinds = {"soundtrack": 1, "album": 2, "single": 3, "compilation": 4}
        self.kind.setCurrentIndex(kinds.get(manual.get("kind", ""), 0))
        self.instrumental.setCurrentIndex({True: 1, False: 2}.get(manual.get("instrumental"), 0))
        cover, lyrics = metadata.read_file_extras(Path(r["file_path"]))
        self._show_cover(cover)
        self.lyrics.setPlainText(lyrics)
        self._loaded_lyrics = self.lyrics.toPlainText()     # as the box shows them, line ends and all
        self.status.setText("")
        self._set_editor_enabled(True)

    def _show_cover(self, cover) -> None:
        if cover:
            pm = QPixmap()
            if pm.loadFromData(cover[0]):
                self.cover.setPixmap(pm.scaled(96, 96, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
                return
        self.cover.setPixmap(QPixmap())
        self.cover.setText("no cover")

    # -- actions ---------------------------------------------------------------------------

    @Slot()
    def pick_cover(self) -> None:
        """When you press Cover image, show the picture you choose in the editor, and keep it so the next Save or
        Look up again writes it into the song's file."""
        f, _ = QFileDialog.getOpenFileName(self, "Choose cover image", "", "Images (*.jpg *.jpeg *.png)")
        if not f:
            return
        data = Path(f).read_bytes()
        mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
        self._new_cover = (data, mime)
        self._show_cover(self._new_cover)
        self.status.setText("Cover chosen. Press Save changes to write it into the file.")

    def _has_unsaved_changes(self) -> bool:
        """True while the editor has changes you haven't saved, a picked cover included."""
        r = self.rows.get(self.current_id if self.current_id is not None else -1)
        if not r:
            return False
        manual = json.loads(r.get("manual_json") or "{}")
        saved = {k: v for k, v in manual.items() if k in self.fields}
        return (self._new_cover is not None or self._manual_from_form() != saved
                or self.lyrics.toPlainText().strip() != (self._loaded_lyrics or "").strip())

    def _manual_from_form(self) -> dict:
        r = self.rows.get(self.current_id or -1, {})
        ident = json.loads(r.get("identity_json") or "{}")
        manual = json.loads(r.get("manual_json") or "{}")
        out = {}
        for key, e in self.fields.items():
            text = e.text().strip()
            auto = metadata.tagged_value(ident, key)
            if isinstance(auto, list):
                auto = "; ".join(auto)
            auto = "" if auto in (None, 0) else str(auto)
            if (key in manual
                    and text == str(manual[key] if not isinstance(manual[key], list) else "; ".join(manual[key]))):
                out[key] = manual[key]
            elif text != auto:
                out[key] = text          # "" clears an earlier manual value
        kinds = ["", "soundtrack", "album", "single", "compilation"]
        k = kinds[self.kind.currentIndex()]
        if k != manual.get("kind", ""):
            out["kind"] = k
        inst = ["", True, False][self.instrumental.currentIndex()]
        if inst != manual.get("instrumental", ""):
            out["instrumental"] = inst   # "" clears an earlier choice
        return out

    def apply(self, lookup: bool) -> None:
        """Write the editor's changes into the song's file with `metadata.refresh_track` on a worker thread. Save
        runs it, and Look up again runs it with `lookup` True to look the song up first."""
        if self.current_id is None or (self.worker and self.worker.isRunning()):
            return
        r = self.rows[self.current_id]
        manual = self._manual_from_form()
        _, current_lyrics = metadata.read_file_extras(Path(r["file_path"]))
        new_lyrics = self.lyrics.toPlainText()
        lyrics_arg = new_lyrics if new_lyrics.strip() != (current_lyrics or "").strip() else None
        self.status.setText("Looking the song up again..." if lookup else "Saving...")
        self._set_editor_enabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.worker = _RefreshWorker(self.win.cfg, self.win.cfg.paths.db_path, self.current_id, lookup, manual,
                                     self._new_cover, lyrics_arg, self)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    @Slot(int, dict)
    def _done(self, tid: int, res: dict) -> None:
        QApplication.restoreOverrideCursor()
        miss = res.get("missing", [])
        note = res.get("note", "")
        self._new_cover = None
        self.reload()
        if tid in self.rows:
            self._load(tid)                     # the saved song, as the index has it now
        self.status.setText(("Saved. " if not note else f"Saved ({note}). ") +
                            ("Still missing: " + ", ".join(metadata.LABELS.get(x, x) for x in miss) if miss
                             else "All metadata present."))
        self._set_editor_enabled(True)

    @Slot(int, str)
    def _failed(self, tid: int, msg: str) -> None:
        QApplication.restoreOverrideCursor()
        self._set_editor_enabled(True)
        QMessageBox.warning(self, "Could not update the song", msg)

    @Slot()
    def export_usb(self) -> None:
        """When you press Export to USB, open the dialog of that name for the library folder, the `[paths]` setting
        `library_dir`."""
        from .export_dialog import ExportDialog
        ExportDialog(self.win.cfg.paths.library_dir, self).exec()

    @Slot()
    def show_in_folder(self) -> None:
        """When you press Folder, open the folder of the song you're editing, if its file is still there."""
        r = self.rows.get(self.current_id or -1)
        if r and r.get("file_path") and Path(r["file_path"]).exists():
            os.startfile(str(Path(r["file_path"]).parent))
