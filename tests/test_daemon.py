# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""State-machine tests: drive the recorder with synthetic media-session snapshots and a fake capture."""
import asyncio
import datetime as dt
import glob
import time

import numpy as np
import pytest

from mynaphone import smtc as S
from mynaphone.bridge import BridgeEvent, SpotifyState
from mynaphone.capture import Take
from mynaphone.daemon import Recorder


class FakeCapture:
    """Produces a tone for exactly the time a take was open."""

    def __init__(self, clock, rate=48000):
        self.clock, self.rate, self.channels = clock, rate, 2
        self.device_name = "fake"
        self.healthy = True
        self._take = None
        self.ring_seconds = 3.0

    def start(self): ...
    def stop(self): ...

    def begin_take(self, t_begin):
        self._take = Take(rate=self.rate, channels=self.channels, t_begin=t_begin)
        return self._take

    def end_take(self, tail_seconds=0.0):
        t, self._take = self._take, None
        if t is None:
            return None
        t.t_end = self.clock()
        seconds = max(0.0, t.t_end - t.t_begin)
        n = int(seconds * self.rate)
        x = (0.3 * np.sin(2 * np.pi * 440 * np.arange(n) / self.rate)).astype(np.float32)
        t.chunks = [np.stack([x, x], axis=1)]
        return t

    @property
    def recording(self):
        return self._take is not None


class FakeSession:
    def __init__(self):
        self.skips = 0

    async def try_skip_next_async(self):
        self.skips += 1
        return True

    async def try_get_media_properties_async(self):
        return None


def snap(title, artist="Artist", album="Album", status=S.PLAYING, pos_ms=0, end_ms=180_000, app="Spotify.exe"):
    return S.Snapshot(app=app, title=title, artist=artist, album=album, status=status, position_ms=pos_ms,
                      end_ms=end_ms, last_updated=dt.datetime.now(dt.timezone.utc))


@pytest.fixture
def recorder(tmp_config, clock):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    rec = Recorder(tmp_config, loop)
    rec.captures = {"*": FakeCapture(clock)}
    rec.events = []
    rec.on_event = rec.events.append
    yield rec, loop
    loop.close()


def run(loop, coro):
    return loop.run_until_complete(coro)


def play_full_song(rec, loop, clock, title, session=None, end_ms=180_000, **kw):
    """Start a song at position 0, let it run to its end, then start another title."""
    run(loop, rec._handle(snap(title, pos_ms=0, end_ms=end_ms, **kw), "media", session))
    clock.advance(end_ms / 1000.0)


def test_clean_song_is_kept(recorder, clock, tmp_config):
    rec, loop = recorder
    play_full_song(rec, loop, clock, "One")
    assert rec.active is not None and rec.active.meta.title == "One"
    run(loop, rec._handle(snap("Two"), "media", None))              # boundary
    kept = [e for e in rec.events if e["kind"] == "kept"]
    assert len(kept) == 1 and kept[0]["title"] == "One"
    assert glob.glob(str(tmp_config.paths.inbox_dir / "*One*.flac"))
    assert rec.active.meta.title == "Two"


def test_pause_discards(recorder, clock):
    rec, loop = recorder
    run(loop, rec._handle(snap("One"), "media", None))
    clock.advance(30)
    run(loop, rec._handle(snap("One", status=S.PAUSED, pos_ms=30_000), "playback", None))
    clock.advance(150)
    run(loop, rec._handle(snap("Two"), "media", None))
    d = [e for e in rec.events if e["kind"] == "discarded"]
    assert d and "paused" in d[0]["reasons"]


def test_pause_at_the_end_of_the_queue_keeps_the_song(recorder, clock):
    """Spotify pauses when its queue runs out after the last song (Amidinine, 2026-10-03)."""
    rec, loop = recorder
    run(loop, rec._handle(snap("One", end_ms=120_000), "media", None))
    clock.advance(120.5)
    run(loop, rec._handle(snap("One", status=S.PAUSED, pos_ms=120_000, end_ms=120_000), "playback", None))
    assert rec.active is None
    assert [e["title"] for e in rec.events if e["kind"] == "kept"] == ["One"]


def test_pause_seconds_before_the_end_still_discards(recorder, clock):
    rec, loop = recorder
    run(loop, rec._handle(snap("One", end_ms=120_000), "media", None))
    clock.advance(114.0)
    run(loop, rec._handle(snap("One", status=S.PAUSED, pos_ms=114_000, end_ms=120_000), "playback", None))
    assert [e["title"] for e in rec.events if e["kind"] == "discarded"] == ["One"]


def test_seek_is_detected_from_timeline(recorder, clock):
    rec, loop = recorder
    run(loop, rec._handle(snap("One"), "media", None))
    clock.advance(10)
    run(loop, rec._handle(snap("One", pos_ms=60_000), "timeline", None))   # jumped 50 s ahead
    assert rec.active.flags.get("seek") is True


def test_spotify_start_up_delay_is_not_a_stall(recorder, clock):
    """Spotify names a track about 2 s before its sound starts; only falling further behind is a stall."""
    rec, loop = recorder
    run(loop, rec._handle(snap("One"), "media", None))
    clock.advance(4.5)
    run(loop, rec._handle(snap("One", pos_ms=2_600), "timeline", None))    # 1.9 s behind, as on O Sanam
    assert not rec.active.flags.get("buffering") and rec.active.flags["start_lag_ms"] == 1900
    clock.advance(60.0)
    run(loop, rec._handle(snap("One", pos_ms=62_600), "timeline", None))
    assert not rec.active.flags.get("buffering")
    clock.advance(30.0)
    run(loop, rec._handle(snap("One", pos_ms=70_000), "timeline", None))   # stuck for over 20 s
    assert rec.active.flags["buffering"]


def test_reading_handled_late_is_not_a_seek(recorder, clock):
    """While a long song is written out, the queue waits, so the new song's first timeline reading is
    handled seconds after Spotify sent it. Taken at face value it set a 5 s start lag, and the next fresh
    reading looked like a 3 s jump ahead (Hydrogen, Felina, Jessie's Land and four more on 2026-10-02)."""
    rec, loop = recorder
    run(loop, rec._handle(snap("One"), "media", None))
    clock.advance(9.0)
    late = snap("One", pos_ms=2_000)                                       # sent at 4 s, 2 s behind
    late.last_updated -= dt.timedelta(seconds=5)
    run(loop, rec._handle(late, "timeline", None))
    assert 1_800 <= rec.active.flags["start_lag_ms"] <= 2_200
    clock.advance(4.5)
    run(loop, rec._handle(snap("One", pos_ms=11_500), "timeline", None))   # fresh, still 2 s behind
    assert not rec.active.flags.get("seek") and not rec.active.flags.get("buffering")


def test_small_lead_at_the_start_is_not_a_seek(recorder, clock):
    rec, loop = recorder
    run(loop, rec._handle(snap("One"), "media", None))
    clock.advance(4.5)
    run(loop, rec._handle(snap("One", pos_ms=6_400), "timeline", None))    # 1.9 s ahead
    assert not rec.active.flags.get("seek") and rec.active.flags["start_lag_ms"] == -1900
    clock.advance(60.0)
    run(loop, rec._handle(snap("One", pos_ms=66_400), "timeline", None))
    assert not rec.active.flags.get("seek") and not rec.active.flags.get("buffering")


def test_boundary_timeline_quirk_is_ignored(recorder, clock):
    """At a track change Spotify sends the next song's timeline before the new title; must not count as a stall."""
    rec, loop = recorder
    run(loop, rec._handle(snap("One", end_ms=180_000), "media", None))
    clock.advance(179)
    run(loop, rec._handle(snap("One", pos_ms=500, end_ms=240_000), "timeline", None))
    assert not rec.active.flags.get("buffering") and not rec.active.flags.get("seek")


def test_started_mid_song_is_discarded(recorder, clock):
    rec, loop = recorder
    run(loop, rec._handle(snap("One", pos_ms=90_000), "media", None))
    assert rec.active.flags["start_position_ms"] > 1500
    clock.advance(90)
    run(loop, rec._handle(snap("Two"), "media", None))
    d = [e for e in rec.events if e["kind"] == "discarded"]
    assert d and any(r.startswith("started_mid_track") for r in d[0]["reasons"])


def test_late_event_reaches_into_ring_buffer(recorder, clock):
    rec, loop = recorder
    run(loop, rec._handle(snap("One", pos_ms=2_000), "media", None))     # reported 2 s late
    assert rec.active.flags["start_position_ms"] == 0                      # covered by the 3 s ring
    # the position is extrapolated with the wall clock, so the call's own duration is added; on a
    # cold start (no compiled files yet, as on CI) that is a few milliseconds
    assert 2_000 <= rec.active.flags["reported_start_ms"] < 2_500


def test_next_take_starts_before_the_last_one_is_written(recorder, clock, monkeypatch):
    """Writing a long song out takes seconds. The next take must not wait for it, because it can only
    reach preroll_seconds back into the ring buffer for its opening."""
    rec, loop = recorder
    finalize = rec._finalize

    def slow_finalize(*args):
        time.sleep(1.0)
        finalize(*args)

    monkeypatch.setattr(rec, "_finalize", slow_finalize)
    play_full_song(rec, loop, clock, "One", end_ms=60_000)
    run(loop, rec._handle(snap("Two"), "media", None))                     # boundary
    assert rec.active.meta.title == "Two"
    # waiting for the write would put the start past 1000 ms; the margin covers a slow machine
    assert rec.active.flags["reported_start_ms"] < 800
    order = [(e["kind"], e["title"]) for e in rec.events if e["kind"] in ("recording", "kept")]
    assert order.index(("recording", "Two")) < order.index(("kept", "One"))


def test_buffering_in_the_last_seconds_is_ignored(recorder, clock):
    """Spotify reports buffering while it loads the next track, near the end of the current one."""
    rec, loop = recorder

    def buffering(title):
        state = SpotifyState(name=title, is_buffering=True, received_at=clock())
        run(loop, rec._on_bridge(BridgeEvent(kind="state", state=state)))

    run(loop, rec._handle(snap("One"), "media", None))
    clock.advance(177.0)                                                   # 3 s before the end
    buffering("One")
    assert not rec.active.flags.get("buffering") and rec.active.flags["buffering_near_end"]
    clock.advance(3.0)
    run(loop, rec._handle(snap("Two"), "media", None))
    clock.advance(60.0)                                                    # mid-song
    buffering("Two")
    assert rec.active.flags["buffering"]
    kept = [e for e in rec.events if e["kind"] == "kept"]
    assert [e["title"] for e in kept] == ["One"]


def test_stall_that_left_no_hole_is_kept(recorder, clock):
    """Spotify sends no sound while it loads, so the capture of a stalled song has no gap in it."""
    rec, loop = recorder
    run(loop, rec._handle(snap("One"), "media", None))
    clock.advance(60.0)
    run(loop, rec._on_bridge(BridgeEvent(kind="state", state=SpotifyState(name="One", is_buffering=True,
                                                                          received_at=clock()))))
    assert rec.active.flags["buffering"]
    clock.advance(120.0)
    run(loop, rec._handle(snap("Two"), "media", None))
    assert [e["title"] for e in rec.events if e["kind"] == "kept"] == ["One"]


def test_song_replaced_at_once_is_not_a_take(recorder, clock, tmp_config):
    """Pressing play on a new song, Spotify names the last one for a moment first; that blip is dropped."""
    rec, loop = recorder
    run(loop, rec._handle(snap("Old"), "media", None))
    clock.advance(0.2)
    run(loop, rec._handle(snap("New"), "media", None))
    assert rec.active.meta.title == "New"
    assert not [e for e in rec.events if e["kind"] in ("kept", "discarded")]
    assert not glob.glob(str(tmp_config.paths.discard_dir / "*Old*"))


def test_duplicate_is_skipped_and_harvest_skips_player(recorder, clock):
    rec, loop = recorder
    play_full_song(rec, loop, clock, "One")
    run(loop, rec._handle(snap("Two"), "media", None))
    run(loop, rec._handle(snap("Three"), "media", None))                   # closes "Two" (discarded, short)
    sess = FakeSession()
    rec.harvest = True
    run(loop, rec._handle(snap("One"), "media", sess))                      # "One" again
    skipped = [e for e in rec.events if e["kind"] == "skipped"]
    assert skipped and skipped[-1]["reason"] == "already_archived_skipped"
    assert sess.skips == 1 and rec.active is None


def test_higher_tier_replaces_archived_copy(recorder, clock, tmp_config):
    rec, loop = recorder
    play_full_song(rec, loop, clock, "One")
    run(loop, rec._handle(snap("Two"), "media", None))
    first = rec.store.find_archived("Artist", "One", 180_000)
    assert first is not None and first["quality_tier"] == "unknown"
    # pretend the bridge now reports a better tier for the same song
    from mynaphone.bridge import SpotifyState
    rec.bridge = type("B", (), {})()
    rec.bridge.state = SpotifyState(name="One", quality={"bitrateLevel": 4}, received_at=clock())
    rec.bridge.lyrics = {}
    run(loop, rec._handle(snap("Three"), "media", None))
    run(loop, rec._handle(snap("One"), "media", None))
    assert rec.active is not None and rec.active.replace_id == first["id"]


def test_ads_and_blank_titles_are_ignored(recorder, clock):
    rec, loop = recorder
    run(loop, rec._handle(snap("Advertisement", artist="Spotify"), "media", None))
    assert rec.active is None
    run(loop, rec._handle(snap("", artist=""), "media", None))
    assert rec.active is None


def test_browser_source_needs_extension(recorder, clock):
    rec, loop = recorder
    run(loop, rec._handle(snap("Some video", artist="Channel", app="chrome.exe"), "media", None))
    assert rec.active is None
    assert any(e["kind"] == "skipped" and e["reason"] == "browser_unverified" for e in rec.events)


def test_long_items_are_skipped(recorder, clock):
    rec, loop = recorder
    run(loop, rec._handle(snap("Episode 12", artist="Some Podcast", end_ms=2_400_000), "media", None))
    assert rec.active is None
    assert any(e["kind"] == "skipped" and e["reason"] == "too_long" for e in rec.events)


def test_paused_recorder_does_not_start_takes(recorder, clock):
    rec, loop = recorder
    rec.paused = True
    run(loop, rec._handle(snap("One"), "media", None))
    assert rec.active is None
    assert any(e["kind"] == "skipped" and e["reason"] == "paused_by_user" for e in rec.events)


def test_stop_at_the_end_is_a_normal_finish(recorder, clock):
    """YouTube reports 'stopped' when a video ends, before the next starts; that is not ending early."""
    rec, loop = recorder
    run(loop, rec._handle(snap("One", end_ms=120_000), "media", None))
    clock.advance(120)
    run(loop, rec._handle(snap("One", status=S.STOPPED, pos_ms=120_000, end_ms=120_000), "playback", None))
    kept = [e for e in rec.events if e["kind"] == "kept"]
    assert kept and kept[0]["title"] == "One"


def test_stop_in_the_middle_is_ending_early(recorder, clock):
    rec, loop = recorder
    run(loop, rec._handle(snap("One", end_ms=120_000), "media", None))
    clock.advance(40)
    run(loop, rec._handle(snap("One", status=S.STOPPED, pos_ms=40_000, end_ms=120_000), "playback", None))
    d = [e for e in rec.events if e["kind"] == "discarded"]
    assert d and "stopped" in d[0]["reasons"]


def test_overrun_tick_closes_take(recorder, clock):
    rec, loop = recorder
    run(loop, rec._handle(snap("One", end_ms=60_000), "media", None))
    clock.advance(70)
    run(loop, rec._tick())
    assert rec.active is None
    assert any(e["kind"] in ("kept", "discarded") for e in rec.events)
