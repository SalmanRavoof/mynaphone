# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI tests, run offscreen: the theme, the mark, tooltips, page headers, state pills, tables and
the single-instance guard. No recorder is started and no audio is touched."""
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint  # noqa: E402
from PySide6.QtGui import QHelpEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem, QPushButton  # noqa: E402

from mynaphone.gui import icons, theme  # noqa: E402
from mynaphone.store import Store  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    theme.apply_theme(app)
    return app


@pytest.fixture
def gui_config(tmp_path: Path) -> Path:
    """A config that opens the window without starting the recorder."""
    p = tmp_path / "config.toml"
    p.write_text(
        "[paths]\n"
        f'inbox_dir = "{(tmp_path / "inbox").as_posix()}"\n'
        f'discard_dir = "{(tmp_path / "discard").as_posix()}"\n'
        f'library_dir = "{(tmp_path / "library").as_posix()}"\n'
        f'db_path = "{(tmp_path / "db.sqlite").as_posix()}"\n'
        f'log_dir = "{(tmp_path / "logs").as_posix()}"\n'
        "[capture]\nmode = \"device\"\n"
        "[rules]\nsources = [\"Spotify.exe\"]\n"
        "[bridge]\nenabled = false\n"
        "[app]\nstart_minimized = false\nautostart_recording = false\nshow_tooltips = true\n",
        encoding="utf-8",
    )
    return p


def _seed(db: Path, library_dir: Path) -> None:
    """One filed song with gaps, one complete, and three takes in the log."""
    st = Store(db)
    song = library_dir / "Artists" / "A" / "Singles" / "Song.m4a"
    song.parent.mkdir(parents=True)
    song.write_bytes(b"")
    st.add_track(artist="A", title="Song", album="", album_artist="A", track_number=0, duration_ms=200000,
                 source_app="Spotify.exe", source_uri="spotify:track:1", quality_tier="high", file_path=str(song),
                 state="library", missing_json='["album", "year", "cover", "lyrics", "synced_lyrics", "composers"]')
    st.add_track(artist="B", title="Done", album="Album", album_artist="B", track_number=1, duration_ms=100000,
                 source_app="Spotify.exe", source_uri="spotify:track:2", quality_tier="high", file_path=str(song),
                 state="library", missing_json="[]")
    for i, (verdict, reasons) in enumerate((("keep", "[]"),
                                            ("discard", '["paused", "session_gone", "length_mismatch"]'),
                                            ("discard", '["buffering"]'))):
        st.log_take(started_at=f"2026-10-02T0{i}:00:00", ended_at=f"2026-10-02T0{i}:03:00", artist="A", title=f"T{i}",
                    album="", source_app="Spotify.exe", source_uri="", expected_ms=180000, captured_ms=180000,
                    wall_ms=180000, verdict=verdict, reasons=reasons, file_path=None, quality_tier="high")
    st.conn.commit()


@pytest.fixture
def window(qapp, gui_config, tmp_path):
    from mynaphone.config import Config
    cfg = Config.load(gui_config)
    _seed(cfg.paths.db_path, cfg.paths.library_dir)
    from mynaphone.gui.app import MainWindow
    win = MainWindow(gui_config, start_minimized=False)
    qapp.processEvents()
    yield win
    win._quitting = True
    win.close()
    win.deleteLater()
    qapp.processEvents()


# -- theme and mark -----------------------------------------------------------------------

def test_theme_builds_and_tones_switch(qapp):
    from PySide6.QtWidgets import QLabel
    qss = qapp.styleSheet()
    assert 'QLabel#pill[tone="rec"]' in qss and "QWidget#sidebar" in qss and "QFrame#tip" in qss
    lab = QLabel("Recording")
    lab.setObjectName("pill")
    theme.set_tone(lab, "rec")
    assert lab.property("tone") == "rec"


@pytest.mark.parametrize("state", ["idle", "recording", "paused", "stopped"])
def test_mark_renders_every_state_and_tile(qapp, state):
    for tile in (False, True):
        for size in icons.MARK_SIZES:
            pm = icons.app_icon(state, tile=tile).pixmap(size, size)
            assert not pm.isNull() and pm.width() == size
        img = icons.app_icon(state, tile=tile).pixmap(32, 32).toImage()
        red = sum(1 for x in range(32) for y in range(32)
                  if (c := img.pixelColor(x, y)).red() > 180 and c.green() < 120 and c.alpha() > 200)
        # the eye is red only while recording
        assert (red > 0) == (state == "recording")


def test_tray_eye_is_big_enough_to_see_turn_red(qapp):
    """At 150 % the tray icon is 24 px; the designer's eye alone gave it 8 red pixels."""
    from PySide6.QtCore import QSize

    def red(pm):
        img = pm.toImage()
        return sum(1 for x in range(img.width()) for y in range(img.height())
                   if (c := img.pixelColor(x, y)).red() > 150 and c.green() < 110 and c.alpha() > 128)

    assert all(icons._small_svg(s, v) for s in icons.MARK_STATES.values() for v in ("tile", "bare"))
    tray = icons.app_icon("recording", tile=True).pixmap(QSize(16, 16), 1.5)
    assert tray.width() == 24 and red(tray) >= 30
    assert red(icons.app_icon("idle", tile=True).pixmap(QSize(16, 16), 1.5)) == 0
    # the taskbar asks for 32 px at 150 %: it gets a sharp 48 px icon, not the 24 px one stretched
    assert icons.app_icon("recording", tile=True).pixmap(QSize(32, 32), 1.5).width() == 48


def test_nav_icons_exist_for_every_page(qapp):
    for name in ("Status", "Activity", "Library", "Settings", "Setup check", "Set up"):
        ic = icons.nav_icon(name)
        assert name in icons.NAV_GLYPHS
        if "Segoe MDL2 Assets" in __import__("PySide6.QtGui", fromlist=["QFontDatabase"]).QFontDatabase.families():
            assert not ic.isNull()


# -- tooltips -----------------------------------------------------------------------------

class _Cfg:
    class app:
        show_tooltips = True


class _Win:
    cfg = _Cfg()


def test_tooltip_shows_under_control_and_hides_on_leave(qapp):
    from mynaphone.gui.app import _TipFilter
    f = _TipFilter(_Win())
    b = QPushButton("x")
    b.setToolTip("hello tip")
    b.show()
    ev = QHelpEvent(QEvent.ToolTip, QPoint(3, 3), b.mapToGlobal(QPoint(3, 3)))
    assert f.eventFilter(b, ev) is True
    assert f.tip.isVisible() and f.tip.text.text() == "hello tip"
    assert f.tip.y() >= b.mapToGlobal(b.rect().bottomLeft()).y()
    f.eventFilter(b, QEvent(QEvent.Leave))
    assert not f.tip.isVisible()


def test_tooltip_reads_list_rows_and_respects_the_setting(qapp):
    from mynaphone.gui.app import _TipFilter
    win = _Win()
    f = _TipFilter(win)
    lst = QListWidget()
    it = QListWidgetItem("row", lst)
    it.setToolTip("row tip")
    lst.show()
    r = lst.visualItemRect(it)
    ev = QHelpEvent(QEvent.ToolTip, r.center(), lst.viewport().mapToGlobal(r.center()))
    assert f.eventFilter(lst.viewport(), ev) is True and f.tip.text.text() == "row tip"
    f.eventFilter(lst.viewport(), QEvent(QEvent.Leave))
    win.cfg.app.show_tooltips = False
    assert f.eventFilter(lst.viewport(), ev) is True and not f.tip.isVisible()


# -- the window ---------------------------------------------------------------------------

def test_window_opens_with_pages_headers_and_seeded_data(window, qapp):
    assert window.nav.count() == 6 and window.pages.count() == 6
    # no AcoustID key in the test config, so the first run lands on Set up
    assert window.page_title.text() == "Set up" and window.pages.currentIndex() == 5
    window.nav.setCurrentRow(0)
    qapp.processEvents()
    assert window.page_title.text() == "Status" and window.page_sub.text()
    window.nav.setCurrentRow(1)
    qapp.processEvents()
    assert window.page_title.text() == "Activity" and window.pages.currentIndex() == 1
    # recent takes reached both tables, newest first, with the cause and a count in the cell
    assert window.activity.table.rowCount() == 3
    assert window.activity.table.item(0, 3).text() == "playback stalled"
    assert window.activity.table.item(1, 3).text() == "paused during the song, and 2 more"
    assert "player closed" in window.activity.table.item(1, 3).toolTip()
    assert window.status.recent.rowCount() == 3
    assert window.status.tiles["library"].text() == "2"


def test_state_pill_follows_the_recorder(window, qapp):
    st = window.status
    assert st.state.text() == "Stopped" and st.state.property("tone") == "off"
    window.on_event({"kind": "recording", "title": "Song", "artist": "A", "album": "Al",
                     "expected_ms": 1000, "t_event": 0})
    assert st.state.text() == "Recording" and st.state.property("tone") == "rec"
    assert st.title.text() == "Song" and st.progress.isVisibleTo(st)
    window._refresh_state_labels()
    assert st.state.property("tone") == "off"


def test_library_page_lists_songs_and_wraps_missing(window, qapp):
    lib = window.library
    lib.reload()
    qapp.processEvents()
    assert lib.table.rowCount() == 2
    texts = {lib.table.item(r, 0).text(): lib.table.item(r, 1).text() for r in range(2)}
    assert texts["B - Done"] == "Complete"
    assert texts["A - Song"].startswith("Album, Year, Cover art")
    lib.only_incomplete.setChecked(True)
    qapp.processEvents()
    assert lib.table.rowCount() == 1
    lib.table.resize(420, 300)
    lib.table.fit()
    assert lib.table.columnWidth(0) + lib.table.columnWidth(1) == lib.table.viewport().width()
    assert lib.table.rowHeight(0) > 30  # the missing list wrapped onto more than one line


def test_activity_rows_keep_one_line_with_hover_text(window):
    t = window.activity.table
    window.activity.add_row("09:00", "X " * 80, "discard", ("short", "the whole reason"))
    assert t.item(0, 3).text() == "short" and t.item(0, 3).toolTip() == "the whole reason"
    assert t.item(0, 1).toolTip().startswith("X X")
    assert not t.wordWrap()
    assert t.horizontalHeader().maximumSectionSize() == 300


def test_detail_wording():
    from mynaphone.gui.app import _detail
    assert _detail([]) == ("", "")
    assert _detail(["buffering"]) == ("playback stalled", "playback stalled")
    short, full = _detail(["paused", "cut_short"])
    assert short == "paused during the song, and 1 more" and full == "paused during the song, ended early"


# -- single instance ----------------------------------------------------------------------

def test_second_launch_talks_to_the_first(qapp, monkeypatch):
    from PySide6.QtNetwork import QLocalServer

    import mynaphone.gui.app as A
    name = f"mynaphone-test-{os.getpid()}"
    monkeypatch.setattr(A, "INSTANCE_NAME", name)
    assert A._already_running() is False
    QLocalServer.removeServer(name)
    server = QLocalServer()
    assert server.listen(name)
    try:
        assert A._already_running() is True
    finally:
        server.close()


# -- now-playing card ------------------------------------------------------------------------

def test_recording_title_is_not_squeezed(window, qapp):
    st = window.status
    window.nav.setCurrentRow(0)
    qapp.processEvents()
    row = st.title.parentWidget()
    idle_height = row.height()
    window.on_event({"kind": "recording", "artist": "Atif Aslam", "title": "Aadat",
                     "album": "Kalyug (Original Motion Picture Soundtrack)", "expected_ms": 333_000})
    window._tick()
    qapp.processEvents()
    assert st.title.height() >= st.title.sizeHint().height()
    assert st.title.geometry().bottom() < st.sub.geometry().top()
    assert row.height() == idle_height                     # the card doesn't jump when a song starts


def test_previous_songs_verdict_leaves_the_new_recording_on_screen(window):
    """The next song starts recording before the previous one is written out, so its verdict comes later."""
    st = window.status
    window.on_event({"kind": "recording", "artist": "A", "title": "Two", "expected_ms": 200_000})
    window.on_event({"kind": "kept", "artist": "A", "title": "One", "captured_ms": 180_000,
                     "expected_ms": 180_000, "tier": "high"})
    assert window.recording_since is not None and not st.progress.isHidden() and st.title.text() == "Two"
    window.on_event({"kind": "discarded", "artist": "A", "title": "Two", "reasons": ["buffering"]})
    assert window.recording_since is None and st.progress.isHidden()


def test_cover_placeholder_eye_turns_red_while_recording(window):
    from mynaphone.gui.app import COVER_MARK
    st = window.status
    window.on_event({"kind": "recording", "artist": "A", "title": "Two", "expected_ms": 200_000})
    shown = st.cover.pixmap().toImage()
    assert shown == icons.app_icon("recording").pixmap(COVER_MARK, COVER_MARK).toImage()
    assert shown != icons.app_icon("idle").pixmap(COVER_MARK, COVER_MARK).toImage()


# -- coming back from the tray --------------------------------------------------------------

def test_blank_window_is_minimized_and_restored_once(window, monkeypatch, caplog):
    """Windows now and then shows the window from the tray as a white frame; minimizing and restoring fixes it."""
    import logging

    from PySide6.QtGui import QColor
    calls = []
    monkeypatch.setattr(window, "_sidebar_on_screen", lambda: [QColor("#ffffff")] * 3)
    monkeypatch.setattr(window, "showMinimized", lambda: calls.append("minimized"))
    monkeypatch.setattr(window, "_show_and_check", lambda: calls.append("shown"))
    window._blank_heals = 0
    with caplog.at_level(logging.INFO, logger="mynaphone"):
        window._check_painted()
        window._check_painted()                 # still white after the restore: logged, not repeated
        monkeypatch.setattr(window, "_sidebar_on_screen", lambda: [QColor("#1c1b19")] * 3)
        window._check_painted()
    assert calls == ["minimized"]
    said = [r.getMessage() for r in caplog.records if r.name.startswith("mynaphone")]
    assert len(said) == 3
    assert said[0].startswith("the window came up blank") and "sidebar shows #ffffff" in said[0]
    assert said[1].startswith("the window is still blank")
    assert said[2] == "the window filled in after minimizing and restoring it"


def test_painted_or_covered_window_is_left_alone(window, monkeypatch, caplog):
    import logging

    from PySide6.QtGui import QColor
    calls = []
    monkeypatch.setattr(window, "showMinimized", lambda: calls.append("minimized"))
    window._blank_heals = 0
    with caplog.at_level(logging.INFO, logger="mynaphone"):
        assert window._sidebar_on_screen() is None      # offscreen: no real window to find on the desktop
        window._check_painted()
        monkeypatch.setattr(window, "_sidebar_on_screen", lambda: [QColor("#1c1b19"), QColor("#ffffff")] * 2)
        window._check_painted()                 # one dark spot is enough: a tooltip may cover another
    assert calls == []
    assert not [r for r in caplog.records if r.name.startswith("mynaphone")]


def test_every_reason_the_recorder_gives_has_words():
    """A skip or discard reason shows up raw in the Takes table unless _humanize knows it."""
    import re

    from mynaphone.gui.app import _humanize
    root = Path(__file__).resolve().parents[1] / "mynaphone"
    src = (root / "daemon.py").read_text(encoding="utf-8") + (root / "takes.py").read_text(encoding="utf-8")
    codes = set(re.findall(r'reason="([a-z_]+)"', src))
    codes |= set(re.findall(r'reason="[a-z_]+" if [^\n]*?else "([a-z_]+)"', src))
    codes |= set(re.findall(r'reasons\.append\(f?"([a-z_]+)', src))
    for group in re.findall(r'reason in \(([^)]*)\)', src):
        codes |= set(re.findall(r'"([a-z_]+)"', group))
    assert {"capture_not_ready", "browser_unverified", "buffering", "already_archived", "stopped"} <= codes
    assert not sorted(c for c in codes if _humanize(c) == c)
