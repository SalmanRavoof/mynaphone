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


def _plays(rec):
    return [uri for do, uri in rec.bridge.sent if do == "play"]


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
        # Spotify stopped after the playlist's last song, so song 3 gets its one more go
        await asyncio.sleep(0)
        assert _plays(rec).count("spotify:track:3") == 2 and job.tries == {3: 1}
        await job.on_track("spotify:track:3", archived=False)
        await job.on_result("spotify:track:3", kept=True, reasons=[])
        assert job.done and rec.job is None
        assert ("pause", None) in rec.bridge.sent and ("restore_shuffle", 1) in rec.bridge.sent
        assert [tracks[i]["name"] for i in job.saved] == ["Song 1", "Song 4", "Song 3"]

    asyncio.run(scenario())
    m3u = (tmp_config.paths.library_dir / "Playlists" / "Car.m3u8").read_text(encoding="utf-8")
    assert "../Artists/A/Album/00 Song 0.m4a" in m3u and "# not in your library yet: A - Song 1" in m3u


def test_the_last_song_isnt_played_again_while_its_take_is_saved(tmp_config):
    """Monsoon Season, November 20, 2026: song 12, which the library had, started while song 11's take was being
    saved, and the job played song 11 again for one more try. The first take was fine."""
    store = Store(tmp_config.paths.db_path)
    rec = FakeRecorder(tmp_config, store)
    tracks = _tracks(4)
    _have(store, tmp_config, tracks, 0, 2, 3)

    async def scenario():
        job = rec.job = PlaylistJob(rec, "spotify:album:a", "Album", tracks)
        await job.start()
        await job.on_track("spotify:track:1", archived=False)
        assert await job.on_track("spotify:track:2", archived=True) is True     # before song 1 is judged
        await asyncio.sleep(0)
        assert _plays(rec) == ["spotify:track:1"] and not job.done
        await job.on_result("spotify:track:1", kept=True, reasons=[])
        assert job.done and ("pause", None) in rec.bridge.sent
        assert rec.events[-1][1]["why"] == "done" and rec.events[-1][1]["saved"] == 1

    asyncio.run(scenario())


def test_the_last_song_gets_its_one_more_go_once_its_verdict_is_in(tmp_config):
    store = Store(tmp_config.paths.db_path)
    rec = FakeRecorder(tmp_config, store)
    tracks = _tracks(3)
    _have(store, tmp_config, tracks, 0, 2)

    async def scenario():
        job = rec.job = PlaylistJob(rec, "spotify:album:a", "Album", tracks)
        await job.start()
        await job.on_track("spotify:track:1", archived=False)
        await job.on_track("spotify:track:2", archived=True)
        await asyncio.sleep(0)
        assert _plays(rec) == ["spotify:track:1"]                    # it waits for song 1's verdict
        await job.on_result("spotify:track:1", kept=False, reasons=["buffering"])
        await asyncio.sleep(0)
        assert _plays(rec) == ["spotify:track:1", "spotify:track:1"]   # which says it needs one more go

    asyncio.run(scenario())


def test_autoplay_after_the_last_song_is_the_end(tmp_config, clock):
    store = Store(tmp_config.paths.db_path)
    rec = FakeRecorder(tmp_config, store)
    tracks = _tracks(2)
    _have(store, tmp_config, tracks, 0)

    async def scenario():
        job = rec.job = PlaylistJob(rec, "spotify:album:a", "Album", tracks)
        await job.start()
        await job.on_track("spotify:track:1", archived=False)
        clock.advance(200)
        await job.on_track("spotify:track:radio", archived=False)     # Spotify's autoplay, after the album's end
        assert ("pause", None) in rec.bridge.sent and not job.done
        await job.on_result("spotify:track:1", kept=True, reasons=[])
        assert job.done and rec.events[-1][1]["why"] == "done" and rec.events[-1][1]["saved"] == 1

    asyncio.run(scenario())


def test_a_song_you_queue_after_the_last_one_plays_on(tmp_config, clock):
    from mynaphone.bridge import SpotifyState
    store = Store(tmp_config.paths.db_path)
    rec = FakeRecorder(tmp_config, store)
    tracks = _tracks(2)
    _have(store, tmp_config, tracks, 0)

    async def scenario():
        job = rec.job = PlaylistJob(rec, "spotify:album:a", "Album", tracks)
        await job.start()
        await job.on_track("spotify:track:1", archived=False)
        clock.advance(200)
        rec.bridge.state = SpotifyState(uri="spotify:track:queued", provider="queue")
        await job.on_track("spotify:track:queued", archived=False)
        assert job.done and rec.events[-1][1]["why"] == "playback left the playlist"
        assert ("pause", None) not in rec.bridge.sent

    asyncio.run(scenario())


def test_picking_something_else_in_spotify_stops_the_job(tmp_config, clock):
    store = Store(tmp_config.paths.db_path)
    rec = FakeRecorder(tmp_config, store)

    async def scenario():
        job = rec.job = PlaylistJob(rec, "spotify:playlist:p", "Car", _tracks(3))
        await job.start()
        clock.advance(30)
        await job.on_track("spotify:track:elsewhere", archived=False)
        assert job.done and rec.events[-1][1]["stopped"] and rec.events[-1][1]["why"] == "playback left the playlist"
        assert ("pause", None) not in rec.bridge.sent                 # you're listening to something else now

    asyncio.run(scenario())


def test_the_song_spotify_was_paused_on_doesnt_end_the_job(tmp_config):
    """After a play command Spotify names the song it was paused on for a moment."""
    store = Store(tmp_config.paths.db_path)
    rec = FakeRecorder(tmp_config, store)

    async def scenario():
        job = rec.job = PlaylistJob(rec, "spotify:album:a", "Album", _tracks(2))
        await job.start()
        await job.on_track("spotify:track:before", archived=True)
        assert not job.done
        assert await job.on_track("spotify:track:0", archived=False) is False and 0 in job.recording

    asyncio.run(scenario())


def test_a_song_named_before_its_id_arrives_is_still_recognised(tmp_config):
    """The bridge can name a song a second after the media session does, so a take can start with no Spotify id."""
    store = Store(tmp_config.paths.db_path)
    rec = FakeRecorder(tmp_config, store)
    tracks = _tracks(3)
    _have(store, tmp_config, tracks, 1)

    async def scenario():
        job = rec.job = PlaylistJob(rec, "spotify:album:a", "Album", tracks)
        await job.start()
        assert await job.on_track("", archived=False, title="Song 0", duration_ms=200_400) is False
        assert job.recording == {0} and rec.events[-1][1]["current"] == "Song 0"
        await job.on_result("", kept=True, reasons=[], title="Song 0", duration_ms=200_400)
        assert job.saved == [0]
        assert await job.on_track("", archived=True, title="song 1", duration_ms=199_000) is True   # one you have
        await asyncio.sleep(0)
        assert _plays(rec)[-1] == "spotify:track:2"
        assert await job.on_track("", archived=False, title="Something Else", duration_ms=1000) is False
        assert not job.done                                          # no id and not one of its titles

    asyncio.run(scenario())


def test_a_song_the_recorder_wont_take_is_left_out(tmp_config):
    store = Store(tmp_config.paths.db_path)
    rec = FakeRecorder(tmp_config, store)

    async def scenario():
        job = rec.job = PlaylistJob(rec, "spotify:album:a", "Album", _tracks(2))
        await job.start()
        await job.on_skipped("spotify:track:0", "too_long")
        assert job.todo == [1] and job.given_up == {0: "too_long"}
        await asyncio.sleep(0)
        assert _plays(rec)[-1] == "spotify:track:1"                  # it doesn't play the long one out

    asyncio.run(scenario())


def test_a_song_the_library_gets_meanwhile_leaves_the_list(tmp_config):
    """A song still in the inbox, or recorded some other way while the job ran, counts as had."""
    store = Store(tmp_config.paths.db_path)
    rec = FakeRecorder(tmp_config, store)

    async def scenario():
        job = rec.job = PlaylistJob(rec, "spotify:album:a", "Album", _tracks(2))
        await job.start()
        await job.on_track("spotify:track:0", archived=True)
        await asyncio.sleep(0)
        assert _plays(rec)[-1] == "spotify:track:1" and job.have == 1
        await job.on_track("spotify:track:1", archived=False)
        await job.on_result("spotify:track:1", kept=True, reasons=[])
        assert job.done

    asyncio.run(scenario())


def test_a_song_listed_twice_is_recorded_once(tmp_config):
    store = Store(tmp_config.paths.db_path)
    rec = FakeRecorder(tmp_config, store)
    tracks = _tracks(3)
    tracks[2]["uri"] = tracks[0]["uri"]

    async def scenario():
        job = rec.job = PlaylistJob(rec, "spotify:playlist:p", "Car", tracks)
        await job.start()
        await job.on_track("spotify:track:0", archived=False)
        await job.on_result("spotify:track:0", kept=True, reasons=[])
        await job.on_track("spotify:track:1", archived=False)
        await job.on_result("spotify:track:1", kept=True, reasons=[])
        assert job.done and job.saved == [0, 1]

    asyncio.run(scenario())


def test_a_take_dropped_at_once_gets_another_go(tmp_config):
    store = Store(tmp_config.paths.db_path)
    rec = FakeRecorder(tmp_config, store)

    async def scenario():
        job = rec.job = PlaylistJob(rec, "spotify:album:a", "Album", _tracks(2))
        await job.start()
        await job.on_track("spotify:track:0", archived=False)
        job.on_dropped("spotify:track:0")                            # it played under 2 seconds, so no verdict
        await job.on_track("spotify:track:1", archived=False)
        await job.on_result("spotify:track:1", kept=True, reasons=[])
        await asyncio.sleep(0)
        assert _plays(rec)[-1] == "spotify:track:0" and not job.done

    asyncio.run(scenario())


def test_starting_says_why_spotify_wouldnt_play(tmp_config):
    """It used to answer the window with "'NoneType' object has no attribute 'progress'"."""
    from mynaphone.daemon import Recorder

    class Bridge:
        async def request(self, do, timeout=30.0, **params):
            if do == "tracks":
                return {"tracks": _tracks(2), "name": "Monsoon Season"}
            if do == "play":
                raise BridgeError("Spotify is playing on another device")
            return {}

    async def scenario():
        rec = Recorder(tmp_config, asyncio.get_running_loop())
        rec.bridge = Bridge()
        try:
            got = await rec.start_job("spotify:album:a", "")
        finally:
            rec._writer.shutdown(wait=True)
        assert got["done"] and got["name"] == "Monsoon Season"
        assert rec.job is None
        assert rec.store.conn.execute("SELECT name FROM playlists").fetchone()[0] == "Monsoon Season"

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

def test_a_renamed_playlist_leaves_no_old_file(tmp_config):
    store = Store(tmp_config.paths.db_path)
    tracks = _tracks(2)
    old, _, _ = playlists.save(store, tmp_config.paths.library_dir, "spotify:album:a", "Playlist 0AVJyPXZ", tracks)
    new, _, _ = playlists.save(store, tmp_config.paths.library_dir, "spotify:album:a", "Monsoon Season", tracks)
    assert new.name == "Monsoon Season.m3u8" and new.exists() and not old.exists()


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
