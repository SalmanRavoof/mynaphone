# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Genres, instrumentals and Spotify's player counts. No network: every lookup is replaced."""
from types import SimpleNamespace

import pytest

from mynaphone import genres, identify, musicbrainz
from mynaphone.identify import Identity
from mynaphone.metadata import missing_fields

APPLE = [
    {"trackName": "Kyon Hawa", "artistName": "Lata Mangeshkar", "primaryGenreName": "Bollywood",
     "trackTimeMillis": 340_000},
    {"trackName": "Kyon Hawa (Instrumental)", "artistName": "Madan Mohan", "primaryGenreName": "Bollywood",
     "trackTimeMillis": 253_000},
    {"trackName": "Lamha Lamha", "artistName": "Pritam & Abhijeet", "primaryGenreName": "Bollywood",
     "trackTimeMillis": 324_600},
]


def cfg(lastfm_key=""):
    return SimpleNamespace(identify=SimpleNamespace(lastfm_api_key=lastfm_key, apple_country="US"))


def test_apple_pick_needs_the_title_and_the_artist_or_length():
    assert genres.pick_apple(APPLE, "Kyon Hawa (Instrumental)", "Madan Mohan", 253.2) is APPLE[1]
    # a " - From ..." tail and a second credited artist still match
    assert genres.pick_apple(APPLE, 'Lamha Lamha - From "Gangster"', "Pritam", 324.0) is APPLE[2]
    # same title by someone else, and a very different length: not this song
    assert genres.pick_apple(APPLE[:1], "Kyon Hawa", "Sonu Nigam", 200.0) is None
    assert genres.pick_apple(APPLE, "Some Other Song", "Madan Mohan", 253.0) is None


def test_lastfm_keeps_only_tags_that_are_genres(monkeypatch):
    answers = [
        {"error": 6, "message": "Track not found"},
        {"toptags": {"tag": [{"name": "seen live"}, {"name": "hindi"}, {"name": "Bollywood"}, {"name": "rock"}]}},
    ]
    monkeypatch.setattr(genres, "_get_json", lambda url, timeout=15.0: answers.pop(0))
    assert genres.lastfm_genre("Song", "Artist", "key") == "Bollywood"    # from the artist's tags


def test_lastfm_bad_key_gives_no_genre(monkeypatch):
    monkeypatch.setattr(genres, "_get_json", lambda url, timeout=15.0: {"error": 10, "message": "Invalid API key"})
    assert genres.lastfm_genre("Song", "Artist", "wrong") == ""


@pytest.mark.parametrize("apple, mb, lastfm, key, soundtrack, want", [
    ("Rock", ["progressive rock"], "", "", False, ["Rock", "progressive rock"]),    # Apple first, MB kept after
    ("", ["progressive rock"], "Pop", "k", False, ["progressive rock"]),            # then MusicBrainz
    ("", [], "Ghazal", "k", False, ["Ghazal"]),                                     # then Last.fm
    ("", [], "Ghazal", "", False, []),                                              # Last.fm only with a key
    ("", [], "", "k", True, ["Soundtrack"]),                                        # then the folder
    (OSError, [], "", "k", True, []),                                               # failed lookup: retry later
])
def test_genre_chain_order(monkeypatch, apple, mb, lastfm, key, soundtrack, want):
    def fake_apple(*a):
        if apple is OSError:
            raise OSError("offline")
        return apple

    monkeypatch.setattr(genres, "apple_genre", fake_apple)
    monkeypatch.setattr(genres, "lastfm_genre", lambda *a: lastfm)
    ident = Identity(title="Song", artist="Artist", genres=list(mb),
                     secondary_types=["Soundtrack"] if soundtrack else [])
    genres.resolve(ident, "Artist", 200.0, cfg(key))
    assert ident.genres == want


def test_instrumentals_need_no_lyrics_or_lyricist():
    assert identify.is_instrumental("Kyon Hawa (Instrumental)")
    assert identify.is_instrumental("Tere Liye", "Romancing The Legend: Veer-Zaara Instrumental")
    assert not identify.is_instrumental("Tujhe Dekha To", "Dilwale Dulhania Le Jayenge")
    ident = Identity(title="Kyon Hawa (Instrumental)", artist="Madan Mohan", album="A", album_artist="Madan Mohan")
    assert not {"lyrics", "synced_lyrics", "lyricists"} & set(missing_fields(ident, True, "instrumental"))
    assert {"lyrics", "synced_lyrics", "lyricists"} <= set(missing_fields(ident, True, "none"))


def test_spotify_player_counts_fill_track_and_disc_numbers():
    meta = {"title": "Kyon Hawa (Instrumental)", "artist": "Madan Mohan", "source_uri": "spotify:track:1",
            "extra": {"album_info": {"copyrights": [], "artists": []},   # what a refused web API request left
                      "track_metadata": {"album_track_number": "3", "album_track_count": "10",
                                         "album_disc_number": "1", "album_disc_count": "1"}}}
    ident = identify.from_tags(meta)
    assert (ident.track_number, ident.track_total, ident.disc_number, ident.disc_total) == (3, 10, 1, 1)
    assert ident.year == 0 and ident.label == ""                       # nothing invented from the empty reply


def test_musicbrainz_release_with_a_catalog_number_but_no_label(monkeypatch):
    monkeypatch.setattr(musicbrainz, "_get", lambda path, inc="": {
        "title": "Wish You Were Here 50", "label-info": [{"label": None, "catalog-number": "PFR50"}], "media": []})
    rel = musicbrainz.release("0aad2e45-96fb-4468-a535-bafb91224ee8")
    assert rel["label"] == "" and rel["catalog"] == "PFR50"
