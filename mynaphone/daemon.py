# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""The recorder state machine: media-session events in, verified takes out."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import smtc as S
from .bridge import Bridge, BridgeEvent, SpotifyState, YouTubeEvent, YouTubeState
from .capture import LoopbackCapture, ProcessCapture, Take
from .config import Config
from .postprocess import PostProcessor
from .sessions import ForeignAudioMonitor, app_session_volume
from .store import Store, tier_rank
from .takes import TakeMeta, judge, longest_hole_ms, output_path, sidecar, tag_flac, trim, write_flac

log = logging.getLogger("mynaphone")


@dataclass
class ActiveTake:
    app: str
    key: tuple[str, str, str]
    meta: TakeMeta
    take: Take
    t_event: float                              # monotonic time of the track-change event
    flags: dict = field(default_factory=dict)
    replace_id: int | None = None
    session: object = None
    capture: object = None


STOP = "STOP"
BLIP_SECONDS = 2.0   # a take replaced by the next song this fast was never that song playing
START_LAG_MAX_MS = 6000   # the most start-up delay forgiven; Spotify's has been 1.5 to 3.7 s


class Recorder:
    def __init__(self, cfg: Config, loop: asyncio.AbstractEventLoop | None = None):
        self.cfg = cfg
        self.loop = loop or asyncio.get_event_loop()
        self.queue: asyncio.Queue = asyncio.Queue()
        self.store = Store(cfg.paths.db_path)
        self.process_mode = cfg.capture.mode == "process" and ProcessCapture.available()
        if cfg.capture.mode == "process" and not self.process_mode:
            log.warning("per-app capture helper not found; falling back to whole-device loopback")
        self.captures: dict[str, object] = {}
        if self.process_mode:
            rate = cfg.capture.sample_rate or 48000
            for src in cfg.rules.sources:
                self.captures[src.lower()] = ProcessCapture(src, rate, cfg.capture.preroll_seconds)
        else:
            self.captures["*"] = LoopbackCapture(cfg.capture.device, cfg.capture.preroll_seconds)
        self.smtc = S.SmtcListener(self.loop, self.queue)
        self.bridge = (Bridge(self.loop, self.queue, cfg.bridge.port, on_status=self._bridge_status)
                       if cfg.bridge.enabled else None)
        self.active: ActiveTake | None = None
        self.pending: S.Snapshot | None = None      # a source track seen while not playing
        self.skipping_key: tuple | None = None      # current track we decided not to record
        self._last_prune = 0.0
        self.on_event = None                        # optional callable(dict) for UIs
        self.paused = False                         # when True, no new takes are started
        self.harvest = cfg.rules.harvest_mode       # when True, skip songs already archived
        self._skips: list[float] = []               # monotonic times of recent harvest skips
        self.foreign = ForeignAudioMonitor(cfg.rules.sources, cfg.rules.foreign_audio_threshold_db)
        self.post = PostProcessor(cfg, self.store, on_event=lambda e: self._emit(e.pop("kind"), **e))

    # -- observers -------------------------------------------------------------------------

    def _emit(self, kind: str, **data) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event({"kind": kind, **data})
        except Exception:
            log.exception("event listener failed")

    def _bridge_status(self, connected: bool) -> None:
        self._emit("bridge", connected=connected)

    def request_stop(self) -> None:
        """Thread-safe: ask the run loop to shut down."""
        self.loop.call_soon_threadsafe(self.queue.put_nowait, STOP)

    def set_paused(self, paused: bool) -> None:
        """Thread-safe: pause/resume starting new takes."""
        def apply():
            self.paused = paused
            self._emit("paused", paused=paused)
        self.loop.call_soon_threadsafe(apply)

    def set_harvest(self, on: bool) -> None:
        """Thread-safe: toggle skipping of already-archived songs."""
        def apply():
            self.harvest = on
            log.info("harvest mode %s", "on" if on else "off")
            self._emit("harvest", on=on)
        self.loop.call_soon_threadsafe(apply)

    async def _harvest_skip(self, session, artist: str, title: str) -> bool:
        """Skip to the next song, at most 30 times per minute so a looping queue can't run away."""
        now = time.monotonic()
        self._skips = [t for t in self._skips if now - t < 60.0]
        if len(self._skips) >= 30:
            log.warning("harvest: skip limit reached, not skipping %s - %s", artist, title)
            return False
        try:
            ok = await session.try_skip_next_async()
        except Exception as e:
            log.warning("harvest: skip failed: %s", e)
            return False
        if ok:
            self._skips.append(now)
            log.info("harvest: skipped %s - %s (already archived)", artist, title)
        return bool(ok)

    # -- lifecycle -------------------------------------------------------------------------

    def capture_for(self, app: str):
        a = (app or "").lower()
        for name, cap in self.captures.items():
            if name != "*" and (a == name or a.endswith(name)):
                return cap
        return self.captures.get("*")

    async def run(self) -> None:
        for cap in self.captures.values():
            cap.start()
        self.foreign.start()
        self.post.start()
        await self.smtc.start()
        if self.bridge:
            await self.bridge.start()
        log.info("mynaphone running; sources=%s inbox=%s", self.cfg.rules.sources, self.cfg.paths.inbox_dir)
        first = next(iter(self.captures.values()))
        desc = ("per-app capture of " + ", ".join(self.cfg.rules.sources)) if self.process_mode else first.device_name
        self._emit("started", device=desc, rate=first.rate, mode="process" if self.process_mode else "device")
        self._emit("idle")
        ticker = asyncio.create_task(self._ticker())
        # evaluate whatever is already playing
        for sess in self.smtc.sessions():
            await self._handle(await S.snapshot(sess), "sessions", sess)
        try:
            while True:
                ev = await self.queue.get()
                if ev == STOP:
                    break
                try:
                    if isinstance(ev, BridgeEvent):
                        await self._on_bridge(ev)
                    elif isinstance(ev, YouTubeEvent):
                        await self._on_youtube(ev)
                    elif isinstance(ev, S.SmtcEvent):
                        await self._on_smtc(ev)
                except Exception:
                    log.exception("error handling %s", ev)
        finally:
            ticker.cancel()
            if self.active:
                await self._finish("shutdown")
            self.smtc.stop()
            for cap in self.captures.values():
                cap.stop()
            self.foreign.stop()
            self.post.stop()
            if self.bridge:
                await self.bridge.stop()
            self._emit("stopped")

    async def _ticker(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            try:
                await self._tick()
            except Exception:
                log.exception("tick failed")

    # -- event routing ---------------------------------------------------------------------

    async def _on_smtc(self, ev: S.SmtcEvent) -> None:
        if ev.kind == "sessions":
            seen_source = False
            for sess in self.smtc.sessions():
                app = sess.source_app_user_model_id or ""
                if self.cfg.rules.is_source(app):
                    seen_source = True
                    await self._handle(await S.snapshot(sess), "sessions", sess)
            if not seen_source and self.active:
                await self._finish("session_gone")
            return
        if not self.cfg.rules.is_source(ev.app):
            return
        snap = await S.snapshot(ev.session)
        await self._handle(snap, ev.kind, ev.session)

    async def _handle(self, snap: S.Snapshot, kind: str, session) -> None:
        a = self.active
        if a and a.app.lower() == snap.app.lower() and snap.key != a.key and not self._is_blank(snap):
            # boundary: the session now reports a different track. Start the next take before writing
            # the old one out: writing a long song takes seconds, and the next take can only reach
            # preroll_seconds back into the ring buffer for its opening.
            ended = self._end_take("track_change")
            try:
                await self._handle(snap, kind, session)
            finally:
                if ended is not None:
                    await self._write_take(*ended)
            return
        if a and a.app.lower() == snap.app.lower():
            # same track: pause/stop/seek/stall checks
            if snap.status == S.PAUSED:
                if not a.flags.get("paused"):
                    log.info("paused during take: %s", a.meta.title)
                a.flags["paused"] = True
            elif snap.status in (S.STOPPED, S.CLOSED):
                await self._finish("stopped")
            elif kind == "timeline" and snap.status == S.PLAYING:
                self._check_timeline(a, snap)
            return
        # no active take for this app: decide whether to start one
        if self._is_blank(snap) or self.cfg.rules.is_ignored_title(snap.title) or not snap.artist:
            if self.active is None:
                self.skipping_key = None
            self.pending = None
            return
        if snap.status != S.PLAYING:
            self.pending = snap
            return
        if self.skipping_key == snap.key:
            return
        if self.paused:
            self.skipping_key = snap.key
            self._emit("skipped", artist=snap.artist, title=snap.title, reason="paused_by_user")
            return
        await self._start(snap, session)

    @staticmethod
    def _is_blank(snap: S.Snapshot) -> bool:
        return not (snap.title or snap.artist)

    @staticmethod
    def _is_browser(app: str) -> bool:
        a = (app or "").lower()
        return any(b in a for b in ("chrome", "msedge", "firefox", "brave", "opera", "vivaldi"))

    def _youtube_ok(self, snap: S.Snapshot) -> tuple[bool, str]:
        """For a browser source: only record when the extension says a music video/track is playing."""
        if self.bridge is None or not self.bridge.youtube.fresh:
            return False, "browser extension not reporting"
        yt = self.bridge.youtube
        if not yt.is_music:
            return False, "not music"
        if yt.duration_s and snap.end_ms and abs(yt.duration_s * 1000 - snap.end_ms) > 3000:
            return False, "extension and media session disagree on the video"
        return True, ""

    async def _on_youtube(self, ev: YouTubeEvent) -> None:
        st = ev.state
        a = self.active
        if a is None or not self._is_browser(a.app) or st is None:
            return
        if (st.video_id and a.meta.extra.get("youtube", {}).get("video_id")
                and st.video_id != a.meta.extra["youtube"]["video_id"]):
            return
        if st.event in ("seeking", "seeked") and (time.monotonic() - a.t_event) > 2.0:
            if not a.flags.get("seek"):
                log.info("seek reported by the browser during %s", a.meta.title)
            a.flags["seek"] = True
        if st.paused and not st.ended and (time.monotonic() - a.t_event) > 1.0:
            a.flags["paused"] = True
        if st.rate and abs(st.rate - 1.0) > 0.01:
            a.flags["seek"] = True
            log.info("playback speed %.2fx during %s; take cannot be used", st.rate, a.meta.title)

    def _enrich_from_youtube(self, meta: TakeMeta, yt: YouTubeState) -> None:
        info = {"video_id": yt.video_id, "url": yt.url, "host": yt.host, "channel": yt.channel, "genre": yt.genre,
                "page_title": yt.title, "duration_s": yt.duration_s, "description": yt.description}
        if yt.music:
            info["music"] = yt.music
            if yt.music.get("title"):
                meta.title = yt.music["title"]
            if yt.music.get("artist"):
                meta.artist = yt.music["artist"]
            album = yt.music.get("album") or ""
            if album and not re.search(r"\b(views?|likes?|subscribers?)\b", album, re.I):
                meta.album = album
            elif re.search(r"\b(views?|likes?)\b", meta.album or "", re.I):
                meta.album = ""
            if yt.music.get("year") and str(yt.music["year"]).isdigit():
                info["year"] = int(yt.music["year"])
        meta.source_uri = f"youtube:video:{yt.video_id}" if yt.video_id else ""
        meta.extra["youtube"] = info

    def _check_timeline(self, a: ActiveTake, snap: S.Snapshot) -> None:
        since_start = time.monotonic() - a.t_event
        if since_start < 3.0 or snap.last_updated is None:
            return
        exp_s = a.meta.expected_ms / 1000.0
        # At a track boundary Spotify updates the timeline before the media properties, so the
        # snapshot can pair the old title with the next track's duration/position. Ignore those.
        if a.meta.expected_ms and abs(snap.end_ms - a.meta.expected_ms) > 1000:
            return
        if snap.position_ms < 3000 and since_start > exp_s - 5.0:
            return
        expected = a.flags.get("start_position_ms", 0) + since_start * 1000.0
        drift = snap.position_ms - expected
        tol = self.cfg.rules.duration_tolerance_seconds * 1000.0
        # Spotify names a track a second or more before its sound starts, so its position begins behind
        # the clock. The first reading once the song is under way sets that lag; a stall is falling
        # further behind it.
        if "start_lag_ms" not in a.flags:
            if snap.position_ms < 1000:
                return
            a.flags["start_lag_ms"] = int(min(max(-drift, 0.0), START_LAG_MAX_MS))
        drift += a.flags["start_lag_ms"]
        if drift > tol and not a.flags.get("seek"):
            a.flags["seek"] = True
            log.info("seek detected (+%.1fs) in %s", drift / 1000, a.meta.title)
        elif drift < -tol and not a.flags.get("buffering"):
            a.flags["buffering"] = True
            log.info("playback stalled (%.1fs behind) in %s", -drift / 1000, a.meta.title)

    async def _on_bridge(self, ev: BridgeEvent) -> None:
        st = ev.state
        a = self.active
        if a is None or not a.app.lower().startswith("spotify") or st is None:
            return
        if ev.kind == "lyrics":
            self._attach_lyrics(a.meta)
            return
        if st.name and a.meta.title and st.name.strip().lower() != a.meta.title.strip().lower():
            return  # bridge is reporting a different track than the media session; ignore
        self._enrich_from_bridge(a.meta, st)
        since_start = time.monotonic() - a.t_event
        # Spotify loads the next track during the last seconds of this one and reports buffering while it
        # does. A real stall there still shows up in the verdict as extra wall-clock time.
        near_end = bool(a.meta.expected_ms) and since_start > a.meta.expected_ms / 1000.0 - 10.0
        if st.is_buffering and since_start > 2.0:
            if near_end:
                if not a.flags.get("buffering_near_end"):
                    log.info("buffering reported in the last seconds of %s; ignored (Spotify loading the next track)",
                             a.meta.title)
                a.flags["buffering_near_end"] = True
                return
            if not a.flags.get("buffering"):
                log.info("buffering reported by spotify during %s", a.meta.title)
            a.flags["buffering"] = True

    def _attach_lyrics(self, meta: TakeMeta) -> None:
        if self.bridge and meta.source_uri and meta.source_uri in self.bridge.lyrics:
            meta.extra["spotify_lyrics"] = self.bridge.lyrics[meta.source_uri]

    @staticmethod
    def _enrich_from_bridge(meta: TakeMeta, st: SpotifyState) -> None:
        if st.uri:
            meta.source_uri = st.uri
        if st.album and st.album.get("uri"):
            meta.album_uri = st.album["uri"]
        if st.artists:
            meta.artist_uris = [x.get("uri", "") for x in st.artists if x.get("uri")]
        if st.image:
            img = st.image
            if img.startswith("spotify:image:"):
                img = "https://i.scdn.co/image/" + img.split(":", 2)[2]
            meta.cover_url = img
        if st.duration_ms and not meta.expected_ms:
            meta.expected_ms = st.duration_ms
        if st.quality:
            meta.quality_raw = st.quality
            meta.quality_tier = st.tier
        if st.album_info:
            meta.extra["album_info"] = st.album_info
        if st.metadata:
            meta.extra["track_metadata"] = {k: v for k, v in st.metadata.items() if v not in (None, "")}
        if st.track_info:
            meta.extra["track_info"] = st.track_info
        md = st.metadata or {}
        for k in ("album_track_number", "track_number"):
            if md.get(k) and not meta.track_number:
                try:
                    meta.track_number = int(md[k])
                except ValueError:
                    pass
        for k in ("album_disc_number", "disc_number"):
            if md.get(k) and not meta.disc_number:
                try:
                    meta.disc_number = int(md[k])
                except ValueError:
                    pass

    # -- take lifecycle --------------------------------------------------------------------

    async def _start(self, snap: S.Snapshot, session) -> None:
        now_mono = time.monotonic()
        meta = TakeMeta(
            app=snap.app, artist=snap.artist, title=snap.title, album=snap.album,
            album_artist=snap.album_artist, track_number=snap.track_number, expected_ms=snap.end_ms,
            started_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        )
        if self.bridge and self.bridge.state.fresh and snap.app.lower().startswith("spotify"):
            st = self.bridge.state
            if not st.name or st.name.strip().lower() == snap.title.strip().lower():
                self._enrich_from_bridge(meta, st)
        if self._is_browser(snap.app):
            ok, why = self._youtube_ok(snap)
            if not ok:
                self.skipping_key = snap.key
                log.info("not recording browser audio (%s): %s - %s", why, snap.artist, snap.title)
                self._emit("skipped", artist=snap.artist, title=snap.title,
                           reason="not_music" if why == "not music" else "browser_unverified")
                return
            self._enrich_from_youtube(meta, self.bridge.youtube)
            meta.quality_tier = "youtube"
        start_pos = snap.expected_position_ms()
        existing = self.store.find_archived(meta.artist, meta.title, meta.expected_ms, meta.source_uri or None)
        replace_id = None
        if existing is not None:
            better = (self.cfg.quality.upgrade_on_higher_tier
                      and tier_rank(meta.quality_tier) > tier_rank(existing["quality_tier"]))
            if not better:
                self.skipping_key = snap.key
                log.info("already archived (%s): %s - %s", existing["quality_tier"], meta.artist, meta.title)
                skipped = False
                if self.harvest and session is not None:
                    skipped = await self._harvest_skip(session, meta.artist, meta.title)
                self._emit("skipped", artist=meta.artist, title=meta.title,
                           reason="already_archived_skipped" if skipped else "already_archived")
                self.store.log_take(started_at=meta.started_at, ended_at=meta.started_at, artist=meta.artist,
                                    title=meta.title, album=meta.album, source_app=meta.app,
                                    source_uri=meta.source_uri, expected_ms=meta.expected_ms, verdict="skip",
                                    reasons=["already_archived_skipped" if skipped else "already_archived"],
                                    quality_tier=meta.quality_tier)
                return
            replace_id = int(existing["id"])
            log.info("upgrade: %s -> %s for %s - %s",
                     existing["quality_tier"], meta.quality_tier, meta.artist, meta.title)
        if meta.expected_ms and meta.expected_ms / 1000.0 < self.cfg.rules.min_duration_seconds:
            self.skipping_key = snap.key
            log.info("too short (%.0fs), not recording: %s - %s", meta.expected_ms / 1000, meta.artist, meta.title)
            self._emit("skipped", artist=meta.artist, title=meta.title, reason="too_short")
            return
        if meta.expected_ms and meta.expected_ms / 1000.0 > self.cfg.rules.max_duration_seconds:
            self.skipping_key = snap.key
            log.info("too long (%.0fs; podcast or mix?), not recording: %s - %s",
                     meta.expected_ms / 1000, meta.artist, meta.title)
            self._emit("skipped", artist=meta.artist, title=meta.title, reason="too_long")
            return
        # If the change was noticed late (position already > 0), reach back into the ring buffer
        # for the audio that played since the real boundary.
        cap = self.capture_for(snap.app)
        if cap is None or not cap.healthy:
            self.skipping_key = snap.key
            log.warning("no live capture for %s; not recording %s - %s", snap.app, meta.artist, meta.title)
            self._emit("skipped", artist=meta.artist, title=meta.title, reason="capture_not_ready")
            return
        lead = self.cfg.capture.lead_margin_seconds
        back = min(start_pos / 1000.0 + lead, max(cap.ring_seconds - 0.1, lead))
        take = cap.begin_take(now_mono - back)
        effective_start = max(0, int(start_pos - (back - lead) * 1000))
        flags = {"start_position_ms": effective_start, "reported_start_ms": int(start_pos)}
        self._check_volumes(snap.app, flags)
        self.active = ActiveTake(app=snap.app, key=snap.key, meta=meta, take=take, t_event=now_mono - (back - lead),
                                 flags=flags, replace_id=replace_id, session=session, capture=cap)
        self.pending = None
        self.skipping_key = None
        log.info("recording: %s - %s [%s] expected %.1fs, start pos %.1fs, tier %s",
                 meta.artist, meta.title, meta.album, meta.expected_ms / 1000, start_pos / 1000, meta.quality_tier)
        self._emit("recording", artist=meta.artist, title=meta.title, album=meta.album,
                   expected_ms=meta.expected_ms, tier=meta.quality_tier, t_event=self.active.t_event)
        asyncio.create_task(self._fetch_cover(self.active))

    def _check_volumes(self, app: str, flags: dict) -> None:
        """A take recorded below full volume is a quiet, degraded file; flag it so the verdict rejects it.

        Windows' master volume and mute do not affect per-app capture (measured), but the app's slider
        in the Volume Mixer and the app's own volume control do.
        """
        mixer = app_session_volume(app)
        if mixer is not None:
            vol, muted = mixer
            if muted or vol < 0.99:
                flags["mixer_volume"] = 0 if muted else int(round(vol * 100))
                log.info("%s is at %s%% in the Windows Volume Mixer; the take will be rejected",
                         app, flags["mixer_volume"])
        if self.bridge is not None and app.lower().startswith("spotify") and self.bridge.state.fresh:
            v = self.bridge.state.volume
            if v is not None and v < 0.99:
                flags["app_volume"] = int(round(v * 100))
                log.info("Spotify's own volume is at %s%%; the take will be rejected", flags["app_volume"])
        if self.bridge is not None and self._is_browser(app) and self.bridge.youtube.fresh:
            yt = self.bridge.youtube
            if yt.muted or (yt.volume is not None and yt.volume < 0.99):
                flags["app_volume"] = 0 if yt.muted else int(round((yt.volume or 0) * 100))
                log.info("YouTube player volume is at %s%%; the take will be rejected", flags["app_volume"])

    async def _fetch_cover(self, a: ActiveTake) -> None:
        """Grab the media-session thumbnail; Spotify attaches it a moment after the track change."""
        for attempt in range(4):
            if self.active is not a:
                return
            try:
                snap = await S.snapshot(a.session, with_thumbnail=True)
                if snap.key == a.key and snap.thumbnail:
                    a.meta.cover = snap.thumbnail
                    self._emit("cover", artist=a.meta.artist, title=a.meta.title, data=snap.thumbnail)
                    return
            except Exception as e:
                log.debug("cover fetch failed: %s", e)
            await asyncio.sleep(3.0)

    async def _finish(self, reason: str) -> None:
        ended = self._end_take(reason)
        if ended is not None:
            await self._write_take(*ended)

    def _end_take(self, reason: str) -> tuple[ActiveTake, Take, dict, float] | None:
        """Stop the active take's capture and settle its flags. Quick, so the next take can start at once."""
        a, self.active = self.active, None
        if a is None:
            return None
        take = a.capture.end_take() if a.capture is not None else None
        if take is None:
            return None
        a.meta.ended_at = dt.datetime.now(dt.timezone.utc).isoformat()
        flags = dict(a.flags)
        flags["overflows"] = take.overflows
        flags["device_changes"] = take.device_changes
        flags["end_reason"] = reason
        report = self.foreign.events_since(take.t_begin)
        if report.events:
            flags["foreign_audio"] = {"apps": report.apps, "max_db": round(report.max_db, 1),
                                      "count": len(report.events), "isolated": self.process_mode}
            if self.process_mode:
                log.info("other apps made sound during the take (%s) but per-app capture kept it out",
                         ", ".join(report.apps))
        self.foreign.forget_before(take.t_begin)
        wall_s = (take.t_end or time.monotonic()) - a.t_event
        if reason == "track_change" and wall_s < BLIP_SECONDS:
            # Spotify names the last song for a moment when you press play on the next one; that isn't a take
            log.info("dropped %.1f s of %s - %s: the player moved on at once", wall_s, a.meta.artist, a.meta.title)
            return None
        # a stop reported at the song's expected end (YouTube does this between tracks) is a normal finish
        at_end = (bool(a.meta.expected_ms)
                  and wall_s >= a.meta.expected_ms / 1000.0 - self.cfg.rules.duration_tolerance_seconds)
        if reason in ("stopped", "session_gone", "shutdown") and not at_end:
            flags["ended_early"] = reason
        if (self.bridge and self.bridge.state.fresh
                and self.bridge.state.name.strip().lower() == a.meta.title.strip().lower()):
            self._enrich_from_bridge(a.meta, self.bridge.state)
        self._attach_lyrics(a.meta)
        return a, take, flags, wall_s

    async def _write_take(self, a: ActiveTake, take: Take, flags: dict, wall_s: float) -> None:
        """Judge, write and index an ended take, off the event loop; this is the slow part."""
        await self.loop.run_in_executor(None, self._finalize, a, take, flags, wall_s)

    def _finalize(self, a: ActiveTake, take: Take, flags: dict, wall_s: float) -> None:
        cfg = self.cfg
        meta = a.meta
        audio = take.audio()
        audio, lead_ms = trim(audio, take.rate, meta.expected_ms,
                              cfg.capture.lead_margin_seconds + 1.5, cfg.rules.duration_tolerance_seconds)
        captured_s = len(audio) / float(take.rate)
        flags["hole_ms"] = longest_hole_ms(audio, take.rate)
        verdict = judge(meta, captured_s, wall_s, flags, cfg)
        verdict.trimmed_lead_ms = lead_ms
        root = cfg.paths.inbox_dir if verdict.keep else cfg.paths.discard_dir
        path = None
        if verdict.keep and meta.cover_url.startswith("http"):
            # prefer the full-size cover when the network is up; the SMTC thumbnail stays as fallback
            try:
                import urllib.request
                req = urllib.request.Request(meta.cover_url, headers={"User-Agent": "mynaphone/0.1"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    data = r.read()
                if data[:3] == b"\xff\xd8\xff" or data[:4] == b"\x89PNG":
                    meta.cover = data
            except Exception as e:
                log.debug("cover download failed (%s); using thumbnail if any", e)
        if verdict.keep or cfg.rules.keep_discards_days > 0:
            path = output_path(root, meta)
            write_flac(path, audio, take.rate, cfg.capture.bit_depth)
            try:
                tag_flac(path, meta, verdict, take.rate, cfg.capture.bit_depth)
            except Exception as e:
                log.warning("tagging failed for %s: %s", path.name, e)
            sidecar(path, meta, verdict, flags, take.rate, cfg.capture.bit_depth)
        self.store.log_take(
            started_at=meta.started_at, ended_at=meta.ended_at, artist=meta.artist, title=meta.title,
            album=meta.album, source_app=meta.app, source_uri=meta.source_uri, expected_ms=meta.expected_ms,
            captured_ms=verdict.captured_ms, wall_ms=verdict.wall_ms,
            verdict="keep" if verdict.keep else "discard", reasons=verdict.reasons,
            file_path=str(path) if path else None, quality_tier=meta.quality_tier,
        )
        if verdict.keep:
            fields = dict(artist=meta.artist, title=meta.title, album=meta.album, album_artist=meta.album_artist,
                          track_number=meta.track_number, duration_ms=meta.expected_ms, source_app=meta.app,
                          source_uri=meta.source_uri, quality_tier=meta.quality_tier, file_path=str(path),
                          state="inbox", meta_json={"album_uri": meta.album_uri, "artist_uris": meta.artist_uris,
                                                    "cover_url": meta.cover_url, "quality": meta.quality_raw,
                                                    "extra": meta.extra})
            if a.replace_id is not None:
                old = self.store.conn.execute("SELECT file_path FROM tracks WHERE id=?", (a.replace_id,)).fetchone()
                self.store.replace_track(a.replace_id, **fields)
                if old and old["file_path"]:
                    for p in (Path(old["file_path"]), Path(old["file_path"]).with_suffix(".json")):
                        try:
                            p.unlink(missing_ok=True)
                        except Exception:
                            pass
            else:
                self.store.add_track(**fields)
            log.info("KEPT %.1fs -> %s", captured_s, path.name)
            self._emit("kept", artist=meta.artist, title=meta.title, album=meta.album, path=str(path),
                       captured_ms=verdict.captured_ms, expected_ms=meta.expected_ms, tier=meta.quality_tier)
            self.post.kick()
        else:
            log.info("DISCARDED %s - %s: %s", meta.artist, meta.title, ", ".join(verdict.reasons))
            self._emit("discarded", artist=meta.artist, title=meta.title, album=meta.album, reasons=verdict.reasons,
                       captured_ms=verdict.captured_ms, expected_ms=meta.expected_ms, tier=meta.quality_tier)
        if self.active is None:
            self._emit("idle")

    # -- housekeeping ----------------------------------------------------------------------

    async def _tick(self) -> None:
        a = self.active
        if a and a.meta.expected_ms:
            overrun = time.monotonic() - a.t_event - a.meta.expected_ms / 1000.0
            if overrun > self.cfg.rules.duration_tolerance_seconds + 3.0:
                log.info("overrun by %.1fs with no track change; closing take", overrun)
                await self._finish("overrun")
        if self.pending and time.monotonic() - self._last_prune > 2.0:
            # re-evaluate a track that was seen while paused, in case playback resumed without an event
            pass
        if time.monotonic() - self._last_prune > 3600:
            self._last_prune = time.monotonic()
            self._prune_discards()

    def _prune_discards(self) -> None:
        days = self.cfg.rules.keep_discards_days
        if days <= 0:
            return
        cutoff = time.time() - days * 86400
        for p in self.cfg.paths.discard_dir.glob("*"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
            except Exception:
                pass
