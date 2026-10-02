# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Export-to-USB dialog."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .. import export


def _gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"


class _Worker(QThread):
    progress = Signal(int, int, str)
    finished_ok = Signal(int, int)
    failed = Signal(str)

    def __init__(self, plan: export.ExportPlan, parent=None):
        super().__init__(parent)
        self.plan = plan
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            c, r = export.run(self.plan, progress=lambda d, t, n: self.progress.emit(d, t, n),
                              should_stop=lambda: self._stop)
            self.finished_ok.emit(c, r)
        except Exception as e:
            self.failed.emit(str(e))


class ExportDialog(QDialog):
    def __init__(self, library_dir: Path, parent=None):
        super().__init__(parent)
        self.library_dir = library_dir
        self.plan: export.ExportPlan | None = None
        self.worker: _Worker | None = None
        self.setWindowTitle("Export to USB")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)

        intro = QLabel("Copies the library to a drive for the car or a phone. "
                       "Only files that are new or changed are written.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        lay.addWidget(intro)

        row = QHBoxLayout()
        row.addWidget(QLabel("Drive"))
        self.drives = QComboBox()
        self.drives.setMinimumWidth(300)
        row.addWidget(self.drives, 1)
        self.btn_browse = QPushButton("Folder...")
        self.btn_browse.clicked.connect(self.browse)
        row.addWidget(self.btn_browse)
        lay.addLayout(row)
        self.refresh_drives()

        self.ck_lyrics = QCheckBox("Include lyrics files (.lrc). Cars ignore them; phone apps use them.")
        self.ck_lyrics.setToolTip("Also copy the .lrc files next to each song.")
        self.ck_mirror = QCheckBox("Remove songs from the drive that are no longer in the library")
        self.ck_mirror.setToolTip("Make the drive an exact copy of the library by deleting files "
                                  "that are no longer in it.")
        lay.addWidget(self.ck_lyrics)
        lay.addWidget(self.ck_mirror)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.current = QLabel("")
        self.current.setObjectName("small")
        lay.addWidget(self.current)

        btns = QHBoxLayout()
        self.btn_check = QPushButton("Check what would be copied")
        self.btn_check.clicked.connect(self.check)
        self.btn_check.setToolTip("Compare the library with the drive and report what would be copied or removed, "
                                  "without writing anything.")
        self.btn_go = QPushButton("Export")
        self.btn_go.setObjectName("primary")
        self.btn_go.setEnabled(False)
        self.btn_go.clicked.connect(self.go)
        self.btn_go.setToolTip("Copy the files. Eject the drive safely when it reports Done.")
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.reject)
        btns.addWidget(self.btn_check)
        btns.addStretch(1)
        btns.addWidget(self.btn_close)
        btns.addWidget(self.btn_go)
        lay.addLayout(btns)
        for w in (self.drives, self.ck_lyrics, self.ck_mirror):
            (w.currentIndexChanged.connect(self._invalidate) if isinstance(w, QComboBox)
             else w.toggled.connect(self._invalidate))

    def refresh_drives(self) -> None:
        self.drives.clear()
        for d in export.removable_drives():
            label = f"{d['path']}  {d['fstype']}  {_gb(d['free'])} free of {_gb(d['total'])}"
            if d["fstype"].upper() not in ("FAT32", "EXFAT", "FAT"):
                label += "  (cars usually need FAT32)"
            self.drives.addItem(label, d["path"])
        if self.drives.count() == 0:
            self.drives.addItem("No removable drive found. Plug in a USB stick or choose a folder.", "")

    def _dest(self) -> Path | None:
        p = self.drives.currentData()
        return Path(p) if p else None

    @Slot()
    def browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose destination folder")
        if d:
            self.drives.insertItem(0, d, d)
            self.drives.setCurrentIndex(0)

    def _invalidate(self, *_):
        self.plan = None
        self.btn_go.setEnabled(False)
        self.summary.setText("")

    @Slot()
    def check(self) -> None:
        dest = self._dest()
        if not dest:
            self.summary.setText("Choose a drive or folder first.")
            return
        self.plan = export.plan(self.library_dir, dest, self.ck_lyrics.isChecked(), self.ck_mirror.isChecked())
        p = self.plan
        parts = [f"{len(p.copy)} files to copy ({_gb(p.bytes_to_copy)})", f"{p.skip} already up to date"]
        if p.remove:
            parts.append(f"{len(p.remove)} to remove from the drive")
        self.summary.setText(", ".join(parts) + ".")
        self.btn_go.setEnabled(bool(p.copy or p.remove))

    @Slot()
    def go(self) -> None:
        if self.plan is None:
            self.check()
            if self.plan is None:
                return
        self.bar.setRange(0, max(1, len(self.plan.copy) + len(self.plan.remove)))
        self.bar.setValue(0)
        self.bar.show()
        for w in (self.btn_check, self.btn_go, self.drives, self.btn_browse, self.ck_lyrics, self.ck_mirror):
            w.setEnabled(False)
        self.btn_close.setText("Cancel")
        self.worker = _Worker(self.plan, self)
        self.worker.progress.connect(self._progress)
        self.worker.finished_ok.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    @Slot(int, int, str)
    def _progress(self, done: int, total: int, name: str) -> None:
        self.bar.setValue(done)
        self.current.setText(f"{done} of {total}: {name}")

    @Slot(int, int)
    def _done(self, copied: int, removed: int) -> None:
        self.current.setText("")
        self.summary.setText(f"Done. Copied {copied} files" + (f", removed {removed}" if removed else "")
                             + ". Safely eject the drive before unplugging it.")
        self._reset()

    @Slot(str)
    def _failed(self, msg: str) -> None:
        self.summary.setText(f"Export stopped: {msg}")
        self._reset()

    def _reset(self) -> None:
        self.bar.hide()
        for w in (self.btn_check, self.drives, self.btn_browse, self.ck_lyrics, self.ck_mirror):
            w.setEnabled(True)
        self.btn_close.setText("Close")
        self.plan = None
        self.btn_go.setEnabled(False)

    def reject(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.summary.setText("Cancelling after the current file...")
            return
        super().reject()
