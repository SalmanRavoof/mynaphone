# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Local WebSocket bridge for the Spicetify extension.

The extension pushes Spotify's own player state (exact track uri, duration, position, paused,
buffering, quality tier, album/artist uris, cover url). The daemon treats it as an enrichment of
the Windows media-session signal for Spotify.exe and as the authoritative quality-tier source.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field

import websockets

log = logging.getLogger("mynaphone.bridge")


@dataclass
class SpotifyState:
    uri: str = ""
    name: str = ""
    artists: list[dict] = field(default_factory=list)
    album: dict | None = None
    image: str = ""
    duration_ms: int = 0
    position_ms: int = 0
    is_paused: bool = True
    is_buffering: bool = False
    quality: dict | None = None
    playback_id: str = ""
    metadata: dict = field(default_factory=dict)
    next_items: list[dict] = field(default_factory=list)
    album_info: dict | None = None
    track_info: dict | None = None
    volume: float | None = None   # Spotify's own volume slider, 0..1
    received_at: float = 0.0      # monotonic
    client_ts: int = 0

    @property
    def artist_names(self) -> str:
        return ", ".join(a.get("name", "") for a in self.artists if a.get("name"))

    # Spotify desktop bitrateLevel enum, as observed in Spicetify.Player.data.playbackQuality.
    # Free accounts top out at 3 (High, ~160 kbps Vorbis); Premium 4 (Very High, ~320); 5/6 lossless.
    LEVELS = {0: "unknown", 1: "low", 2: "normal", 3: "high", 4: "very_high", 5: "hifi", 6: "hifi24"}

    @property
    def tier(self) -> str:
        q = self.quality or {}
        if int(q.get("losslessStatus") or 0) > 0 and q.get("bitrateLevel") is None:
            return "hifi"
        for k in ("bitrateLevel", "bitrate_level", "targetBitrateLevel", "target_bitrate_level"):
            v = q.get(k)
            if v is None:
                continue
            if isinstance(v, (int, float)) or str(v).isdigit():
                return self.LEVELS.get(int(v), "unknown")
            return str(v).lower()
        return "unknown"

    @property
    def fresh(self) -> bool:
        return self.received_at and (time.monotonic() - self.received_at) < 5.0


@dataclass
class BridgeEvent:
    kind: str = "bridge"
    app: str = "Spotify.exe"
    state: SpotifyState | None = None
    previous: SpotifyState | None = None


@dataclass
class YouTubeState:
    """What the browser extension reports for the YouTube tab that is playing."""
    video_id: str = ""
    url: str = ""
    host: str = ""
    title: str = ""
    channel: str = ""
    genre: str = ""
    is_music: bool = False
    duration_s: float = 0.0
    position_s: float = 0.0
    paused: bool = True
    seeking: bool = False
    ended: bool = False
    rate: float = 1.0
    volume: float | None = None     # the page's player volume, 0..1
    muted: bool = False
    music: dict | None = None       # music.youtube.com player-bar fields: title, artist, album, year
    description: str = ""           # the video description, where labels list song credits
    event: str = ""
    received_at: float = 0.0
    client_ts: int = 0

    @property
    def fresh(self) -> bool:
        return self.received_at and (time.monotonic() - self.received_at) < 5.0


def _clean_music(m):
    """Drop byline fragments such as '54M views' that an older extension may report as the album."""
    if not isinstance(m, dict):
        return m
    from .identify import looks_like_count
    out = dict(m)
    for k in ("album", "artist", "title"):
        if looks_like_count(out.get(k) or ""):
            out[k] = ""
    return out


@dataclass
class YouTubeEvent:
    kind: str = "youtube"
    state: YouTubeState | None = None
    previous: YouTubeState | None = None


class Bridge:
    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue, port: int, on_status=None):
        self.loop = loop
        self.queue = queue
        self.port = port
        self.state = SpotifyState()
        self.lyrics: dict[str, dict] = {}       # track uri -> {"lrc": str, "synced": bool, "language": str}
        self.youtube = YouTubeState()
        self.youtube_connected = False
        self.buffering_seen_since: float | None = None
        self.connected = False
        self._server = None
        self._on_status = on_status
        self._detail_errors: set[tuple[str, str]] = set()

    def _details(self, info, kind: str, uri: str) -> dict | None:
        """The bridge's album or track details, or None. A failed lookup is logged once per item, never stored."""
        if not isinstance(info, dict) or not info:
            return None
        if info.get("error"):
            if (kind, uri) not in self._detail_errors:
                self._detail_errors.add((kind, uri))
                text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(info["error"]))[:300]
                log.info("Spotify could not give %s details for %s: %s", kind, uri, text)
            return None
        log.debug("%s details for %s from Spotify's %s", kind, uri, info.get("source", "bridge"))
        return info

    def _status(self, connected: bool) -> None:
        self.connected = connected
        if self._on_status:
            try:
                self._on_status(connected)
            except Exception:
                log.exception("bridge status listener failed")

    async def start(self) -> None:
        self._server = await websockets.serve(self._handler, "127.0.0.1", self.port)
        log.info("bridge listening on ws://127.0.0.1:%d", self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handler(self, ws):
        path = ""
        try:
            path = ws.request.path
        except Exception:
            try:
                path = ws.path
            except Exception:
                pass
        if path.startswith("/youtube"):
            await self._youtube_handler(ws)
            return
        self._status(True)
        log.info("spicetify extension connected")
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if msg.get("type") == "lyrics":
                    self._store_lyrics(msg)
                    continue
                if msg.get("type") != "state":
                    continue
                prev = self.state
                st = SpotifyState(
                    uri=msg.get("uri", "") or "",
                    name=msg.get("name", "") or "",
                    artists=msg.get("artists") or [],
                    album=msg.get("album"),
                    image=msg.get("image", "") or "",
                    duration_ms=int(msg.get("duration") or 0),
                    position_ms=int(msg.get("position") or 0),
                    is_paused=bool(msg.get("isPaused", True)),
                    is_buffering=bool(msg.get("isBuffering", False)),
                    quality=msg.get("quality"),
                    playback_id=msg.get("playbackId", "") or "",
                    metadata=msg.get("metadata") or {},
                    next_items=msg.get("next") or [],
                    album_info=self._details(msg.get("albumInfo"), "album", (msg.get("album") or {}).get("uri", "")),
                    track_info=self._details(msg.get("trackInfo"), "track", msg.get("uri", "")),
                    volume=(float(msg["volume"]) if msg.get("volume") is not None else None),
                    received_at=time.monotonic(),
                    client_ts=int(msg.get("ts") or 0),
                )
                self.state = st
                changed = (st.uri != prev.uri or st.playback_id != prev.playback_id
                           or st.is_paused != prev.is_paused or st.is_buffering != prev.is_buffering
                           or (st.album_info is not None and prev.album_info is None)
                           or (st.track_info is not None and prev.track_info is None))
                if changed:
                    self.queue.put_nowait(BridgeEvent(state=st, previous=prev))
        except websockets.ConnectionClosed:
            pass
        finally:
            self._status(False)
            log.info("spicetify extension disconnected")

    def _store_lyrics(self, msg: dict) -> None:
        uri = msg.get("uri") or ""
        info = msg.get("lyrics") or {}
        lines = info.get("lines") or []
        if not uri or not lines:
            return
        synced = bool(info.get("synced"))
        out = []
        for ln in lines:
            words = (ln.get("w") or "").strip()
            if synced and ln.get("t") is not None:
                ms = int(ln["t"])
                out.append(f"[{ms // 60000:02d}:{(ms % 60000) // 1000:02d}.{(ms % 1000) // 10:02d}]{words}")
            elif words:
                out.append(words)
        text = "\n".join(out).strip()
        if not text:
            return
        self.lyrics[uri] = {"lrc": text, "synced": synced, "language": info.get("language") or "",
                            "provider": info.get("provider") or ""}
        if len(self.lyrics) > 300:
            self.lyrics.pop(next(iter(self.lyrics)))
        log.info("lyrics from spotify (%s, %s) for %s", "synced" if synced else "plain",
                 info.get("language") or "?", uri)
        self.loop.call_soon_threadsafe(self.queue.put_nowait, BridgeEvent(kind="lyrics", state=self.state))

    async def _youtube_handler(self, ws):
        self.youtube_connected = True
        log.info("browser extension connected")
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if msg.get("type") != "youtube":
                    continue
                prev = self.youtube
                st = YouTubeState(
                    video_id=msg.get("videoId", "") or "", url=msg.get("url", "") or "", host=msg.get("host", "") or "",
                    title=msg.get("title", "") or "", channel=msg.get("channel", "") or "",
                    genre=msg.get("genre", "") or "",
                    is_music=bool(msg.get("isMusic")), duration_s=float(msg.get("duration") or 0),
                    position_s=float(msg.get("position") or 0), paused=bool(msg.get("paused", True)),
                    seeking=bool(msg.get("seeking")), ended=bool(msg.get("ended")),
                    rate=float(msg.get("playbackRate") or 1),
                    volume=(float(msg["volume"]) if msg.get("volume") is not None else None),
                    muted=bool(msg.get("muted")),
                    music=_clean_music(msg.get("music")), description=(msg.get("description") or "")[:4000],
                    event=msg.get("event", "") or "", received_at=time.monotonic(),
                    client_ts=int(msg.get("ts") or 0),
                )
                # a background tab that is paused must not override the tab that is playing
                if st.paused and not prev.paused and st.video_id != prev.video_id and prev.fresh:
                    continue
                self.youtube = st
                changed = (st.video_id != prev.video_id or st.paused != prev.paused or st.ended != prev.ended
                           or st.event in ("seeking", "seeked", "ratechange"))
                if changed:
                    self.queue.put_nowait(YouTubeEvent(state=st, previous=prev))
        except websockets.ConnectionClosed:
            pass
        finally:
            self.youtube_connected = False
            log.info("browser extension disconnected")
