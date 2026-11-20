# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Album completeness: which Spotify listings are one album, how many of an album's songs you have, and which albums
are on the Wanted list. The albums are ones from the library these features were built on."""
import asyncio
import json

import pytest

from mynaphone import albums as A, playlists
from mynaphone.config import Config
from mynaphone.library import safe
from mynaphone.playlist_job import PlaylistJob
from mynaphone.store import Store


def _song(store, cfg, uri, title, album_uri, album, total, track=0, kind="album", artists=("Anirudh Ravichander",),
          artist="", duration=200_000, release="2023-10-19", isrc=""):
    f = cfg.paths.library_dir / "Soundtracks" / safe(album) / f"{track:02d} {safe(title)}.m4a"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"m4a")
    meta = {"album_uri": album_uri, "played_album": album,
            "extra": {"album_info": {"total_tracks": total, "album_type": kind, "artists": list(artists),
                                     "release_date": release},
                      "track_metadata": {"album_track_number": str(track), "album_disc_number": "1"}}}
    return store.add_track(artist=artist or artists[0], title=title, album=album, duration_ms=duration, source_uri=uri,
                           state="library", file_path=str(f), meta_json=meta,
                           identity_json=json.dumps({"isrc": isrc}) if isrc else None)


def _uri(album_uri, i):
    """The Spotify id of an album's song in these tests."""
    return album_uri.replace("spotify:album:", "spotify:track:") + f"-{i}"


def _tracks(album_uri, names, artists=("Anirudh Ravichander",), duration=200_000, unplayable=()):
    return [{"index": i, "uri": _uri(album_uri, i), "uid": f"u{i}", "name": n, "artists": list(artists),
             "album": {"name": "", "uri": album_uri}, "duration_ms": duration, "playable": i not in unplayable,
             "track_number": i + 1, "disc_number": 1} for i, n in enumerate(names)]


# -- one album, several listings ---------------------------------------------------------------

@pytest.mark.parametrize("name, key", [
    ("Master Of Puppets (Deluxe Box Set / Remastered)", "master of puppets"),
    ("Master Of Puppets (Remastered)", "master of puppets"),
    ("Casino Royale (Original Motion Picture Soundtrack) (Deluxe Version)", "casino royale"),
    ("Guild Wars 2: Heart of Thorns (Original Game Soundtrack)", "guild wars 2 heart of thorns"),
    ("The Wall: The High Resolution Remasters", "the wall"),
    ("Garam Masala: Original Motion Picture Soundtrack", "garam masala"),
    ("Divinity: Original Sin 2 OST", "divinity original sin 2"),
    ("Toxicity (limited edition with bonus DVD)", "toxicity"),
    ("Abbey Road (Remastered 2009)", "abbey road"),
    ("Thriller (25th Anniversary Edition)", "thriller"),
    # words that make another album stay
    ("Master (Telugu) [Original Motion Picture Soundtrack]", "master telugu"),
    ("Master: Original Background Score", "master original background score"),
    ("Dilwale Dulhania Le Jayenge (dialogues version)", "dilwale dulhania le jayenge dialogues version"),
    ("Play (The Remixes)", "play the remixes"),
    ("Kuch Kuch Hota Hai - Und Ganz Plötzlich Ist Es Liebe...", "kuch kuch hota hai und ganz plötzlich ist es liebe"),
    ("Soundtrack", "soundtrack"),
])
def test_edition_words_leave_the_albums_name(name, key):
    assert A.edition_key(name) == key


def test_a_box_set_counts_against_the_album_and_its_extra_songs_are_never_missing(tmp_config):
    st = Store(tmp_config.paths.db_path)
    _song(st, tmp_config, "spotify:track:mop", "Master of Puppets", "spotify:album:std",
          "Master Of Puppets (Remastered)", 8, 2, artists=("Metallica",))
    for i, title in ((4, "Welcome Home (Sanitarium) - Remastered"), (7, "Orion - Remastered")):
        _song(st, tmp_config, f"spotify:track:box{i}", title, "spotify:album:box",
              "Master Of Puppets (Deluxe Box Set / Remastered)", 137, i, kind="compilation", artists=("Metallica",),
              isrc=f"USBK1860000{i}")
    [album] = A.build(st)
    assert album.uri == "spotify:album:std" and album.total == 8
    assert (album.have, album.bonus, album.yours) == (1, 2, 3)
    assert album.listings == ["spotify:album:std", "spotify:album:box"]
    assert A.on_wanted_list(album, 3) and not A.on_wanted_list(album, 4)
    # once Spotify's list of the album is in, with the ISRCs of the songs the library doesn't know by their ids, the box
    # set's copies fill their places on it
    tracks = _tracks("spotify:album:std", [
        "Battery - Remastered", "Master Of Puppets - Remastered", "The Thing That Should Not Be - Remastered",
        "Welcome Home (Sanitarium) - Remastered", "Disposable Heroes - Remastered", "Leper Messiah - Remastered",
        "Orion - Remastered", "Damage, Inc. - Remastered"], artists=("Metallica",))
    tracks[1]["uri"] = "spotify:track:mop"
    for i in (3, 6):
        tracks[i]["isrc"] = f"USBK1860000{i + 1}"
        tracks[i]["uri"] = f"spotify:track:std{i}"
    st.save_album_tracks("spotify:album:std", tracks)
    [album] = A.build(st)
    assert (album.have, album.bonus, album.missing) == (3, 0, 5)
    assert [h is not None for h in album.held] == [False, True, False, True, False, False, True, False]


def test_the_same_soundtrack_from_two_labels_is_one_album(tmp_config):
    """Guild Wars 2: Heart of Thorns is on Spotify twice, under Various Artists and under its composers; 25 songs came
    from one listing and the other 2 from the second."""
    st = Store(tmp_config.paths.db_path)
    for i in range(1, 28):
        twin = i in (14, 19)
        _song(st, tmp_config, f"spotify:track:hot{i}", f"Song {i}",
              "spotify:album:materia" if twin else "spotify:album:arena",
              "Guild Wars 2: Heart of Thorns (Original Game Soundtrack)" if twin
              else "Guild Wars 2: Heart of Thorns (Original Soundtrack)", 27, i, kind="compilation",
              artists=("Maclaine Diemer", "Lena Raine") if twin else ("Various Artists",), artist="Maclaine Diemer",
              release="2015-12-15")
    [album] = A.build(st)
    assert album.uri == "spotify:album:arena" and (album.have, album.bonus) == (25, 2)
    st.save_album_tracks("spotify:album:arena", _tracks("spotify:album:arena", [f"Song {i}" for i in range(1, 28)],
                                                        artists=("Maclaine Diemer",)))
    [album] = A.build(st)
    assert album.whole and album.bonus == 0 and not A.on_wanted_list(album, 3)


def test_a_dubbed_album_and_a_score_keep_their_own_counts(tmp_config):
    st = Store(tmp_config.paths.db_path)
    _song(st, tmp_config, "spotify:track:vr", "Vaathi Raid", "spotify:album:ta", "Master (Original Motion Picture "
          "Soundtrack)", 8, 8)
    _song(st, tmp_config, "spotify:track:mc", "Master Coming", "spotify:album:te",
          "Master (Telugu) [Original Motion Picture Soundtrack]", 8, 1)
    _song(st, tmp_config, "spotify:track:bgm", "Master the Blaster", "spotify:album:bgm",
          "Master (Original Background Score)", 16, 2)
    _song(st, tmp_config, "spotify:track:vc", "Vaathi Coming", "spotify:album:single", 'Vaathi Coming (From "Master")',
          1, 1, kind="single")
    found = A.build(st)
    assert sorted(a.uri for a in found) == ["spotify:album:bgm", "spotify:album:ta", "spotify:album:te"]
    assert all(a.have == 1 and a.bonus == 0 for a in found)


def test_an_albums_songs_from_spotify_count_its_singles_and_what_spotify_cant_play(tmp_config):
    """Leo: 5 songs from the album, Ratata from its single (Spotify's media session gives the first singer only), and
    a song Spotify can't play in your country."""
    st = Store(tmp_config.paths.db_path)
    names = ["Naa Ready", "Badass", "Ordinary Person", "Villain Yaaru", "I'm Scared", "Bloody Sweet", "Ratata"]
    for i in range(5):
        _song(st, tmp_config, _uri("spotify:album:leo", i), names[i], "spotify:album:leo", "Leo", 7, i + 1)
    _song(st, tmp_config, "spotify:track:ratata-single", "Ratata", "spotify:album:rs", 'Ratata (From "Leo")', 1, 1,
          kind="single", artist="Anirudh Ravichander")
    [album] = A.build(st)
    assert (album.have, album.total, album.unplayable) == (5, 7, 0)
    st.save_album_tracks("spotify:album:leo", _tracks("spotify:album:leo", names, unplayable={5},
                                                      artists=("Anirudh Ravichander", "Arivu", "Asal Kolaar")))
    [album] = A.build(st)
    assert (album.have, album.unplayable, album.to_record, album.yours) == (6, 1, 0, 6)
    assert album.held[6]["title"] == "Ratata"
    # nothing Spotify can play is left, so it goes to the end of the list
    _song(st, tmp_config, "spotify:track:other", "Song", "spotify:album:other", "Jailer 2", 12, 1, release="2026-06-01")
    for i in range(2, 4):
        _song(st, tmp_config, f"spotify:track:other{i}", f"Song {i}", "spotify:album:other", "Jailer 2", 12, i)
    assert [a.name for a in A.wanted_list(A.build(st), 3)] == ["Jailer 2", "Leo"]


def test_the_wanted_list(tmp_config):
    st = Store(tmp_config.paths.db_path)

    def album(uri, name, total, have):
        for i in range(have):
            _song(st, tmp_config, _uri(uri, i), f"{name} {i}", uri, name, total, i + 1)

    album("spotify:album:div", "Divinity: Original Sin 2 (Original Soundtrack)", 42, 41)
    album("spotify:album:kal", "Kalari", 4, 3)
    album("spotify:album:bg3", "Baldur's Gate 3", 43, 38)
    album("spotify:album:petta", "Petta", 11, 2)
    album("spotify:album:whole", "Kalyug", 3, 3)
    found = A.build(st)
    # nearest to whole first: the fewest songs to record, then the biggest share
    assert [a.name for a in A.wanted_list(found, 3)] == ["Divinity: Original Sin 2 (Original Soundtrack)", "Kalari",
                                                         "Baldur's Gate 3"]
    st.set_wanted("spotify:album:petta", True)          # Want this album
    st.set_wanted("spotify:album:kal", False)           # Take it off the Wanted list
    found = A.build(st)
    assert [a.name for a in A.wanted_list(found, 3)] == ["Divinity: Original Sin 2 (Original Soundtrack)",
                                                         "Baldur's Gate 3", "Petta"]
    assert [a.name for a in A.wanted_list(found, 0)] == ["Petta"]     # only the albums you add
    st.set_wanted("spotify:album:kal", True)            # the newest decision wins
    assert "Kalari" in [a.name for a in A.wanted_list(A.build(st), 3)]
    st.set_wanted("spotify:album:whole", True)          # a whole album never is
    assert "Kalyug" not in [a.name for a in A.wanted_list(A.build(st), 3)]
    divinity = A.find(found, "spotify:album:div")
    assert A.minutes_to_record(divinity, 225_000) == 4
    st.save_album_tracks("spotify:album:div", _tracks("spotify:album:div", [f"Divinity: Original Sin 2 (Original "
                                                                            f"Soundtrack) {i}" for i in range(42)],
                                                      duration=200_000))
    divinity = A.find(A.build(st), "spotify:album:div")
    assert divinity.have == 41 and A.minutes_to_record(divinity, 225_000) == 3


def test_matching_takes_the_first_artist_the_media_session_gave(tmp_config):
    st = Store(tmp_config.paths.db_path)
    _song(st, tmp_config, "spotify:track:hukum-single", "Hukum - Thalaivar Alappara", "spotify:album:hs", "Hukum", 1, 1,
          kind="single")
    track = {"uri": "spotify:track:hukum-album", "name": "Hukum - Thalaivar Alappara", "duration_ms": 201_000,
             "artists": ["Anirudh Ravichander", "Super Subu"]}
    assert playlists.match(st, track)["title"] == "Hukum - Thalaivar Alappara"
    assert playlists.match(st, {**track, "artists": ["Super Subu", "Anirudh Ravichander"]}) is None


def test_the_job_drops_a_song_the_recorder_already_has_and_writes_no_file_for_an_album(tmp_config):
    from tests.test_playlists import FakeRecorder, _tracks as playlist_tracks
    st = Store(tmp_config.paths.db_path)
    rec = FakeRecorder(tmp_config, st)
    tracks = playlist_tracks(3)

    async def scenario():
        job = rec.job = PlaylistJob(rec, "spotify:album:a", "Album", tracks, keep_file=False)
        await job.start()
        assert job.todo == [0, 1, 2]
        # song 1 is in the library by its ISRC from another release, which the job's list didn't know
        assert await job.on_track("spotify:track:1", archived=True) is True
        assert job.todo == [0, 2] and job.have == 1
        await asyncio.sleep(0)
        assert rec.bridge.sent[-1] == ("play", "spotify:track:2")
        await job.on_track("spotify:track:2", archived=False)
        await job.on_result("spotify:track:2", kept=True, reasons=[])
        await job.on_track("spotify:track:0", archived=False)
        await job.on_result("spotify:track:0", kept=True, reasons=[])
        assert job.done

    asyncio.run(scenario())
    assert not (tmp_config.paths.library_dir / "Playlists").exists()


def test_an_album_spotify_lists_no_songs_for_isnt_started(tmp_config):
    from mynaphone.bridge import BridgeError
    from mynaphone.daemon import Recorder

    class Bridge:
        async def request(self, do, timeout=30.0, **params):
            return {"tracks": []}

    rec = Recorder.__new__(Recorder)
    rec.store, rec.cfg, rec.bridge, rec.job = Store(tmp_config.paths.db_path), tmp_config, Bridge(), None
    with pytest.raises(BridgeError, match="didn't list any songs"):
        asyncio.run(rec.start_job("spotify:album:empty", "Empty", keep_file=False))
    assert rec.job is None


def test_the_wanted_list_setting_is_saved(tmp_config):
    assert tmp_config.albums.wanted_min_songs == 3
    tmp_config.albums.wanted_min_songs = 0
    tmp_config.save()
    assert Config.load(tmp_config.source_file).albums.wanted_min_songs == 0
