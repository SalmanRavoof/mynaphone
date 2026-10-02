# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio

import numpy as np

from mynaphone import export
from mynaphone.bridge import Bridge, SpotifyState
from mynaphone.capture import _RingCapture
from mynaphone.sessions import ForeignAudioMonitor, ForeignReport, ForeignSound


def test_spotify_tier_mapping():
    assert SpotifyState(quality={"bitrateLevel": 3}).tier == "high"
    assert SpotifyState(quality={"bitrateLevel": 4}).tier == "very_high"
    assert SpotifyState(quality={"bitrateLevel": 5, "losslessStatus": 2}).tier == "hifi"
    assert SpotifyState(quality={"bitrate_level": "very_high"}).tier == "very_high"
    assert SpotifyState(quality=None).tier == "unknown"


class _Loop:
    def call_soon_threadsafe(self, fn, *a):
        fn(*a)


def test_bridge_converts_spotify_lyrics_to_lrc():
    q = asyncio.Queue()
    b = Bridge(_Loop(), q, 0)
    b._store_lyrics({"uri": "spotify:track:1", "lyrics": {"synced": True, "language": "ta", "lines": [
        {"t": 1230, "w": "first"}, {"t": 61500, "w": "second"}]}})
    got = b.lyrics["spotify:track:1"]
    assert got["synced"] and got["language"] == "ta"
    assert got["lrc"] == "[00:01.23]first\n[01:01.50]second"
    assert not q.empty()
    b._store_lyrics({"uri": "spotify:track:2", "lyrics": {"synced": False, "lines": [{"t": None, "w": "plain"}]}})
    assert b.lyrics["spotify:track:2"]["lrc"] == "plain"


def test_ring_capture_reaches_back_in_time(monkeypatch):
    import mynaphone.capture as cap
    now = [100.0]
    monkeypatch.setattr(cap.time, "monotonic", lambda: now[0])
    r = _RingCapture(preroll_seconds=3.0)
    r.rate, r.channels = 10, 2          # 10 Hz for easy arithmetic
    for i in range(50):                 # 5 s of 0.1 s chunks
        now[0] += 0.1
        r._push(np.full((1, 2), float(i), np.float32))
    assert 2.9 <= r.ring_seconds <= 3.1  # trimmed to the pre-roll
    take = r.begin_take(now[0] - 1.0)   # reach back 1 s
    assert 9 <= len(take.chunks) <= 11
    now[0] += 0.1
    r._push(np.full((1, 2), 99.0, np.float32), glitch=True)
    assert take.overflows == 1
    done = r.end_take()
    assert done is take and done.t_end == now[0] and not r.recording
    assert done.audio()[-1, 0] == 99.0


def test_foreign_monitor_source_matching_and_report():
    m = ForeignAudioMonitor(["Spotify.exe"])
    assert m._is_source("spotify.exe") and m._is_source("mynaphone-capture.exe") and not m._is_source("chrome.exe")
    rep = ForeignReport([
        ForeignSound(1.0, "a.exe", -30.0), ForeignSound(2.0, "b.exe", -10.0), ForeignSound(3.0, "a.exe", -50.0)])
    assert rep.apps == ["a.exe", "b.exe"] and rep.max_db == -10.0


def test_export_plan_and_mirror(tmp_path):
    lib = tmp_path / "lib"
    (lib / "Artists" / "X" / "Singles").mkdir(parents=True)
    song = lib / "Artists" / "X" / "Singles" / "S.m4a"
    song.write_bytes(b"audio")
    (lib / "Artists" / "X" / "Singles" / "S.lrc").write_text("[00:01.00]x")
    dest = tmp_path / "usb"
    p = export.plan(lib, dest, include_lyrics=False)
    assert len(p.copy) == 1 and p.skip == 0
    export.run(p)
    assert (dest / "Artists" / "X" / "Singles" / "S.m4a").read_bytes() == b"audio"
    assert not (dest / "Artists" / "X" / "Singles" / "S.lrc").exists()
    p2 = export.plan(lib, dest)
    assert p2.copy == [] and p2.skip == 1
    stale = dest / "Artists" / "Old" / "gone.m4a"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")
    p3 = export.plan(lib, dest, mirror=True)
    assert p3.remove == [stale]
    export.run(p3)
    assert not stale.exists() and not stale.parent.exists()
    p4 = export.plan(lib, dest, include_lyrics=True)
    assert [d.name for _, d in p4.copy] == ["S.lrc"]
