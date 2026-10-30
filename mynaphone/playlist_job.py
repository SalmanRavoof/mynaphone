# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Record a Spotify playlist or album: play it through the bridge and record the songs the library lacks.

The job starts the playlist at its first missing song, in order with shuffle and repeat off. When a song the library
already has comes up, it jumps to the next missing one, so it plays as little as it can of what you already have.
Songs that don't record all the way through get one more try at the end. When it's done it pauses Spotify, puts the
playlist's shuffle setting back, and writes the playlist's M3U8. Picking something else in Spotify stops it.
"""
from __future__ import annotations

import asyncio
import logging

from . import playlists
from .bridge import BridgeError

log = logging.getLogger("mynaphone.job")


class PlaylistJob:
    def __init__(self, recorder, uri: str, name: str, tracks: list[dict]):
        self.rec = recorder
        self.uri = uri
        self.name = name
        self.tracks = tracks
        s = playlists.summary(recorder.store, tracks)
        self.todo: list[int] = list(s["todo"])          # playlist positions still to record, in playlist order
        self.have = len(s["have"])
        self.unplayable = len(s["unplayable"])
        self.saved: list[int] = []
        self.failed: dict[int, list[str]] = {}          # position -> why its last try didn't record
        self.given_up: dict[int, str] = {}              # songs the recorder won't take (too short, say)
        self.by_uri = {t["uri"]: t["index"] for t in tracks if t.get("uri")}
        self.tries: dict[int, int] = {}                 # position -> takes of it that didn't record
        self.current: int | None = None
        self.shuffle_was = None
        self.done = False
        self._jump: asyncio.Task | None = None

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
        t = self.tracks[index]
        self.current = index
        try:
            res = await self.rec.bridge.request("play", timeout=25.0, context=self.uri, uri=t["uri"],
                                                uid=t.get("uid") or "")
        except BridgeError as e:
            await self.finish(f"Spotify wouldn't play it: {e}", stopped=True)
            return
        if self.shuffle_was is None:
            self.shuffle_was = (res or {}).get("shuffle_was")
        self.rec._emit("job", **self.progress())

    def _jump_to(self, index: int) -> None:
        if self._jump is not None and not self._jump.done():
            return                      # one jump at a time; the song it lands on decides what comes next
        self._jump = asyncio.ensure_future(self._play(index))

    def _next_todo(self, after: int | None) -> int | None:
        """The next song to record after position `after`. Past the end it starts over, which gives a song that
        didn't record its one more go; a song that fails twice has left the list by then."""
        later = [i for i in self.todo if after is None or i > after]
        if later:
            return later[0]
        if self.todo:
            log.info("playlist %s: one more try for %d songs", self.name, len(self.todo))
            return self.todo[0]
        return None

    # -- what the recorder tells it -------------------------------------------------------

    async def on_track(self, uri: str, archived: bool) -> bool:
        """A Spotify song started. True when the job took care of it by jumping past it."""
        if self.done or not uri:
            return False
        index = self.by_uri.get(uri)
        if index is None:
            # not from this playlist: autoplay, the queue, or you picked something else
            await self.finish("done" if not self.todo else "playback left the playlist", stopped=bool(self.todo))
            return False
        self.current = index
        if archived or index not in self.todo:
            nxt = self._next_todo(index)
            if nxt is None:
                await self.finish("done")
            elif nxt != index:
                self._jump_to(nxt)
            return True
        self.rec._emit("job", **self.progress())
        return False

    def on_skipped(self, uri: str, reason: str) -> None:
        """The recorder won't record this playlist song (too short, too long). Leave it out of the job."""
        index = self.by_uri.get(uri)
        if self.done or index is None or index not in self.todo:
            return
        self.todo.remove(index)
        self.given_up[index] = reason
        self.rec._emit("job", **self.progress())

    async def on_result(self, uri: str, kept: bool, reasons: list[str]) -> None:
        index = self.by_uri.get(uri)
        if self.done or index is None or index not in self.todo:
            return
        if kept:
            self.todo.remove(index)
            self.saved.append(index)
            self.failed.pop(index, None)
        else:
            self.failed[index] = list(reasons)
            self.tries[index] = self.tries.get(index, 0) + 1
            if self.tries[index] >= 2:
                self.todo.remove(index)         # it'll be on the list of songs to play again
        self.rec._emit("job", **self.progress())
        if not self.todo:
            await self.finish("done")

    # -- the end ----------------------------------------------------------------------------

    async def finish(self, why: str, stopped: bool = False) -> None:
        if self.done:
            return
        self.done = True
        bridge = self.rec.bridge
        if bridge is not None:
            if not stopped:
                try:
                    await bridge.request("pause", timeout=10.0)
                except BridgeError:
                    pass
            if self.shuffle_was is not None:
                try:
                    await bridge.request("restore_shuffle", timeout=10.0, context=self.uri, mode=self.shuffle_was)
                except BridgeError:
                    pass
        try:
            playlists.save(self.rec.store, self.rec.cfg.paths.library_dir, self.uri, self.name, self.tracks)
        except Exception:
            log.exception("could not write the playlist file for %s", self.name)
        log.info("playlist %s: %s; %d saved, %d didn't record, %d left out", self.name, why, len(self.saved),
                 len(self.failed), len(self.given_up))
        if self.rec.job is self:
            self.rec.job = None
        self.rec._emit("job", **self.progress(why=why, stopped=stopped))
