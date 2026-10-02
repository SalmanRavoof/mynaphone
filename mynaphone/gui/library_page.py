# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Library page: every filed song, what it is missing, and an editor to fix things by hand."""
from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication,
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import metadata
from ..store import Store
from . import theme


def label(text: str, name: str | None = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


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
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.rows: dict[int, dict] = {}
        self.current_id: int | None = None
        self.worker: _RefreshWorker | None = None
        self._new_cover: tuple[bytes, str] | None = None

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
        head.addWidget(label("Songs", "h2"))
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
        ll.addLayout(sub)
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
        ll.addWidget(self.table, 1)
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
        split.addWidget(right)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 5)
        split.setSizes([400, 560])
        left.setMinimumWidth(300)
        body.setMinimumWidth(0)
        lay.addWidget(split, 1)
        self._set_editor_enabled(False)
        self.reload()

    # -- list ------------------------------------------------------------------------------

    @Slot()
    def reload(self) -> None:
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
        self.summary.setText(f"{total} songs in the library, {incomplete} with something missing")
        keep = self.current_id
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.rows.clear()
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
            if keep == int(r["id"]):
                self.table.selectRow(i)
        self.table.blockSignals(False)
        self.table.fit()
        QTimer.singleShot(0, self.table.fit)
        if keep is not None and keep in self.rows:
            self._load(keep)

    def _selected(self) -> None:
        items = self.table.selectedItems()
        if not items:
            return
        tid = items[0].data(Qt.UserRole)
        if tid is not None:
            self._load(int(tid))

    def _set_editor_enabled(self, on: bool) -> None:
        for w in list(self.fields.values()) + [self.kind, self.lyrics, self.btn_cover, self.btn_lookup,
                                               self.btn_folder, self.btn_save]:
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
            v = manual.get(key, ident.get(key, ""))
            if isinstance(v, list):
                v = "; ".join(v)
            e.setText("" if v in (None, 0, "0") else str(v))
            e.setCursorPosition(0)
            e.setStyleSheet(f"border-color: {theme.ACCENT};" if key in manual else "")
        kinds = {"soundtrack": 1, "album": 2, "single": 3, "compilation": 4}
        self.kind.setCurrentIndex(kinds.get(manual.get("kind", ""), 0))
        cover, lyrics = metadata.read_file_extras(Path(r["file_path"]))
        self._show_cover(cover)
        self.lyrics.setPlainText(lyrics)
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
        f, _ = QFileDialog.getOpenFileName(self, "Choose cover image", "", "Images (*.jpg *.jpeg *.png)")
        if not f:
            return
        data = Path(f).read_bytes()
        mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
        self._new_cover = (data, mime)
        self._show_cover(self._new_cover)
        self.status.setText("Cover chosen. Press Save changes to write it into the file.")

    def _manual_from_form(self) -> dict:
        r = self.rows.get(self.current_id or -1, {})
        ident = json.loads(r.get("identity_json") or "{}")
        manual = json.loads(r.get("manual_json") or "{}")
        out = {}
        for key, e in self.fields.items():
            text = e.text().strip()
            auto = ident.get(key, "")
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
        return out

    def apply(self, lookup: bool) -> None:
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
        self.status.setText(("Saved. " if not note else f"Saved ({note}). ") +
                            ("Still missing: " + ", ".join(metadata.LABELS.get(x, x) for x in miss) if miss
                             else "All metadata present."))
        self._new_cover = None
        self.reload()
        self._set_editor_enabled(True)

    @Slot(int, str)
    def _failed(self, tid: int, msg: str) -> None:
        QApplication.restoreOverrideCursor()
        self._set_editor_enabled(True)
        QMessageBox.warning(self, "Could not update the song", msg)

    @Slot()
    def export_usb(self) -> None:
        from .export_dialog import ExportDialog
        ExportDialog(self.win.cfg.paths.library_dir, self).exec()

    @Slot()
    def show_in_folder(self) -> None:
        r = self.rows.get(self.current_id or -1)
        if r and r.get("file_path") and Path(r["file_path"]).exists():
            os.startfile(str(Path(r["file_path"]).parent))
