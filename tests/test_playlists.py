# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Recording a playlist: the bridge's commands over a real local WebSocket, the job against a stand-in bridge,
and the M3U8 files the library gets."""
import asyncio
import json
import socket

import pytest
import websockets

from mynaphone import playlists
from mynaphone.bridge import Bridge, BridgeError
from mynaphone.playlist_job import PlaylistJob
from mynaphone.store import Store


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_commands_and_replies_over_the_bridge():
    async def scenario():
        loop = asyncio.get_running_loop()
        port = _free_port()
        details = []
        bridge = Bridge(loop, asyncio.Queue(), port)
        bridge.on_track_details = lambda uri, info, error: details.append((uri, info, error))
        await bridge.start()
        async with websockets.connect(f"ws://127.0.0.1:{port}/spotify") as ext:      # the Spicetify extension
            await asyncio.sleep(0.05)
            asked = asyncio.ensure_future(bridge.request("playlists", timeout=5))
            cmd = json.loads(await ext.recv())
            assert cmd["type"] == "command" and cmd["do"] == "playlists"
            await ext.send(json.dumps({"type": "reply", "id": cmd["id"], "ok": True,
                                       "result": {"playlists": [{"uri": "spotify:playlist:p", "name": "Car"}]}}))
            assert (await asked)["playlists"][0]["name"] == "Car"
            failing = asyncio.ensure_future(bridge.request("play", timeout=5, context="spotify:playlist:p"))
            cmd = json.loads(await ext.recv())
            assert cmd["context"] == "spotify:playlist:p"
            await ext.send(json.dumps({"type": "reply", "id": cmd["id"], "ok": False,
                                       "error": "Spotify is playing on another device"}))
            with pytest.raises(BridgeError, match="another device"):
                await failing
            await ext.send(json.dumps({"type": "track_details", "uri": "spotify:track:t",
                                       "info": {"isrc": "QMBZ92351475", "source": "spclient"}}))
            await ext.send(json.dumps({"type": "state", "uri": "spotify:ad:1", "name": "Ad", "isAd": True,
                                       "context": "spotify:playlist:p", "provider": "ad"}))
            await asyncio.sleep(0.1)
            assert details == [("spotify:track:t", {"isrc": "QMBZ92351475", "source": "spclient"}, None)]
            assert bridge.state.is_ad and bridge.state.context == "spotify:playlist:p"
            lost = asyncio.ensure_future(bridge.request("tracks", timeout=5, uri="spotify:playlist:p"))
            await ext.recv()
        with pytest.raises(BridgeError, match="disconnected"):
            await lost                                         # the extension went away before it answered
        with pytest.raises(BridgeError, match="isn't connected"):
            await bridge.request("pause")
        await bridge.stop()

    asyncio.run(scenario())


# -- the job ---------------------------------------------------------------------------------

def _tracks(n):
    return [{"index": i, "uri": f"spotify:track:{i}", "uid": f"u{i}", "name": f"Song {i}", "artists": ["A"],
             "album": {"name": "Album", "uri": "spotify:album:a"}, "duration_ms": 200_000, "playable": True}
            for i in range(n)]


class FakeBridge:
    def __init__(self):
        self.sent = []

    async def request(self, do, timeout=30.0, **params):
        self.sent.append((do, params.get("uri") or params.get("mode")))
        return {"shuffle_was": 1} if do == "play" else {}


class FakeRecorder:
    def __init__(self, cfg, store):
        self.cfg, self.store, self.bridge = cfg, store, FakeBridge()
        self.events, self.job = [], None

    def _emit(self, kind, **data):
        self.events.append((kind, data))


def _have(store, cfg, tracks, *indexes):
    for i in indexes:
        f = cfg.paths.library_dir / "Artists" / "A" / "Album" / f"{i:02d} Song {i}.m4a"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"m4a")
        store.add_track(artist="A", title=f"Song {i}", duration_ms=200_000, source_uri=tracks[i]["uri"],
                        state="library", file_path=str(f))


def test_the_job_records_only_whats_missing_and_retries_failures_once(tmp_config):
    store = Store(tmp_config.paths.db_path)
    rec = FakeRecorder(tmp_config, store)
    tracks = _tracks(5)
    _have(store, tmp_config, tracks, 0, 2)                    # songs 1, 3 and 4 are missing

    async def scenario():
        job = rec.job = PlaylistJob(rec, "spotify:playlist:p", "Car", tracks)
        await job.start()
        assert rec.bridge.sent == [("play", "spotify:track:1")]               # starts at the first missing song
        assert await job.on_track("spotify:track:1", archived=False) is False   # recorded as usual
        await job.on_result("spotify:track:1", kept=True, reasons=[])
        assert await job.on_track("spotify:track:2", archived=True) is True     # one you have: jump
        await asyncio.sleep(0)
        assert rec.bridge.sent[-1] == ("play", "spotify:track:3")
        await job.on_track("spotify:track:3", archived=False)
        await job.on_result("spotify:track:3", kept=False, reasons=["buffering"])
        await job.on_track("spotify:track:4", archived=False)
        await job.on_result("spotify:track:4", kept=True, reasons=[])
        await job.on_track("spotify:track:0", archived=True)   # the playlist came round: song 3 gets one more go
        await asyncio.sleep(0)
        assert rec.bridge.sent[-1] == ("play", "spotify:track:3") and job.tries == {3: 1}
        await job.on_track("spotify:track:3", archived=False)
        await job.on_result("spotify:track:3", kept=True, reasons=[])
        assert job.done and rec.job is None
        assert ("pause", None) in rec.bridge.sent and ("restore_shuffle", 1) in rec.bridge.sent
        assert [tracks[i]["name"] for i in job.saved] == ["Song 1", "Song 4", "Song 3"]

    asyncio.run(scenario())
    m3u = (tmp_config.paths.library_dir / "Playlists" / "Car.m3u8").read_text(encoding="utf-8")
    assert "../Artists/A/Album/00 Song 0.m4a" in m3u and "# not in your library yet: A - Song 1" in m3u


def test_picking_something_else_in_spotify_stops_the_job(tmp_config):
    store = Store(tmp_config.paths.db_path)
    rec = FakeRecorder(tmp_config, store)

    async def scenario():
        job = rec.job = PlaylistJob(rec, "spotify:playlist:p", "Car", _tracks(3))
        await job.start()
        await job.on_track("spotify:track:elsewhere", archived=False)
        assert job.done and rec.events[-1][1]["stopped"] and rec.events[-1][1]["why"] == "playback left the playlist"
        assert ("pause", None) not in rec.bridge.sent                 # you're listening to something else now

    asyncio.run(scenario())


def test_a_song_the_recorder_wont_take_is_left_out(tmp_config):
    store = Store(tmp_config.paths.db_path)
    rec = FakeRecorder(tmp_config, store)

    async def scenario():
        job = rec.job = PlaylistJob(rec, "spotify:album:a", "Album", _tracks(2))
        await job.start()
        job.on_skipped("spotify:track:0", "too_long")
        assert job.todo == [1] and job.given_up == {0: "too_long"}

    asyncio.run(scenario())


# -- the files -------------------------------------------------------------------------------

def test_playlist_files_follow_the_songs(tmp_config):
    store = Store(tmp_config.paths.db_path)
    tracks = _tracks(3)
    tracks[2]["playable"] = False
    _have(store, tmp_config, tracks, 1)
    s = playlists.summary(store, tracks)
    assert s["have"] == [1] and s["todo"] == [0] and s["unplayable"] == [2]
    path, listed, missing = playlists.save(store, tmp_config.paths.library_dir, "spotify:playlist:p", "Road: Trip",
                                           tracks)
    assert path.name == "Road- Trip.m3u8" or path.name.startswith("Road")
    text = path.read_bytes().decode("utf-8")
    assert text.startswith("#EXTM3U\r\n#PLAYLIST:Road: Trip\r\n")
    assert "#EXTINF:200,A - Song 1\r\n../Artists/A/Album/01 Song 1.m4a\r\n" in text
    assert (listed, missing) == (1, 2)
    # the song moves: the file is written again with its new path
    row = store.find_archived("A", "Song 1", 200_000, "spotify:track:1")
    new = tmp_config.paths.library_dir / "Artists" / "A" / "Other" / "Song 1.m4a"
    new.parent.mkdir(parents=True)
    (tmp_config.paths.library_dir / "Artists" / "A" / "Album" / "01 Song 1.m4a").rename(new)
    store.conn.execute("UPDATE tracks SET file_path=? WHERE id=?", (str(new), row["id"]))
    store.conn.commit()
    assert playlists.rewrite_all(store, tmp_config.paths.library_dir) == 1
    assert "../Artists/A/Other/Song 1.m4a" in path.read_text(encoding="utf-8")


def test_a_song_that_fails_twice_is_left_for_later(tmp_config):
    store = Store(tmp_config.paths.db_path)
    rec = FakeRecorder(tmp_config, store)

    async def scenario():
        job = rec.job = PlaylistJob(rec, "spotify:playlist:p", "Car", _tracks(2))
        await job.start()
        await job.on_track("spotify:track:0", archived=False)
        await job.on_result("spotify:track:0", kept=False, reasons=["paused"])
        await job.on_track("spotify:track:1", archived=False)
        await job.on_result("spotify:track:1", kept=True, reasons=[])
        assert job.todo == [0] and not job.done
        await job.on_track("spotify:track:0", archived=False)
        await job.on_result("spotify:track:0", kept=False, reasons=["buffering"])
        assert job.done and job.failed == {0: ["buffering"]}

    asyncio.run(scenario())
