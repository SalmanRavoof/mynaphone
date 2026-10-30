# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""The media-session listener with stand-ins for Windows' session manager and sessions."""
import asyncio

from mynaphone import smtc as S


class FakeSession:
    source_app_user_model_id = "Spotify.exe"

    def __init__(self):
        self.handlers = {}
        self.added = 0
        self.removed = 0

    def _add(self, name, fn):
        self.added += 1
        self.handlers[name] = fn
        return self.added

    def add_media_properties_changed(self, fn):
        return self._add("media", fn)

    def add_playback_info_changed(self, fn):
        return self._add("playback", fn)

    def add_timeline_properties_changed(self, fn):
        return self._add("timeline", fn)

    def remove_media_properties_changed(self, token):
        self.removed += 1

    def remove_playback_info_changed(self, token):
        self.removed += 1

    def remove_timeline_properties_changed(self, token):
        self.removed += 1


class FakeManager:
    def __init__(self, sessions):
        self._sessions = sessions
        self.on_sessions_changed = None
        self.removed = False

    def add_sessions_changed(self, fn):
        self.on_sessions_changed = fn
        return 7

    def remove_sessions_changed(self, token):
        self.removed = True

    def get_sessions(self):
        return list(self._sessions)


def started_listener(monkeypatch, loop, queue, session):
    manager = FakeManager([session])

    async def request_async():
        return manager

    monkeypatch.setattr(S.Manager, "request_async", request_async, raising=False)
    listener = S.SmtcListener(loop, queue)
    loop.run_until_complete(listener.start())
    return listener, manager


def test_stop_unhooks_and_lets_go_of_windows_objects(monkeypatch):
    loop = asyncio.new_event_loop()
    try:
        queue = asyncio.Queue()
        session = FakeSession()
        listener, manager = started_listener(monkeypatch, loop, queue, session)
        assert session.added == 3
        listener.stop()
        assert session.removed == 3 and manager.removed
        assert listener.manager is None and listener.sessions() == []
    finally:
        loop.close()


def test_changes_reported_after_stop_do_nothing(monkeypatch):
    """Windows can report a change while the app shuts down. It mustn't hook the sessions again or queue an event,
    even when the event loop has already closed."""
    loop = asyncio.new_event_loop()
    queue = asyncio.Queue()
    session = FakeSession()
    listener, manager = started_listener(monkeypatch, loop, queue, session)
    media_changed = session.handlers["media"]
    # a sessions change arrives just before the stop; its rehook runs on the loop after it
    manager.on_sessions_changed(manager, None)
    listener.stop()
    loop.run_until_complete(asyncio.sleep(0))
    assert session.added == 3
    loop.close()
    manager.on_sessions_changed(manager, None)          # after the loop closed: no RuntimeError either
    media_changed(session, None)
    assert session.added == 3


def test_events_reach_the_queue_while_running(monkeypatch):
    loop = asyncio.new_event_loop()
    try:
        queue = asyncio.Queue()
        session = FakeSession()
        listener, _ = started_listener(monkeypatch, loop, queue, session)
        session.handlers["timeline"](session, None)
        loop.run_until_complete(asyncio.sleep(0))
        ev = queue.get_nowait()
        assert ev.kind == "timeline" and ev.app == "Spotify.exe"
        listener.stop()
    finally:
        loop.close()
