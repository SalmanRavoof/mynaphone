# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""State-machine tests: drive the recorder with synthetic media-session snapshots and a fake capture."""
import asyncio
import datetime as dt
import glob
import logging
import time

import numpy as np
import pytest

from mynaphone import smtc as S
from mynaphone.bridge import BridgeEvent, SpotifyState
from mynaphone.capture import Take
from mynaphone.daemon import Recorder


class FakeCapture:
    """Produces a tone for exactly the time a take was open. With sends_audio off, the app sent no audio at
    all, as Spotify does while it waits for data on a dropped connection."""

    def __init__(self, clock, rate=48000):
        self.clock, self.rate, self.channels = clock, rate, 2
        self.device_name = "fake"
        self.healthy = True
        self._take = None
        self.ring_seconds = 3.0
        self.sends_audio = True
        self.tone = 0.3                 # 0 sends digital silence
        self.last_audio_at = self.last_sound_at = None     # set by hand for the silence watch

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
        x = (self.tone * np.sin(2 * np.pi * 440 * np.arange(n) / self.rate)).astype(np.float32)
        t.chunks = [np.stack([x, x], axis=1)] if self.sends_audio else []
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
def recorder(tmp_config, clock, monkeypatch):
    import mynaphone.daemon as d
    monkeypatch.setattr(d, "app_session_volume", lambda app: None)     # not this PC's real Volume Mixer
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    rec = Recorder(tmp_config, loop)
    rec.captures = {"*": FakeCapture(clock)}
    rec.events = []
    rec.on_event = rec.events.append
    _RECORDERS[loop] = rec
    yield rec, loop
    _RECORDERS.pop(loop, None)
    rec._writer.shutdown(wait=True)
    loop.run_until_complete(rec._cancel_covers())
    loop.close()


_RECORDERS = {}


def run(loop, coro):
    """Run one step, then wait for the takes it ended to be saved: the recorder saves them in the background."""
    result = loop.run_until_complete(coro)
    rec = _RECORDERS.get(loop)
    if rec is not None:
        loop.run_until_complete(rec.settle())
    return result


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


def test_long_pause_mid_song_is_not_taken_as_the_end(recorder, clock):
    """The Gathering of the Pact (2026-10-09) paused at 0:42; a second pause event 90 s later was taken as
    the song ending because the clock had passed its last seconds while the song stood still."""
    rec, loop = recorder
    run(loop, rec._handle(snap("One", end_ms=140_000), "media", None))
    clock.advance(42)
    run(loop, rec._handle(snap("One", status=S.PAUSED, pos_ms=42_000, end_ms=140_000), "playback", None))
    clock.advance(90)
    run(loop, rec._handle(snap("One", status=S.PAUSED, pos_ms=42_000, end_ms=140_000), "playback", None))
    assert rec.active is not None and rec.active.flags["paused"]
    assert not [e for e in rec.events if e["kind"] in ("kept", "discarded")]


def test_pause_after_a_resume_counts_only_playing_time(recorder, clock):
    rec, loop = recorder
    run(loop, rec._handle(snap("One", end_ms=120_000), "media", None))
    clock.advance(30)
    run(loop, rec._handle(snap("One", status=S.PAUSED, pos_ms=30_000, end_ms=120_000), "playback", None))
    clock.advance(60)
    run(loop, rec._handle(snap("One", pos_ms=30_000, end_ms=120_000), "playback", None))       # resumed
    clock.advance(50)   # 140 s since the start, but only 80 s of the song
    run(loop, rec._handle(snap("One", status=S.PAUSED, pos_ms=80_000, end_ms=120_000), "playback", None))
    assert rec.active is not None
    clock.advance(1)
    run(loop, rec._handle(snap("One", pos_ms=80_000, end_ms=120_000), "playback", None))       # resumed
    clock.advance(35)   # the song's last 5 s
    run(loop, rec._handle(snap("One", status=S.PAUSED, pos_ms=115_000, end_ms=120_000), "playback", None))
    assert rec.active is None
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
    # readings are brought up to the wall clock, which the fake clock doesn't stop, so a slow runner moves the
    # lag both ways (a first reading that waited starts the take that much earlier)
    assert not rec.active.flags.get("buffering") and 1_650 <= rec.active.flags["start_lag_ms"] <= 1_950
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
    # each reading is brought up to the wall clock, which keeps running, so a slow runner moves the lag both
    # ways: -1943 when the timeline reading waited, -1899 when the first reading did (the take starts that early)
    assert not rec.active.flags.get("seek") and -2_150 <= rec.active.flags["start_lag_ms"] <= -1_850
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


def test_stuck_cover_read_does_not_keep_the_take(recorder, clock, monkeypatch):
    """Thumbnail reads that never finished held their takes, so every song's audio stayed in memory until the
    app quit: 69 of 70 songs on 13 October 2026, and python.exe at 16.3 GB on the 4th."""
    import gc
    import weakref

    import mynaphone.daemon as D
    rec, loop = recorder
    monkeypatch.setattr(D, "COVER_WAIT_SECONDS", 0.05)
    held = []           # Windows keeps a stuck read's callback, and through it the waiting task, alive

    async def never_returns(session, with_thumbnail=False):
        held.append(asyncio.get_running_loop().create_future())
        await held[-1]
    monkeypatch.setattr(D.S, "snapshot", never_returns)
    run(loop, rec._handle(snap("One"), "media", FakeSession()))
    take = weakref.ref(rec.active.take)
    clock.advance(180)
    run(loop, rec._handle(snap("Two"), "media", None))              # One is written out
    assert [e for e in rec.events if e["kind"] == "kept" and e["title"] == "One"]
    gc.collect()
    assert take() is None or not take().chunks
    clock.advance(1.0)              # the loop's timers run on the fake clock too

    async def spin():
        for _ in range(20):
            await asyncio.sleep(0)
    run(loop, spin())
    assert not [t for t in asyncio.all_tasks(loop) if "_fetch_cover" in repr(t.get_coro())]


def test_volume_mixer_lookup_stays_off_the_recorder_thread(monkeypatch):
    """Its CoInitialize on the recorder's event loop thread stopped Windows Runtime reads from finishing."""
    import threading

    from mynaphone import sessions
    seen = []
    monkeypatch.setattr(sessions, "_app_session_volume",
                        lambda name: seen.append(threading.get_ident()) or (1.0, False))
    assert sessions.app_session_volume("Spotify.exe") == (1.0, False)
    assert seen and seen[0] != threading.get_ident()


def test_stuck_volume_lookup_neither_stalls_takes_nor_holds_up_exit(monkeypatch):
    """Without sound devices the lookup may never return: GitHub's test runner waited on it forever at exit."""
    import threading

    from mynaphone import sessions
    release = threading.Event()
    monkeypatch.setattr(sessions, "_app_session_volume", lambda name: release.wait())
    try:
        assert sessions.app_session_volume("Spotify.exe", timeout=0.1) is None      # gave up waiting
        started = time.perf_counter()
        assert sessions.app_session_volume("Spotify.exe", timeout=5.0) is None      # skipped, not queued
        assert time.perf_counter() - started < 1.0
        assert [t.daemon for t in threading.enumerate() if t.name == "volume-mixer"] == [True]
    finally:
        release.set()
        for _ in range(200):
            if not sessions._mixer_busy.is_set():
                break
            time.sleep(0.01)


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


def _youtube(clock, browser, video_id="abc", **kw):
    from mynaphone.bridge import YouTubeState
    return YouTubeState(video_id=video_id, is_music=True, paused=False, duration_s=180.0, received_at=clock(),
                        browser=browser, **kw)


def test_browser_take_needs_the_extension_in_that_browser(recorder, clock):
    """Brave's extension saying a song plays there vouches for Brave's media session, never for Vivaldi's."""
    from mynaphone.bridge import Bridge
    rec, loop = recorder
    rec.bridge = Bridge(loop, rec.queue, 0)
    rec.bridge.youtube_by_browser["brave.exe"] = _youtube(clock, "brave.exe")
    run(loop, rec._handle(snap("A video", artist="Channel", app="vivaldi.exe"), "media", None))
    assert rec.active is None
    assert any(e["kind"] == "skipped" and e["reason"] == "browser_unverified" for e in rec.events)
    run(loop, rec._handle(snap("A song", artist="Singer", app="brave.exe"), "media", None))
    assert rec.active is not None and rec.active.meta.source_uri == "youtube:video:abc"
    assert rec.active.meta.quality_tier == "youtube"


def test_another_browsers_pause_leaves_the_take_alone(recorder, clock):
    """The same video paused in Chrome says nothing about the copy Brave is playing."""
    from mynaphone.bridge import Bridge, YouTubeEvent, YouTubeState
    rec, loop = recorder
    rec.bridge = Bridge(loop, rec.queue, 0)
    rec.bridge.youtube_by_browser["brave.exe"] = _youtube(clock, "brave.exe")
    run(loop, rec._handle(snap("A song", artist="Singer", app="brave.exe"), "media", None))
    clock.advance(30)
    for browser in ("chrome.exe", "brave.exe"):
        paused = YouTubeState(video_id="abc", paused=True, received_at=clock(), browser=browser, event="pause")
        run(loop, rec._on_youtube(YouTubeEvent(state=paused)))
        assert bool(rec.active.flags.get("paused")) == (browser == "brave.exe")


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


@pytest.mark.parametrize("ending", ["stopped", "overrun"])
def test_take_with_no_audio_leaves_no_file(recorder, clock, tmp_config, caplog, ending):
    """Spotify can show a song as playing while it waits for data and send no audio at all. Stopped after
    a few seconds, or closed by the overrun check after the whole song, such a take has nothing left
    after trimming; it used to leave a 0-byte FLAC, a JSON and a tagging warning in the discard folder."""
    rec, loop = recorder
    rec.captures["*"].sends_audio = False
    run(loop, rec._handle(snap("One", end_ms=198_000), "media", None))
    if ending == "stopped":
        clock.advance(5.0)                                                 # past the 2 s quick-skip drop
        run(loop, rec._handle(snap("One", status=S.STOPPED, pos_ms=5_000, end_ms=198_000), "playback", None))
    else:
        clock.advance(204.0)
        run(loop, rec._tick())
    d = [e for e in rec.events if e["kind"] == "discarded"]
    assert d and d[0]["title"] == "One" and d[0]["captured_ms"] == 0
    assert "length_mismatch:0.0s_vs_198.0s" in d[0]["reasons"]
    row = rec.store.recent_takes(1)[0]
    assert row["title"] == "One" and row["verdict"] == "discard" and row["file_path"] is None
    assert list(tmp_config.paths.discard_dir.iterdir()) == []
    # only the app's own loggers count; asyncio reports other tests' leftover cover tasks whenever they are collected
    assert not [r for r in caplog.records if r.name.startswith("mynaphone") and r.levelno >= logging.WARNING]


def test_saving_a_song_does_not_hold_up_the_next_one(recorder, clock, monkeypatch):
    """Writing a song out used to block the event queue for 5 to 9 s, so the next song's first timeline readings
    were handled late, and on October 2 seven complete songs looked seeked."""
    import threading
    rec, loop = recorder
    release = threading.Event()
    real_finalize = rec._finalize

    def slow_finalize(*args):
        release.wait(10)
        real_finalize(*args)

    monkeypatch.setattr(rec, "_finalize", slow_finalize)
    play_full_song(rec, loop, clock, "One")
    loop.run_until_complete(rec._handle(snap("Two"), "media", None))     # the boundary returns at once
    assert rec.active.meta.title == "Two"
    assert rec._saves and not [e for e in rec.events if e["kind"] == "kept"]
    clock.advance(10)
    loop.run_until_complete(rec._handle(snap("Two", pos_ms=10_000), "timeline", None))
    assert "start_lag_ms" in rec.active.flags and not rec.active.flags.get("seek")
    release.set()
    loop.run_until_complete(rec.settle())
    assert [e["title"] for e in rec.events if e["kind"] == "kept"] == ["One"]


# -- playing but silent (silence.py) ---------------------------------------------------------

def spotify_bridge(rec, loop, clock, **state):
    """The Spotify bridge, not started, with Spotify's own state; plays() keeps the state fresh."""
    from mynaphone.bridge import Bridge
    rec.bridge = Bridge(loop, rec.queue, 0)
    rec.bridge.state = SpotifyState(received_at=clock(), is_paused=False, **state)
    return rec.bridge


def plays(rec, loop, clock, seconds, title="One", start_ms=0, packets=False, bridge=None, moving=True):
    """Spotify plays title for this many seconds: a timeline reading and a tick each second. With packets, silent
    audio arrives; without, none. moving=False holds the position, as while Spotify loads the song.

    The warning can come a second after the 15 s mark. Before Python 3.13 Windows' clock ticks every 15.6 ms, so a
    reading's age can take up to 15 ms off the song's time, and the mark then falls on the next tick."""
    cap = rec.captures["*"]
    for i in range(1, seconds + 1):
        clock.advance(1.0)
        if bridge is not None:
            bridge.state.received_at = clock()
        if packets:
            cap.last_audio_at = clock()
        run(loop, rec._handle(snap(title, pos_ms=start_ms + (i * 1000 if moving else 0)), "timeline", None))
        run(loop, rec._tick())


def begin(rec, loop, title="One", **kw):
    run(loop, rec._handle(snap(title, **kw), "media", None))
    run(loop, rec._tick())


def quiet_events(rec):
    return [e for e in rec.events if e["kind"] == "silence"]


def test_spotify_playing_with_no_audio_warns_once_and_names_why(recorder, clock, caplog):
    rec, loop = recorder
    rec.captures["*"].sends_audio = False
    begin(rec, loop)
    with caplog.at_level(logging.INFO, logger="mynaphone"):
        plays(rec, loop, clock, 14)
        assert not quiet_events(rec)
        plays(rec, loop, clock, 2, start_ms=14_000)
    q = quiet_events(rec)
    assert len(q) == 1 and q[0]["new"] and q[0]["cause"] == "no_audio" and q[0]["app"] == "Spotify.exe"
    assert q[0]["headline"] == "Mynaphone can't hear Spotify" and "exclusive mode" in q[0]["text"]
    assert q[0]["tip"] == "Mynaphone can't hear Spotify"
    warned = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warned == ["no sound from Spotify.exe for 15 s of One: " + q[0]["text"]]
    # it goes on into the next song: one warning for the whole stretch, and each take names the cause first
    plays(rec, loop, clock, 164, start_ms=16_000)
    run(loop, rec._handle(snap("Two"), "media", None))
    plays(rec, loop, clock, 60, title="Two")
    assert len(quiet_events(rec)) == 1
    clock.advance(120)
    run(loop, rec._handle(snap("Three"), "media", None))
    d = [e for e in rec.events if e["kind"] == "discarded"]
    assert [x["title"] for x in d] == ["One", "Two"] and all(x["reasons"][0] == "no_sound:no_audio" for x in d)


def test_a_song_that_opens_quietly_is_kept_and_the_warning_ends(recorder, clock, caplog):
    """Silent audio arriving is also how a song with a long, quiet opening looks, so it doesn't spoil the take."""
    rec, loop = recorder
    begin(rec, loop)
    plays(rec, loop, clock, 20, packets=True)
    assert [e["cause"] for e in quiet_events(rec)] == ["silent_audio"]
    rec.captures["*"].last_sound_at = clock()
    with caplog.at_level(logging.INFO, logger="mynaphone"):
        plays(rec, loop, clock, 1, start_ms=20_000)
    assert [e for e in rec.events if e["kind"] == "sound"] == [{"kind": "sound", "app": "Spotify.exe"}]
    assert "the no-sound warning for Spotify.exe ended after 21 s: sound came back" in caplog.text
    clock.advance(159)
    run(loop, rec._handle(snap("Two"), "media", None))
    assert [e["title"] for e in rec.events if e["kind"] == "kept"] == ["One"]


def test_a_recording_that_came_out_silent_is_not_kept(recorder, clock):
    rec, loop = recorder
    rec.captures["*"].tone = 0.0
    begin(rec, loop)
    plays(rec, loop, clock, 20, packets=True)
    clock.advance(160)
    run(loop, rec._handle(snap("Two"), "media", None))
    d = [e for e in rec.events if e["kind"] == "discarded"]
    assert d and d[0]["reasons"] == ["no_sound:silent_audio"]


def test_muted_in_the_volume_mixer(recorder, clock, monkeypatch):
    import threading

    import mynaphone.daemon as D
    rec, loop = recorder
    rec.captures["*"].tone = 0.0
    asked = []
    monkeypatch.setattr(D, "app_session_volume", lambda app: asked.append(threading.get_ident()) or (1.0, True))
    begin(rec, loop)
    plays(rec, loop, clock, 16, packets=True)
    q = quiet_events(rec)
    assert [e["cause"] for e in q] == ["muted"] and "Volume Mixer" in q[0]["text"]
    assert threading.get_ident() in asked                  # the check at the take's start, as before
    assert len(set(asked)) == 2                            # and the warning's, on another thread
    clock.advance(164)
    run(loop, rec._handle(snap("Two"), "media", None))
    d = [e for e in rec.events if e["kind"] == "discarded"][0]
    assert "mixer_volume:0" in d["reasons"] and not [r for r in d["reasons"] if r.startswith("no_sound")]


def test_spotify_connect_playing_on_another_device(recorder, clock):
    rec, loop = recorder
    spotify_bridge(rec, loop, clock, name="One", device={"name": "Living Room", "type": "Speaker", "isLocal": False})
    rec.captures["*"].sends_audio = False
    begin(rec, loop)
    plays(rec, loop, clock, 16, bridge=rec.bridge)
    q = quiet_events(rec)
    assert [(e["cause"], e["device"]) for e in q] == [("connect", "Living Room")] and "Living Room" in q[0]["text"]


def test_spotifys_own_volume_at_zero(recorder, clock):
    rec, loop = recorder
    spotify_bridge(rec, loop, clock, name="One", volume=0.0, device={"name": "This PC", "isLocal": True})
    rec.captures["*"].tone = 0.0
    begin(rec, loop)
    plays(rec, loop, clock, 16, packets=True, bridge=rec.bridge)
    assert [e["cause"] for e in quiet_events(rec)] == ["app_volume"]


def test_a_capture_that_never_attached(recorder, clock):
    """No take starts ("audio capture not running yet"), and the warning says why every song is skipped."""
    rec, loop = recorder
    rec.captures["*"].healthy = False
    begin(rec, loop)
    assert rec.active is None
    plays(rec, loop, clock, 16)
    assert [e["cause"] for e in quiet_events(rec)] == ["capture"]


def test_spotify_buffering_or_stuck_at_the_start_never_warns(recorder, clock):
    """Spotify's bridge says when it buffers, and without the bridge its position stands still: on October 28, 2026
    it said it was playing at 0:00 for 5 s while it started up."""
    rec, loop = recorder
    rec.captures["*"].sends_audio = False
    spotify_bridge(rec, loop, clock, name="One", is_buffering=True)
    begin(rec, loop)
    plays(rec, loop, clock, 30, bridge=rec.bridge)
    rec.bridge = None
    plays(rec, loop, clock, 30, start_ms=30_000, moving=False)
    assert not quiet_events(rec)


def test_a_paused_spotify_or_recorder_never_warns(recorder, clock):
    rec, loop = recorder
    rec.captures["*"].sends_audio = False
    begin(rec, loop)
    plays(rec, loop, clock, 10)
    for _ in range(30):
        clock.advance(1.0)
        run(loop, rec._handle(snap("One", status=S.PAUSED, pos_ms=10_000), "playback", None))
        run(loop, rec._tick())
    rec.paused = True
    plays(rec, loop, clock, 30, start_ms=10_000)
    assert not quiet_events(rec)


def test_a_player_that_closes_ends_the_warning(recorder, clock):
    rec, loop = recorder
    rec.captures["*"].sends_audio = False
    begin(rec, loop)
    plays(rec, loop, clock, 16)
    assert quiet_events(rec)
    run(loop, rec._on_smtc(S.SmtcEvent("sessions", "", None)))          # Spotify's media session is gone
    assert {"kind": "sound", "app": "Spotify.exe"} in rec.events and not rec.silence.quiet


def test_the_warning_can_be_turned_off(recorder, clock):
    rec, loop = recorder
    rec.silence.seconds = 0
    rec.captures["*"].sends_audio = False
    begin(rec, loop)
    plays(rec, loop, clock, 30)
    assert not quiet_events(rec)


def test_the_cause_is_looked_at_again_while_the_warning_stands(recorder, clock):
    rec, loop = recorder
    rec.captures["*"].sends_audio = False
    begin(rec, loop)
    plays(rec, loop, clock, 16)
    rec.captures["*"].healthy = False                                  # the capture helper went away
    plays(rec, loop, clock, 12, start_ms=16_000)
    assert [(e["cause"], e["new"]) for e in quiet_events(rec)] == [("no_audio", True), ("capture", False)]


def youtube_music(rec, loop, clock):
    from mynaphone.bridge import Bridge
    rec.bridge = Bridge(loop, rec.queue, 0)
    yt = rec.bridge.youtube_by_browser["chrome.exe"] = _youtube(clock, "chrome.exe", video_id="v1", title="One")
    rec.captures["*"].sends_audio = False
    return yt


def test_youtube_music_in_a_browser_counts_while_its_song_records(recorder, clock):
    rec, loop = recorder
    yt = youtube_music(rec, loop, clock)
    begin(rec, loop, app="chrome.exe")
    assert rec.active is not None and rec.active.app == "chrome.exe"
    for i in range(1, 16):
        clock.advance(1.0)
        yt.position_s, yt.received_at = float(i), clock()
        run(loop, rec._tick())
    q = quiet_events(rec)
    assert [(e["app"], e["cause"]) for e in q] == [("chrome.exe", "no_audio")]
    assert q[0]["headline"] == "Mynaphone can't hear Chrome"
    assert "tab isn't muted" in q[0]["text"]


def test_a_video_that_is_loading_never_counts(recorder, clock):
    """The extension reports a playing video once a second, and goes quiet while it loads."""
    rec, loop = recorder
    yt = youtube_music(rec, loop, clock)
    begin(rec, loop, app="chrome.exe")
    for _ in range(30):
        clock.advance(1.0)
        run(loop, rec._tick())
    assert yt.position_s == 0 and not quiet_events(rec)


# -- recording a playlist ------------------------------------------------------------------------

def _job_bridge(rec, loop):
    """The bridge object, with the job's commands (play, pause, shuffle) answered here."""
    from mynaphone.bridge import Bridge
    bridge = Bridge(loop, rec.queue, 0)
    bridge.sent = []

    async def request(do, timeout=30.0, **params):
        bridge.sent.append((do, params.get("uri") or params.get("mode")))
        return {"shuffle_was": 0} if do == "play" else {}

    bridge.request = request
    rec.bridge = bridge
    return bridge


def _album(rec, tmp_config, have, n=3):
    """An album of n songs as the bridge lists them, with the ones in `have` in the library."""
    tracks = [{"index": i, "uri": f"spotify:track:{i}", "uid": f"u{i}", "name": f"Song {i}", "artists": ["Artist"],
               "duration_ms": 180_000, "playable": True} for i in range(n)]
    for i in have:
        f = tmp_config.paths.library_dir / "Artists" / "Artist" / "Album" / f"Song {i}.m4a"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"m4a")
        rec.store.add_track(artist="Artist", title=f"Song {i}", duration_ms=180_000, source_uri=f"spotify:track:{i}",
                            quality_tier="high", state="library", file_path=str(f))
    return tracks


def _plays(bridge):
    return [uri for do, uri in bridge.sent if do == "play"]


def test_a_playlist_waits_for_its_last_songs_verdict(recorder, clock, tmp_config):
    """Monsoon Season, November 20, 2026: a song the library had started while the last missing one was being
    saved, and the job played that one again. Here the bridge names nothing, so the job goes by the titles."""
    from mynaphone.playlist_job import PlaylistJob
    rec, loop = recorder
    bridge = _job_bridge(rec, loop)
    rec.job = PlaylistJob(rec, "spotify:album:a", "Album", _album(rec, tmp_config, have=(0, 2)))
    run(loop, rec.job.start())
    run(loop, rec._handle(snap("Song 1"), "media", None))
    clock.advance(180)
    run(loop, rec._handle(snap("Song 2"), "media", None))
    for _ in range(3):
        run(loop, asyncio.sleep(0))
    assert _plays(bridge) == ["spotify:track:1"]
    assert [e["title"] for e in rec.events if e["kind"] == "kept"] == ["Song 1"]
    assert rec.job is None and ("pause", None) in bridge.sent


def test_a_song_the_library_has_from_another_release_isnt_recorded_again(recorder, clock, tmp_config):
    """Holiday, November 20, 2026: the library had it from its COLORS single, under another Spotify id, a longer title
    and 4 s less, so nothing matched it until Spotify gave the song's ISRC a moment after it started."""
    import json

    from mynaphone.playlist_job import PlaylistJob
    rec, loop = recorder
    bridge = _job_bridge(rec, loop)
    f = tmp_config.paths.library_dir / "Holiday.m4a"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"m4a")
    colors = rec.store.add_track(artist="Hanumankind", title="Holiday - A COLORS SHOW", duration_ms=178_956,
                                 source_uri="spotify:track:colors", quality_tier="high", state="library",
                                 file_path=str(f), identity_json=json.dumps({"isrc": "USUG12501292"}))
    tracks = [{"index": 0, "uri": "spotify:track:holiday", "name": "Holiday", "artists": ["Hanumankind"],
               "duration_ms": 183_000, "playable": True},
              {"index": 1, "uri": "spotify:track:sicko", "name": "Sicko", "artists": ["Hanumankind"],
               "duration_ms": 246_000, "playable": True}]
    rec.job = PlaylistJob(rec, "spotify:album:ms", "Monsoon Season", tracks)
    assert rec.job.todo == [0, 1]
    run(loop, rec.job.start())
    run(loop, rec._handle(snap("Holiday", artist="Hanumankind", end_ms=183_000), "media", None))
    assert rec.active is not None
    clock.advance(1)
    bridge.state = SpotifyState(uri="spotify:track:holiday", name="Holiday", duration_ms=183_000,
                                track_info={"isrc": "USUG12501292", "source": "spclient"}, received_at=clock())
    run(loop, rec._on_bridge(BridgeEvent(state=bridge.state)))
    run(loop, asyncio.sleep(0))
    assert rec.active is None and not [e for e in rec.events if e["kind"] in ("kept", "discarded")]
    assert _plays(bridge) == ["spotify:track:holiday", "spotify:track:sicko"]
    assert rec.store.find_archived("", "", 0, "spotify:track:holiday")["id"] == colors      # by its alias now
    assert json.loads(rec.store.recent_takes(1)[0]["reasons"]) == ["already_archived_skipped"]


def test_stopping_the_recorder_ends_the_playlist(recorder, clock, tmp_config, monkeypatch):
    """The playlist kept going with the recorder gone: its shuffle stayed off and its file wasn't written."""
    from mynaphone.playlist_job import PlaylistJob
    rec, loop = recorder
    bridge = _job_bridge(rec, loop)

    async def nothing():
        return None

    bridge.start = bridge.stop = nothing
    rec.smtc = type("Smtc", (), {"start": lambda self: nothing(), "sessions": lambda self: [],
                                 "stop": lambda self: None})()
    for part in (rec.foreign, rec.post):
        monkeypatch.setattr(part, "start", lambda: None)
        monkeypatch.setattr(part, "stop", lambda: None)
    rec.job = PlaylistJob(rec, "spotify:album:a", "Album", _album(rec, tmp_config, have=()))
    rec.job.shuffle_was = 1
    rec.request_stop()
    loop.run_until_complete(rec.run())
    assert rec.job is None and ("restore_shuffle", 1) in bridge.sent and ("pause", None) not in bridge.sent
    assert (tmp_config.paths.library_dir / "Playlists" / "Album.m3u8").exists()
    job = [e for e in rec.events if e["kind"] == "job"][-1]
    assert job["done"] and job["why"] == "the recorder stopped"
