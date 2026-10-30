# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI tests, run offscreen: the theme, the mark, tooltips, page headers, state pills, tables, shortcuts
and the single-instance guard. No recorder is started and no audio is touched."""
import ast
import itertools
import os
import subprocess
import sys
import time
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

_PIPES = itertools.count()


@pytest.fixture(autouse=True)
def _own_pipe(monkeypatch):
    """No test may reach the Mynaphone running on this PC: "quit" would close it, and a copy from before the quit
    command shows its window for any message."""
    import mynaphone.gui.app as A
    monkeypatch.setattr(A, "INSTANCE_NAME", f"mynaphone-test-{os.getpid()}-{next(_PIPES)}")


def _from_another_launch(qapp, code: str):
    """Run code in a second Python, as another launch would, while this process answers the pipe, and return the
    value of its last line. (A pipe client on a thread of this process never sends.)"""
    import mynaphone.gui.app as A
    *body, last = code.strip().splitlines()
    script = "\n".join(["import mynaphone.gui.app as A", f"A.INSTANCE_NAME = {A.INSTANCE_NAME!r}", *body,
                        f"print(repr({last}))"])
    proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    try:
        deadline = time.monotonic() + 30
        while proc.poll() is None and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.005)
        out, err = proc.communicate(timeout=5)
    finally:
        proc.kill()
    assert proc.returncode == 0, err
    return ast.literal_eval(out.strip().splitlines()[-1])


def test_second_launch_talks_to_the_first(qapp, monkeypatch):
    from PySide6.QtNetwork import QLocalServer

    import mynaphone.gui.app as A
    name = f"mynaphone-test-{os.getpid()}"
    monkeypatch.setattr(A, "INSTANCE_NAME", name)
    monkeypatch.setattr(A, "ANSWER_WAIT_MS", 50)      # a bare server never answers
    assert A._already_running() is False
    QLocalServer.removeServer(name)
    server = QLocalServer()
    assert server.listen(name)
    try:
        assert A._already_running() is True
    finally:
        server.close()


def test_quitting_says_why_in_the_log(window, qapp, caplog, monkeypatch):
    """Two stops in October left no trace of who quit the app."""
    import logging
    monkeypatch.setattr(qapp, "quit", lambda: None)
    with caplog.at_level(logging.INFO, logger="mynaphone.gui"):
        window.quit_app("Quit in the tray menu")
    assert "quitting: Quit in the tray menu" in caplog.text


def test_second_launch_lets_the_first_come_to_the_front(qapp, monkeypatch):
    """Windows lets only the app just clicked raise a window, so the second launch passes that right on."""
    from PySide6.QtNetwork import QLocalServer

    import mynaphone.gui.app as A
    name = f"mynaphone-test-front-{os.getpid()}"
    monkeypatch.setattr(A, "INSTANCE_NAME", name)
    monkeypatch.setattr(A, "ANSWER_WAIT_MS", 50)
    allowed = []
    monkeypatch.setattr(A._user32, "AllowSetForegroundWindow", allowed.append)
    QLocalServer.removeServer(name)
    server = QLocalServer()
    assert server.listen(name)
    try:
        assert A._already_running() is True
    finally:
        server.close()
    assert allowed == [os.getpid()]         # the server end of the pipe, here this same process


def test_second_launch_brings_the_window_back(window, qapp, monkeypatch):
    import mynaphone.gui.app as A
    shown = []
    monkeypatch.setattr(window, "show_from_tray", lambda: shown.append(True))
    server = A._listen_for_launches(window)
    try:
        assert _from_another_launch(qapp, "A._already_running()") is True
    finally:
        server.close()
    assert shown == [True]


def test_quit_command_asks_the_running_copy_to_quit(window, qapp, monkeypatch):
    """Restarts used to end the process, which left a dead icon in the tray until the mouse passed over it."""
    import mynaphone.gui.app as A
    asked = []
    monkeypatch.setattr(window, "quit_app", asked.append)
    server = A._listen_for_launches(window)
    try:
        assert _from_another_launch(qapp, "A._tell_running_copy(b'quit')") == (os.getpid(), b"quitting")
    finally:
        server.close()
    assert asked == ["mynaphone quit asked it to"]


def test_a_launch_while_quitting_waits_and_then_opens(window, qapp, monkeypatch):
    """Opened in the 20 seconds it takes to quit, Mynaphone brought back the old copy's window, which then closed
    with it."""
    import mynaphone.gui.app as A
    shown = []
    monkeypatch.setattr(window, "show_from_tray", lambda: shown.append(True))
    window._quitting = True
    server = A._listen_for_launches(window)
    try:
        # the second launch finds the old copy gone as soon as it waits
        got = _from_another_launch(qapp, "waited = []\n"
                                         "A._wait_for_exit = lambda pid, seconds: waited.append(pid) or True\n"
                                         "(A._already_running(), waited)")
    finally:
        server.close()
    assert got == (False, [os.getpid()]) and shown == []       # False, so that launch opens its own window


def test_a_copy_that_never_answers_is_named(qapp, monkeypatch):
    from PySide6.QtNetwork import QLocalServer

    import mynaphone.gui.app as A
    monkeypatch.setattr(A, "ANSWER_WAIT_MS", 50)
    server = QLocalServer()
    assert server.listen(A.INSTANCE_NAME)
    try:
        assert A.quit_running_copy(0.2) == "no answer"      # the copy is this test's own process, which stays up
    finally:
        server.close()


def test_waiting_for_a_copy_to_close():
    import mynaphone.gui.app as A
    quick = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.3)"])
    slow = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert A._wait_for_exit(quick.pid, 10) is True
        assert A._wait_for_exit(slow.pid, 0.2) is False
    finally:
        slow.kill()
        quick.wait()
        slow.wait()
    assert A._wait_for_exit(A.ASFW_ANY, 0.2) is True        # no process named, and no pipe left to watch


def test_quit_command_with_nothing_running(capsys):
    from mynaphone.__main__ import main
    assert main(["quit"]) == 0
    assert capsys.readouterr().out.strip() == "Mynaphone isn't running."


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
    window.check_painted_soon()
    with caplog.at_level(logging.INFO, logger="mynaphone"):
        assert window._sidebar_on_screen() is None      # offscreen: no real window to find on the desktop
        window._check_painted()
        window._check_painted()                 # why it couldn't look is said once each time it looks
        monkeypatch.setattr(window, "_sidebar_on_screen", lambda: [QColor("#1c1b19"), QColor("#ffffff")] * 2)
        window._check_painted()                 # one dark spot is enough: a tooltip may cover another
    assert calls == []
    said = [r.getMessage() for r in caplog.records if r.name.startswith("mynaphone")]
    assert len(said) == 1 and said[0].startswith("couldn't check the window: ")


def test_coming_back_from_the_taskbar_or_waking_up_checks_the_window(window, caplog):
    """The white window seen in late October came back some other way than from the tray."""
    import ctypes
    import logging
    from ctypes import wintypes

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QWindowStateChangeEvent

    from mynaphone.gui import app as A
    window._paint_timer.stop()
    window.changeEvent(QWindowStateChangeEvent(Qt.WindowMinimized))
    assert window._paint_timer.isActive()
    window._paint_timer.stop()
    msg = wintypes.MSG()
    msg.message, msg.wParam = A.WM_POWERBROADCAST, A.PBT_APMRESUMEAUTOMATIC
    with caplog.at_level(logging.INFO, logger="mynaphone"):
        window.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg))
    assert window._paint_timer.isActive()
    assert "Windows woke up from sleep" in [r.getMessage() for r in caplog.records]


def test_numpy_keeps_one_maths_thread():
    """With one thread per CPU, importing numpy set aside 490 MB of Windows' memory on a 16-thread PC."""
    code = "import os, mynaphone.takes; print(os.environ['OPENBLAS_NUM_THREADS'])"
    env = {k: v for k, v in os.environ.items() if k != "OPENBLAS_NUM_THREADS"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert out.stdout.strip() == "1", out.stderr


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


def test_start_with_windows_command_opens_the_window(window, monkeypatch):
    """Start with Windows never started the app: its entry put --config after gui, which the command line refused."""
    import shlex

    import mynaphone.__main__ as cli
    seen = []
    monkeypatch.setattr(cli, "cmd_gui", lambda args: seen.append((args.config, args.minimized)) or 0)
    for in_tray in (True, False):           # "When Windows starts it, open in the tray"
        window.cfg.app.start_minimized = in_tray
        words = [w.strip('"') for w in shlex.split(window._login_command(), posix=False)]
        assert words[1:3] == ["-m", "mynaphone"]
        assert cli.main(words[3:]) == 0
    old = ["gui", "--config", str(window.config_path), "--minimized"]      # as earlier versions wrote it
    assert cli.main(old) == 0
    assert seen == [(str(window.config_path), True), (str(window.config_path), False),
                    (str(window.config_path), True)]


def test_opening_the_app_by_hand_shows_the_window(qapp, gui_config, monkeypatch):
    """With "Open minimized to the tray" ticked, the desktop shortcut started Mynaphone hidden, and opening it
    showed nothing (21 October 2026). Only Start with Windows, which passes --minimized, opens it in the tray."""
    from PySide6.QtCore import QObject

    import mynaphone.gui.app as A
    gui_config.write_text(gui_config.read_text(encoding="utf-8").replace("start_minimized = false",
                                                                         "start_minimized = true"), encoding="utf-8")
    opened = []

    class FakeWindow(QObject):
        def __init__(self, config_path, start_minimized=False):
            super().__init__()
            opened.append(start_minimized)

        def show_from_tray(self):
            pass

    monkeypatch.setattr(A, "MainWindow", FakeWindow)
    monkeypatch.setattr(qapp, "exec", lambda: 0)
    for minimized in (False, True):
        # a name of its own, so the test never reaches the Mynaphone running on this PC
        monkeypatch.setattr(A, "INSTANCE_NAME", f"mynaphone-test-open-{os.getpid()}-{minimized}")
        assert A.run_gui(gui_config, minimized=minimized) == 0
    assert opened == [False, True]


def test_tray_at_sign_in_is_a_start_with_windows_option(window):
    s = window.settings
    s.ck_login.setChecked(True)
    assert s.ck_minimized.isEnabled()
    s.ck_login.setChecked(False)
    assert not s.ck_minimized.isEnabled()


def test_start_menu_shortcut_opens_the_window_and_shares_its_taskbar_button(window, tmp_path, monkeypatch):
    import shlex

    import mynaphone.__main__ as cli
    from mynaphone import shortcuts
    monkeypatch.setattr(shortcuts, "shortcut_path", lambda place: tmp_path / place / shortcuts.LINK_NAME)
    monkeypatch.setattr(window, "_set_login_item", lambda enabled: None)      # leave the real startup list alone
    s = window.settings
    s.ck_start_menu.setChecked(True)
    s.ck_desktop.setChecked(False)
    window.save_settings()
    link = shortcuts.read_link(tmp_path / "start_menu" / shortcuts.LINK_NAME)
    assert not (tmp_path / "desktop" / shortcuts.LINK_NAME).exists()
    assert link["app_id"] == shortcuts.APP_ID
    assert Path(link["target"]) == shortcuts.interpreter() and Path(link["icon"]).exists()
    seen = []
    monkeypatch.setattr(cli, "cmd_gui", lambda args: seen.append((args.config, args.minimized)) or 0)
    words = [w.strip('"') for w in shlex.split(link["arguments"], posix=False)]
    assert words[:2] == ["-m", "mynaphone"]
    assert cli.main(words[2:]) == 0
    assert seen == [(str(window.config_path), False)]
    s.ck_start_menu.setChecked(False)
    window.save_settings()
    assert not (tmp_path / "start_menu" / shortcuts.LINK_NAME).exists()


def test_shortcut_command_adds_and_removes_shortcuts(gui_config, tmp_path, monkeypatch):
    import mynaphone.__main__ as cli
    from mynaphone import shortcuts
    monkeypatch.setattr(shortcuts, "shortcut_path", lambda place: tmp_path / place / shortcuts.LINK_NAME)
    assert cli.main(["--config", str(gui_config), "shortcut"]) == 0
    assert (tmp_path / "start_menu" / shortcuts.LINK_NAME).exists() and not (tmp_path / "desktop").exists()
    assert cli.main(["--config", str(gui_config), "shortcut", "--desktop"]) == 0
    assert (tmp_path / "desktop" / shortcuts.LINK_NAME).exists()
    assert cli.main(["--config", str(gui_config), "shortcut", "--remove"]) == 0
    assert not list(tmp_path.glob("*/*.lnk"))
    assert cli.main(["--config", str(tmp_path / "missing.toml"), "shortcut"]) == 1     # a shortcut that opens nothing


def test_taskbar_identity_matches_the_shortcuts():
    import ctypes

    from mynaphone import shortcuts
    shortcuts.set_app_id()
    shell32 = ctypes.WinDLL("shell32")
    out = ctypes.c_void_p()
    assert shell32.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(out)) == 0
    try:
        assert ctypes.wstring_at(out.value) == shortcuts.APP_ID
    finally:
        ctypes.WinDLL("ole32").CoTaskMemFree(out)


def test_songs_to_play_again_open_from_the_status_page(window, monkeypatch):
    from mynaphone.gui import play_again
    from mynaphone.gui.app import _detail
    from mynaphone.store import Store
    st = Store(window.cfg.paths.db_path)
    seeded = len(st.songs_to_play_again())
    st.log_take(started_at="2026-10-04T10:00:00+00:00", artist="Pritam", title="Tere Bin",
                source_uri="spotify:track:tb", verdict="discard", reasons=["paused", "stopped"])
    st.log_take(started_at="2026-10-06T10:00:00+00:00", artist="A.R. Rahman", title="Main Vari Vari",
                source_uri="", verdict="discard", reasons=["started_mid_track:4461ms"])
    window._load_recent()
    assert window.status.btn_again.text() == f"{seeded + 2} songs to play again"
    assert not window.status.btn_again.isHidden()
    dlg = play_again.PlayAgainDialog(window.cfg.paths.db_path, _detail)
    assert dlg.table.rowCount() == seeded + 2
    assert dlg.table.item(0, 0).text() == "A.R. Rahman - Main Vari Vari"
    assert dlg.table.item(0, 1).text() == "started mid-song"
    opened = []
    monkeypatch.setattr(play_again.os, "startfile", opened.append)
    dlg.open_selected()
    assert opened == ["spotify:search:A.R.%20Rahman%20Main%20Vari%20Vari"]     # no Spotify id, so a search
    dlg.table.selectRow(1)
    dlg.open_selected()
    assert opened[-1] == "spotify:track:tb"
    dlg.hide_selected()
    assert dlg.table.rowCount() == seeded + 1
    for _ in range(seeded + 1):
        dlg.hide_selected()
    window._load_recent()
    assert dlg.table.rowCount() == 0 and window.status.btn_again.isHidden()
    dlg.deleteLater()


def test_record_a_playlist_from_the_status_page(window, monkeypatch):
    import asyncio

    from mynaphone.gui import playlist_dialog as PD
    assert PD.spotify_uri("https://open.spotify.com/intl-es/playlist/37i9dQZF1DXcBWIGoYBM5M?si=ab") == \
        "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"
    assert PD.spotify_uri("spotify:album:4aawyAB9vmqN3uQ7FjRGTy") == "spotify:album:4aawyAB9vmqN3uQ7FjRGTy"
    assert PD.spotify_uri("https://example.com/playlist") == ""

    class Recorder:
        async def list_playlists(self):
            return {"liked": {"uri": "spotify:collection:tracks", "name": "Liked Songs", "total": 412},
                    "playlists": [{"uri": "spotify:playlist:p", "name": "Car Songs", "total": 3}]}

        async def check_playlist(self, uri):
            return {"uri": uri, "tracks": [], "total": 3, "have": [0], "todo": [1, 2], "unplayable": []}

    def ask(make, token):
        window.worker_answer.emit(token, asyncio.run(make(Recorder())), "")
        return True

    started = []
    monkeypatch.setattr(window, "ask_recorder", ask)
    monkeypatch.setattr(window, "start_playlist", lambda uri, name: started.append((uri, name)))
    dlg = PD.PlaylistDialog(window)
    assert dlg.table.rowCount() == 2 and dlg.table.item(0, 0).text() == "Liked Songs"
    assert not dlg.btn_record.isEnabled()
    dlg.table.selectRow(1)
    assert dlg.summary.text() == "1 of 3 songs are in your library. 2 to record."
    assert dlg.btn_record.isEnabled()
    dlg.record()
    assert started == [("spotify:playlist:p", "Car Songs")]
    dlg.deleteLater()

    window._show_job({"name": "Car Songs", "saved": 1, "left": 1, "failed": 0, "current": "Ratata", "done": False})
    assert window.status.btn_playlist.text() == "Stop the playlist"
    assert window.status.job_line.text() == "Recording Car Songs: 1 saved, 1 to go, now Ratata."
    window._show_job({"name": "Car Songs", "saved": 1, "left": 0, "failed": 1, "done": True, "why": "done"})
    assert window.status.btn_playlist.text() == "Record a playlist" and window.job is None
    assert window.status.job_line.text() == \
        "Car Songs: done. 1 song saved, 1 didn't record (they're on the list to play again)."
