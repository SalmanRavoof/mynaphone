# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""The playing-but-silent watch on its own: what counts as a song playing in silence, and when its warning starts
and ends. The recorder's side, with the causes, is in test_daemon.py."""
import numpy as np
import pytest

from mynaphone import silence as Q
from mynaphone.capture import _RingCapture


class Cap:
    """What the watch reads from a capture: when it last heard sound."""

    def __init__(self):
        self.last_sound_at = None
        self.last_audio_at = None
        self.healthy = True


@pytest.fixture
def watch(clock):
    return Q.SilenceWatch(15)


def play(watch, clock, cap, seconds, key=("a", "one", "al"), start_ms=0, app="Spotify.exe", sound_at=None):
    """Step once a second while the song plays from start_ms for this many seconds; return what each step said."""
    said = []
    for i in range(int(seconds) + 1):
        if sound_at is not None and i == sound_at:
            cap.last_sound_at = clock()
        said.append(watch.step(app, key, True, start_ms + i * 1000, cap))
        clock.advance(1.0)
    return said


def test_a_song_that_plays_in_silence_warns_after_15_seconds_of_it(watch, clock):
    cap = Cap()
    said = play(watch, clock, cap, 20)
    assert said.index(Q.QUIET) == 15 and said.count(Q.QUIET) == 1
    q = watch.quiet["Spotify.exe"]
    assert q.noticed - q.since == 15.0


def test_sound_after_the_start_means_the_song_is_fine(watch, clock):
    """A quiet stretch later in a song, such as the silence before a hidden track, never sets it off."""
    cap = Cap()
    assert Q.QUIET not in play(watch, clock, cap, 120, sound_at=4)


def test_the_last_songs_tail_is_not_the_new_songs_sound(watch, clock):
    """Spotify's sound runs on for up to 2.2 s after the next song is named."""
    cap = Cap()
    play(watch, clock, cap, 30, key=("a", "one", "al"), sound_at=2)
    said = play(watch, clock, cap, 20, key=("a", "two", "al"), sound_at=1)      # the end of One
    assert said.index(Q.QUIET) == 15


def test_a_stall_never_counts(watch, clock):
    """While Spotify loads a song, or starts up, its position stands still (18.5 s of it on October 28, 2026)."""
    cap = Cap()
    said = [watch.step("Spotify.exe", ("a", "one", "al"), True, 0, cap)]
    for _ in range(40):                                        # "playing" at 0:00 for 40 s
        clock.advance(1.0)
        said.append(watch.step("Spotify.exe", ("a", "one", "al"), True, 0, cap))
    assert Q.QUIET not in said
    said = play(watch, clock, cap, 20)
    assert said.index(Q.QUIET) == 15


def test_a_pause_starts_the_count_over(watch, clock):
    cap = Cap()
    assert Q.QUIET not in play(watch, clock, cap, 10)
    for _ in range(30):
        assert watch.step("Spotify.exe", ("a", "one", "al"), False, 10_000, cap) is None
        clock.advance(1.0)
    said = play(watch, clock, cap, 20, start_ms=10_000)
    assert said.index(Q.QUIET) == 15


def test_a_seek_forward_is_not_time_played(watch, clock):
    cap = Cap()
    watch.step("Spotify.exe", ("a", "one", "al"), True, 0, cap)
    clock.advance(2.0)
    assert watch.step("Spotify.exe", ("a", "one", "al"), True, 60_000, cap) is None
    said = play(watch, clock, cap, 14, start_ms=60_000)
    assert said.index(Q.QUIET) == 13                          # 15 s after the song began, not 2


def test_one_warning_per_quiet_stretch(watch, clock):
    """However many songs the silence lasts, and the next stretch warns again."""
    cap = Cap()
    said = play(watch, clock, cap, 20, key=("a", "one", "al"))
    said += play(watch, clock, cap, 60, key=("a", "two", "al"))
    assert said.count(Q.QUIET) == 1
    cap.last_sound_at = clock()
    clock.advance(1.0)
    assert watch.step("Spotify.exe", ("a", "two", "al"), True, 61_000, cap) == Q.SOUND
    assert "Spotify.exe" not in watch.quiet
    assert Q.QUIET not in play(watch, clock, cap, 60, key=("a", "two", "al"), start_ms=62_000)
    said = play(watch, clock, cap, 20, key=("a", "three", "al"))
    assert said.count(Q.QUIET) == 1


def test_a_player_that_closes_ends_its_warning(watch, clock):
    cap = Cap()
    play(watch, clock, cap, 20)
    assert watch.forget("Spotify.exe") is True
    assert watch.forget("Spotify.exe") is False and not watch.quiet


def test_each_app_has_its_own_watch(watch, clock):
    spotify, chrome = Cap(), Cap()
    chrome.last_sound_at = clock()
    for i in range(20):
        watch.step("Spotify.exe", ("a", "one", "al"), True, i * 1000, spotify)
        watch.step("chrome.exe", ("b", "video", ""), True, i * 1000, chrome)
        chrome.last_sound_at = clock()
        clock.advance(1.0)
    assert list(watch.quiet) == ["Spotify.exe"]


def test_the_capture_notes_when_it_last_heard_sound(clock):
    cap = _RingCapture(3.0)
    cap.rate = 48000
    cap._push(np.zeros((4800, 2), dtype=np.float32))
    assert cap.last_audio_at == clock() and cap.last_sound_at is None
    clock.advance(1.0)
    cap._push(np.full((4800, 2), 10 ** (-90 / 20), dtype=np.float32))    # -90 dBFS: what a waiting player sends
    assert cap.last_audio_at == clock() and cap.last_sound_at is None
    clock.advance(1.0)
    cap._push(np.full((4800, 2), 0.01, dtype=np.float32))
    assert cap.last_sound_at == clock()


def test_words_for_every_cause():
    assert Q.app_name("Spotify.exe") == "Spotify" and Q.app_name("msedge.exe") == "Edge"
    assert Q.app_name(r"C:\Apps\Tidal.exe") == "Tidal" and Q.app_name("") == "the app"
    assert Q.headline("Spotify.exe") == "Mynaphone can't hear Spotify" == Q.tray_tip("Spotify.exe")
    causes = (Q.CONNECT, Q.CAPTURE, Q.MUTED, Q.APP_VOLUME, Q.NO_AUDIO, Q.SILENT_AUDIO)
    texts = [Q.explain(c, "Spotify.exe") for c in causes]
    assert len(set(texts)) == len(causes) and all("Spotify" in t for t in texts)
    assert "Living Room" in Q.explain(Q.CONNECT, "Spotify.exe", "Living Room")
    browser = [Q.explain(c, "chrome.exe") for c in (Q.APP_VOLUME, Q.NO_AUDIO, Q.SILENT_AUDIO)]
    assert "YouTube player" in browser[0] and all("tab" in t for t in browser[1:])
    assert all(Q.reason_words(c) != Q.reason_words("") for c in causes)
