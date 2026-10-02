# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows media-session (SMTC) listener.

Turns GlobalSystemMediaTransportControlsSessionManager callbacks into asyncio queue events and
offers snapshot() to read the current track, playback status and timeline of a session.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any

from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as Manager,
)
from winrt.windows.storage.streams import Buffer, DataReader, InputStreamOptions

log = logging.getLogger("mynaphone.smtc")

# GlobalSystemMediaTransportControlsSessionPlaybackStatus values
CLOSED, OPENED, CHANGING, STOPPED, PLAYING, PAUSED = 0, 1, 2, 3, 4, 5
STATUS_NAMES = {0: "closed", 1: "opened", 2: "changing", 3: "stopped", 4: "playing", 5: "paused"}


@dataclass
class Snapshot:
    app: str
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    track_number: int = 0
    status: int = CLOSED
    rate: float = 1.0
    position_ms: int = 0           # as of last_updated
    end_ms: int = 0                # duration
    last_updated: dt.datetime | None = None
    thumbnail: bytes | None = None
    taken_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.artist.strip().lower(), self.title.strip().lower(), self.album.strip().lower())

    @property
    def status_name(self) -> str:
        return STATUS_NAMES.get(self.status, str(self.status))

    def expected_position_ms(self, now: dt.datetime | None = None) -> int:
        """Position extrapolated from the last timeline update using wall-clock time."""
        if self.last_updated is None:
            return self.position_ms
        now = now or dt.datetime.now(dt.timezone.utc)
        if self.status != PLAYING:
            return self.position_ms
        elapsed = (now - self.last_updated).total_seconds() * 1000.0 * (self.rate or 1.0)
        return int(self.position_ms + max(elapsed, 0))

    def describe(self) -> str:
        return f"{self.artist} - {self.title} [{self.album}] ({self.end_ms/1000:.1f}s) {self.status_name}"


@dataclass
class SmtcEvent:
    kind: str          # "media" | "playback" | "timeline" | "sessions"
    app: str
    session: Any = None


async def _read_thumbnail(ref) -> bytes | None:
    try:
        stream = await ref.open_read_async()
        size = int(stream.size)
        if size <= 0:
            return None
        buf = Buffer(size)
        out = await stream.read_async(buf, size, InputStreamOptions.READ_AHEAD)
        n = int(out.length)
        if n <= 0:
            return None
        try:
            return bytes(memoryview(out))[:n]
        except TypeError:
            reader = DataReader.from_buffer(out)
            return bytes(reader.read_buffer(n))
    except Exception as e:  # thumbnails are best-effort
        log.debug("thumbnail read failed: %s", e)
        return None


def _td_ms(td) -> int:
    try:
        return int(td.total_seconds() * 1000)
    except Exception:
        return 0


async def snapshot(session, with_thumbnail: bool = False) -> Snapshot:
    app = session.source_app_user_model_id or ""
    snap = Snapshot(app=app)
    try:
        props = await session.try_get_media_properties_async()
        if props is not None:
            snap.title = props.title or ""
            snap.artist = props.artist or ""
            snap.album = props.album_title or ""
            snap.album_artist = props.album_artist or ""
            snap.track_number = int(props.track_number or 0)
            if with_thumbnail and props.thumbnail is not None:
                snap.thumbnail = await _read_thumbnail(props.thumbnail)
    except Exception as e:
        log.debug("media properties unavailable for %s: %s", app, e)
    try:
        pb = session.get_playback_info()
        snap.status = int(pb.playback_status)
        snap.rate = float(pb.playback_rate) if pb.playback_rate is not None else 1.0
    except Exception as e:
        log.debug("playback info unavailable for %s: %s", app, e)
    try:
        tl = session.get_timeline_properties()
        snap.position_ms = _td_ms(tl.position)
        snap.end_ms = _td_ms(tl.end_time)
        lu = tl.last_updated_time
        snap.last_updated = lu if isinstance(lu, dt.datetime) else None
        if snap.last_updated is not None and snap.last_updated.tzinfo is None:
            snap.last_updated = snap.last_updated.replace(tzinfo=dt.timezone.utc)
    except Exception as e:
        log.debug("timeline unavailable for %s: %s", app, e)
    return snap


class SmtcListener:
    """Hooks every media session and forwards change notifications to an asyncio queue."""

    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
        self.loop = loop
        self.queue = queue
        self.manager = None
        self._hooked: list[tuple[Any, list[tuple[str, int]]]] = []
        self._sessions_token = None

    async def start(self) -> None:
        self.manager = await Manager.request_async()
        self._sessions_token = self.manager.add_sessions_changed(self._on_sessions_changed)
        self._rehook()
        log.info("media-session listener started (%d sessions)", len(self._hooked))

    def stop(self) -> None:
        self._unhook_all()
        if self.manager is not None and self._sessions_token is not None:
            try:
                self.manager.remove_sessions_changed(self._sessions_token)
            except Exception:
                pass

    def sessions(self) -> list[Any]:
        try:
            return list(self.manager.get_sessions()) if self.manager else []
        except Exception as e:
            log.warning("get_sessions failed: %s", e)
            return []

    # -- internals -------------------------------------------------------------------------

    def _emit(self, kind: str, session) -> None:
        try:
            app = session.source_app_user_model_id or ""
        except Exception:
            app = ""
        self.loop.call_soon_threadsafe(self.queue.put_nowait, SmtcEvent(kind, app, session))

    def _on_sessions_changed(self, manager, args) -> None:
        self.loop.call_soon_threadsafe(self._rehook)
        self.loop.call_soon_threadsafe(self.queue.put_nowait, SmtcEvent("sessions", "", None))

    def _unhook_all(self) -> None:
        for session, tokens in self._hooked:
            for name, token in tokens:
                try:
                    getattr(session, f"remove_{name}")(token)
                except Exception:
                    pass
        self._hooked.clear()

    def _rehook(self) -> None:
        self._unhook_all()
        for s in self.sessions():
            tokens = []
            try:
                tokens.append(("media_properties_changed",
                               s.add_media_properties_changed(lambda sess, a: self._emit("media", sess))))
                tokens.append(("playback_info_changed",
                               s.add_playback_info_changed(lambda sess, a: self._emit("playback", sess))))
                tokens.append(("timeline_properties_changed",
                               s.add_timeline_properties_changed(lambda sess, a: self._emit("timeline", sess))))
            except Exception as e:
                log.warning("could not hook session: %s", e)
            self._hooked.append((s, tokens))
