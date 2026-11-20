# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Record a Spotify playlist or album: play it through the bridge and record the songs the library lacks.

The job starts the playlist at its first missing song, in order with shuffle and repeat off. When a song the library
already has comes up, it jumps to the next missing one, so it plays as little as it can of what you already have.
Songs that don't record all the way through get one more try at the end. When it's done it pauses Spotify, puts the
playlist's shuffle setting back, and writes the playlist's M3U8, except for an album recorded from the Wanted list,
whose songs are in the library's own folders. Picking something else in Spotify stops it.

A song that just ended is still being saved and judged when the next one starts, so the job never plays such a song
again until its verdict is in: on November 20, 2026 the last missing song of Monsoon Season started over for one more
try while its first take was being saved, and that take turned out fine.
"""
from __future__ import annotations

import asyncio
import logging
import time

from . import playlists
from .bridge import BridgeError
from .store import norm

log = logging.getLogger("mynaphone.job")

# After a play command Spotify's media session names the song it was on for a moment (about 0.2 s after a pause), and
# the bridge may still report that song, so a song from outside the playlist this soon doesn't mean you picked it
SETTLE_SECONDS = 3.0
SAME_LENGTH_MS = 2000       # a song known only by its title is a playlist song this close to it in length
SHUFFLE = {0: "off", 1: "on", 2: "smart shuffle"}


class PlaylistJob:
    def __init__(self, recorder, uri: str, name: str, tracks: list[dict], keep_file: bool = True):
        self.rec = recorder
        self.uri = uri
        self.name = name
        self.tracks = tracks
        self.keep_file = keep_file                      # write the playlist's M3U8 at the end
        s = playlists.summary(recorder.store, tracks)
        self.todo: list[int] = list(s["todo"])          # playlist positions still to record, in playlist order
        self.have = len(s["have"])
        self.unplayable = len(s["unplayable"])
        self.saved: list[int] = []
        self.failed: dict[int, list[str]] = {}          # position -> why its last try didn't record
        self.given_up: dict[int, str] = {}              # songs the recorder won't take (too short, say)
        self.places: dict[str, list[int]] = {}          # Spotify id -> its positions; a song can be listed twice
        for t in tracks:
            if t.get("uri"):
                self.places.setdefault(t["uri"], []).append(t["index"])
        playable = [t["index"] for t in tracks if playlists.wanted(t)]
        self.last = max(playable) if playable else None    # the song Spotify ends the playlist on
        self.tries: dict[int, int] = {}                 # position -> takes of it that didn't record
        self.recording: set[int] = set()                # songs being recorded, or saved and waiting for their verdict
        self.waiting = False                            # nothing to play until one of those verdicts is in
        self.current: int | None = None
        self.shuffle_was = None
        self.done = False
        self._jump: asyncio.Task | None = None
        self._asking = False                            # a play command is on its way to Spotify
        self._asked_at = 0.0                            # monotonic time the last one came back

    # -- what the window shows ------------------------------------------------------------

    def progress(self, **extra) -> dict:
        title = self.tracks[self.current]["name"] if self.current is not None else ""
        return {"name": self.name, "uri": self.uri, "total": len(self.tracks), "have": self.have,
                "saved": len(self.saved), "left": len(self.todo), "failed": len(self.failed),
                "current": title, "done": self.done, **extra}

    # -- driving Spotify ------------------------------------------------------------------

    async def start(self) -> None:
        log.info("playlist %s: %d songs, %d in the library, %d to record, %d Spotify can't play",
                 self.name, len(self.tracks), self.have, len(self.todo), self.unplayable)
        if not self.todo:
            await self.finish("every song in it is already in your library")
            return
        await self._play(self.todo[0])

    async def _play(self, index: int) -> None:
        if self.done:
            return                      # a jump that was on its way when the job ended
        t = self.tracks[index]
        self.current = index
        self._asking = True
        try:
            res = await self.rec.bridge.request("play", timeout=25.0, context=self.uri, uri=t["uri"],
                                                uid=t.get("uid") or "")
        except BridgeError as e:
            self._asking = False
            await self.finish(f"Spotify wouldn't play it: {e}", stopped=True)
            return
        self._asking = False
        self._asked_at = time.monotonic()
        if self.shuffle_was is None:
            self.shuffle_was = (res or {}).get("shuffle_was")
            if self.shuffle_was is not None:
                log.info("playlist %s: its shuffle was %s, and it's off while the songs record", self.name,
                         SHUFFLE.get(self.shuffle_was, self.shuffle_was))
        if not self.done:
            self.rec._emit("job", **self.progress())

    def _jump_to(self, index: int) -> None:
        if self._jump is not None and not self._jump.done():
            return                      # one jump at a time; the song it lands on decides what comes next
        self._jump = asyncio.ensure_future(self._play(index))

    async def _pause(self) -> None:
        if self.rec.bridge is None:
            return
        try:
            await self.rec.bridge.request("pause", timeout=10.0)
        except BridgeError:
            pass

    def _next_todo(self, after: int | None) -> int | None:
        """The next song to record after position `after`. A song still being recorded or judged isn't one yet. Past
        the end it starts over, which gives a song that didn't record its one more go; a song that fails twice has
        left the list by then."""
        free = [i for i in self.todo if i not in self.recording]
        later = [i for i in free if after is None or i > after]
        if later:
            return later[0]
        if free:
            log.info("playlist %s: one more try for %d songs", self.name, len(free))
            return free[0]
        return None

    async def _advance(self, after: int | None) -> None:
        """Go on from position `after`: jump to the next song to record, wait for the verdicts still to come, or
        finish."""
        nxt = self._next_todo(after)
        if nxt is not None:
            self.waiting = False
            self._jump_to(nxt)
        elif self.recording:
            self.waiting = True         # those verdicts decide: done, or one more try
        else:
            await self.finish("done")

    # -- which song it is -------------------------------------------------------------------

    def _find(self, uri: str, title: str = "", duration_ms: int = 0, prefer=()) -> int | None:
        """The playlist position of a song, by its Spotify id. The bridge can name a song a second after the media
        session does, so until it has, a song is matched by its title and length."""
        found = self.places.get(uri) if uri else None
        if not found and title:
            for key in (lambda s: (s or "").casefold().strip(), norm):
                want = key(title)
                found = [t["index"] for t in self.tracks if want and key(t.get("name", "")) == want
                         and (not duration_ms
                              or abs(int(t.get("duration_ms") or 0) - int(duration_ms)) <= SAME_LENGTH_MS)]
                if found:
                    break
        if not found:
            return None
        for group in (prefer, (self.current,)):
            picked = [i for i in found if i in group]
            if picked:
                return picked[0]
        later = [i for i in found if self.current is None or i > self.current]
        return (later or found)[0]

    def _drop(self, index: int) -> None:
        """The library has this song now: it leaves the list, everywhere the playlist has it."""
        uri = self.tracks[index].get("uri")
        for i in self.places.get(uri, [index]) if uri else [index]:
            if i in self.todo:
                self.todo.remove(i)
            self.recording.discard(i)

    # -- what the recorder tells it -------------------------------------------------------

    async def on_track(self, uri: str, archived: bool, title: str = "", duration_ms: int = 0) -> bool:
        """A Spotify song started. True when the job takes care of it, by jumping past it or by waiting there for the
        last verdicts, so harvest mode leaves it alone."""
        if self.done:
            return False
        index = self._find(uri, title, duration_ms)
        if index is None:
            if uri:
                await self._left(uri)
            return False                # no id yet and none of the playlist's titles: nothing to go on
        self.current = index
        if archived:
            if index in self.todo and index not in self.saved:
                log.info("playlist %s: %s is in the library already", self.name, self.tracks[index].get("name"))
                self.have += 1
            self._drop(index)
        elif index in self.todo:
            self.recording.add(index)
            self.waiting = False
            self.rec._emit("job", **self.progress())
            return False
        await self._advance(index)
        return True

    async def _left(self, uri: str) -> None:
        """A song from outside the playlist started: Spotify's autoplay after the playlist's last song, the song it
        was paused on, or something you picked."""
        if self._asking or time.monotonic() - self._asked_at < SETTLE_SECONDS:
            log.info("playlist %s: Spotify named %s while it moved to the playlist; carrying on", self.name, uri)
            return
        st = getattr(self.rec.bridge, "state", None)
        provider = st.provider if st is not None and st.uri == uri else ""     # context, queue or autoplay
        ended = provider == "autoplay" or (self.current is not None and self.current == self.last
                                           and provider not in ("context", "queue"))
        if not ended:
            await self.finish("playback left the playlist", stopped=True)
            return
        # the playlist played to its end and autoplay took over: go back for the songs that need one more try,
        # or stop autoplay from playing on while the last verdicts come in
        nxt = self._next_todo(self.current)
        if nxt is not None:
            self.waiting = False
            self._jump_to(nxt)
        elif self.recording:
            self.waiting = True
            await self._pause()
        else:
            await self.finish("done")

    async def on_skipped(self, uri: str, reason: str, title: str = "", duration_ms: int = 0) -> None:
        """The recorder won't record this playlist song (too short, too long). Leave it out and go on."""
        index = self._find(uri, title, duration_ms)
        if self.done or index is None:
            return
        self.current = index
        if index in self.todo:
            self._drop(index)
            self.given_up[index] = reason
            self.rec._emit("job", **self.progress())
        await self._advance(index)

    def on_dropped(self, uri: str, title: str = "", duration_ms: int = 0) -> None:
        """A take of a playlist song ended within a second or two, with no verdict to come. The song gets its go
        later."""
        index = self._find(uri, title, duration_ms, prefer=self.recording)
        if not self.done and index is not None:
            self.recording.discard(index)

    async def on_result(self, uri: str, kept: bool, reasons: list[str], title: str = "",
                        duration_ms: int = 0) -> None:
        index = self._find(uri, title, duration_ms, prefer=self.recording)
        if self.done or index is None:
            return
        self.recording.discard(index)
        if index in self.todo:
            if kept:
                self._drop(index)
                self.saved.append(index)
                self.failed.pop(index, None)
            else:
                self.failed[index] = list(reasons)
                self.tries[index] = self.tries.get(index, 0) + 1
                if self.tries[index] >= 2:
                    self.todo.remove(index)         # it'll be on the list of songs to play again
        self.rec._emit("job", **self.progress())
        if self.waiting or (index == self.current == self.last):
            # nothing else was playing for the job, or Spotify stopped after the playlist's last song
            await self._advance(self.current)
        elif not self.todo and not self.recording:
            await self.finish("done")

    # -- the end ----------------------------------------------------------------------------

    async def finish(self, why: str, stopped: bool = False) -> None:
        if self.done:
            return
        self.done = True
        bridge = self.rec.bridge
        if bridge is not None:
            if not stopped:
                await self._pause()
            if self.shuffle_was is not None:
                mode = SHUFFLE.get(self.shuffle_was, self.shuffle_was)
                try:
                    await bridge.request("restore_shuffle", timeout=10.0, context=self.uri, mode=self.shuffle_was)
                    log.info("playlist %s: shuffle back to %s", self.name, mode)
                except BridgeError as e:
                    log.info("playlist %s: couldn't put its shuffle back to %s: %s", self.name, mode, e)
        if self.keep_file:
            try:
                playlists.save(self.rec.store, self.rec.cfg.paths.library_dir, self.uri, self.name, self.tracks)
            except Exception:
                log.exception("could not write the playlist file for %s", self.name)
        log.info("playlist %s: %s; %d saved, %d didn't record, %d left out", self.name, why, len(self.saved),
                 len(self.failed), len(self.given_up))
        if self.rec.job is self:
            self.rec.job = None
        self.rec._emit("job", **self.progress(why=why, stopped=stopped))
