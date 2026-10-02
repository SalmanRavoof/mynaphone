# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from mynaphone import tools
from mynaphone.identify import Identity, choose, from_tags, looks_like_soundtrack
from mynaphone.library import classify, file_take, place, safe
from mynaphone.metadata import apply_manual, missing_fields

ACOUSTID = {
    "status": "ok",
    "results": [{
        "id": "acoustid-1", "score": 0.97,
        "recordings": [{
            "id": "rec-1", "title": "Neethanae",
            "artists": [{"id": "ar-1", "name": "A. R. Rahman", "joinphrase": " & "},
                        {"id": "ar-2", "name": "Shreya Ghoshal"}],
            "releasegroups": [{
                "id": "rg-1", "title": "Mersal (Original Motion Picture Soundtrack)", "type": "Album",
                "secondarytypes": ["Soundtrack"], "artists": [{"id": "ar-1", "name": "A. R. Rahman"}],
                "releases": [{
                    "id": "rel-1", "title": "Mersal (Original Motion Picture Soundtrack)",
                    "date": {"year": 2017, "month": 8, "day": 20}, "medium_count": 1,
                    "mediums": [{"position": 1, "track_count": 4,
                                 "tracks": [{"id": "t1", "position": 3, "title": "Neethanae"}]}],
                }],
            }],
        }],
    }],
}


def test_choose_reads_release_track_and_types():
    ident = choose(ACOUSTID, hint_album="Mersal (Original Motion Picture Soundtrack)", hint_title="Neethanae")
    assert ident.source == "acoustid" and ident.score == pytest.approx(0.97)
    assert ident.artist == "A. R. Rahman & Shreya Ghoshal"
    assert ident.album_artist == "A. R. Rahman"
    assert ident.year == 2017 and ident.date == "2017-08-20"
    assert ident.track_number == 3 and ident.track_total == 4 and ident.disc_number == 1
    assert ident.is_soundtrack and ident.release_type == "album"
    assert ident.mb_recording_id == "rec-1" and ident.mb_release_id == "rel-1"


def test_choose_rejects_low_scores():
    bad = json.loads(json.dumps(ACOUSTID))
    bad["results"][0]["score"] = 0.2
    assert choose(bad) is None


@pytest.mark.parametrize("album,title,expected", [
    ("Bigil (Original Motion Picture Soundtrack)", "x", True),
    ("Pathu Thala", 'Nee Singam Dhan (From "Pathu Thala")', True),
    ("Vettaiyan OST", "x", True),
    ("Random Album", "Random Song", False),
])
def test_soundtrack_heuristic(album, title, expected):
    assert looks_like_soundtrack(album, title) is expected


def test_from_tags_uses_spotify_extras_and_composer_fallback():
    meta = {
        "title": "Unakaga", "artist": "A.R. Rahman", "album": "Bigil (Original Motion Picture Soundtrack)",
        "album_artist": "A.R. Rahman", "track_number": 2, "source_uri": "spotify:track:1",
        "extra": {"album_info": {"release_date": "2019-09-19", "total_tracks": 5,
                                 "album_type": "album", "label": "Sony"},
                  "track_info": {"isrc": "inx", "explicit": False, "popularity": 55}},
    }
    i = from_tags(meta)
    assert i.source == "spotify" and i.year == 2019 and i.track_total == 5
    assert i.is_soundtrack and i.composers == ["A.R. Rahman"]
    assert i.isrc == "INX" and i.explicit is False and i.popularity == 55 and i.label == "Sony"


def test_view_counts_never_become_albums():
    from mynaphone.identify import looks_like_count
    assert looks_like_count("54M views") and looks_like_count("1.2M likes") and looks_like_count("71M views")
    assert not looks_like_count("Dhoom (Original Motion Picture Soundtrack)") and not looks_like_count("")
    i = from_tags({"title": "Genda Phool", "artist": "Shraddha Pandit", "album": "71M views", "album_artist": "YRF"})
    assert i.album == "" and i.release_type == "single"
    assert classify(i) == "single"


def test_classify_and_place():
    i = Identity(title="Song", artist="Singer", album="Film (Original Motion Picture Soundtrack)",
                 album_artist="Composer", year=2020, track_number=4, secondary_types=["Soundtrack"])
    assert classify(i) == "soundtrack"
    p = place(i)
    assert p.rel_dir == Path("Soundtracks") / "Film (Original Motion Picture Soundtrack) (2020)"
    assert p.filename == "04 Song"

    s = Identity(title="Single Song", artist="Artist", album="Single Song", release_type="single")
    assert classify(s) == "single"
    assert place(s).rel_dir == Path("Artists") / "Artist" / "Singles"

    a = Identity(title="Track", artist="Artist", album="Album", album_artist="Artist", year=1999, track_number=2,
                 disc_number=2, disc_total=2, release_type="album")
    assert classify(a) == "album"
    assert place(a).filename == "2-02 Track"

    va = Identity(title="T", artist="X", album="Hits", album_artist="Various Artists", track_number=1)
    assert classify(va) == "compilation"


def test_safe_filenames():
    assert safe('A: "B" / C?') == "A B C"          # reserved characters dropped, runs of spaces collapsed
    assert safe("   ") == "Unknown"
    assert len(safe("x" * 200)) == 90


def test_missing_fields_and_manual_overrides():
    i = Identity(title="T", artist="A", album="B", album_artist="A", year=2001, track_number=1, track_total=10,
                 disc_number=1, composers=["C"], lyricists=["L"], genres=["pop"], isrc="x", label="lab",
                 mb_recording_id="m")
    assert missing_fields(i, has_cover=True, lyrics_state="synced") == []
    assert set(missing_fields(i, has_cover=False, lyrics_state="plain")) == {"cover", "synced_lyrics"}
    assert "lyrics" in missing_fields(i, True, "none")
    apply_manual(i, {"composers": "X; Y", "year": "2005", "track_number": "7", "kind": "soundtrack"})
    assert i.composers == ["X", "Y"] and i.year == 2005 and i.track_number == 7 and i.is_soundtrack
    apply_manual(i, {"kind": "album"})
    assert not i.is_soundtrack


@pytest.mark.skipif(tools.ffmpeg() is None, reason="ffmpeg not installed")
def test_file_take_encodes_tags_and_places(tmp_path):
    rate = 48000
    t = np.arange(rate * 3) / rate
    x = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    src = tmp_path / "in.flac"
    sf.write(str(src), np.stack([x, x], axis=1), rate, subtype="PCM_16")
    ident = Identity(source="acoustid", title="Song", artist="Singer",
                     album="Film (Original Motion Picture Soundtrack)",
                     album_artist="Composer", year=2020, date="2020-01-02", track_number=1, track_total=6,
                     secondary_types=["Soundtrack"], composers=["Composer"], isrc="INABC", label="Lbl",
                     mb_recording_id="rec", genres=["film"])
    lyrics = "[00:01.00]hello\n[00:02.00]world"
    dst = file_take(src, tmp_path / "lib", ident, "aac", 128, lyrics,
                    {"quality_tier": "high", "source_app": "Spotify.exe"},
                    cover=(b"\xff\xd8\xff" + b"\x00" * 100, "image/jpeg"))
    assert dst == tmp_path / "lib" / "Soundtracks" / "Film (Original Motion Picture Soundtrack) (2020)" / "01 Song.m4a"
    assert dst.with_suffix(".lrc").read_text(encoding="utf-8") == lyrics
    from mutagen.mp4 import MP4
    m = MP4(str(dst))
    assert m["\xa9nam"] == ["Song"] and m["\xa9wrt"] == ["Composer"] and m["trkn"] == [(1, 6)]
    assert m["\xa9gen"] == ["Film"] and m["\xa9lyr"] == [lyrics] and "covr" in m
    assert bytes(m["----:com.apple.iTunes:ISRC"][0]) == b"INABC"
    assert 2.8 < m.info.length < 3.2


@pytest.mark.skipif(tools.ffmpeg() is None, reason="ffmpeg not installed")
@pytest.mark.parametrize("fmt,ext", [("mp3", ".mp3"), ("opus", ".opus")])
def test_file_take_other_formats(tmp_path, fmt, ext):
    from mynaphone.library import read_extras, write_lyrics
    rate = 48000
    t = np.arange(rate * 2) / rate
    x = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    src = tmp_path / "in.flac"
    sf.write(str(src), np.stack([x, x], axis=1), rate, subtype="PCM_16")
    ident = Identity(source="spotify", title="Song", artist="Singer", album="Album", album_artist="Singer",
                     year=2021, track_number=2, track_total=9, release_type="album", composers=["C"], isrc="INX")
    lyrics = "[00:01.00]hello\n[00:02.50]world"
    dst = file_take(src, tmp_path / "lib", ident, fmt, 128, lyrics, {"quality_tier": "high"},
                    cover=(b"\x89PNG" + b"\x00" * 64, "image/png"))
    assert dst.suffix == ext and dst.exists()
    cover, text = read_extras(dst)
    assert cover is not None and cover[1] == "image/png" and text == lyrics
    if fmt == "mp3":
        from mutagen.id3 import ID3
        f = ID3(str(dst))
        assert f["TIT2"].text == ["Song"] and f["TRCK"].text == ["2/9"] and f["TSRC"].text == ["INX"]
        assert f.getall("SYLT")[0].text[1] == ("world", 2500)
    else:
        from mutagen.oggopus import OggOpus
        f = OggOpus(str(dst))
        assert f["TITLE"] == ["Song"] and f["TRACKNUMBER"] == ["2"] and f["ISRC"] == ["INX"]
    write_lyrics(dst, "plain words")
    assert read_extras(dst)[1] == "plain words"


def test_lossless_tier_keeps_flac(tmp_path):
    rate = 44100
    x = np.zeros((rate, 2), np.float32)
    src = tmp_path / "in.flac"
    sf.write(str(src), x, rate, subtype="PCM_24")
    ident = Identity(title="S", artist="A", album="S", release_type="single")
    dst = file_take(src, tmp_path / "lib", ident, "aac", 256, "", {"quality_tier": "hifi"}, cover=None)
    assert dst.suffix == ".flac"


YRF_DESC = """Ladies, Beware! Listen to the title track 'Bachna Ae Haseeno'!
► Subscribe Now: https://example.invalid

🎧 Song Credits:
Song: Bachna Ae Haseeno
Music: Vishal and Shekhar
Lyrics: Anvita Dutt Guptan
Singers: Kishore Kumar, Sumeet Kumar, Vishal Dadlani

🎬 Movie Credits:
Movie: Bachna Ae Haseeno
Starring: Ranbir Kapoor, Bipasha Basu
Music: Vishal and Shekhar
Release Date: 15 August 2008
"""
TSERIES_DESC = ("Song - Genda Phool\nFilm - Delhi-6\nSinger - Rekha Bharadwaj, Shraddha Pandit, Sujata Majumdar\n"
                "Lyricist - Prasoon Joshi\nMusic Director - A R Rahman, Rajat Dholakia\n"
                "Artist - Abhishek Bachchan, Sonam Kapoor\nMusic On - T-Series")


def test_video_credits_from_label_descriptions():
    from mynaphone.identify import parse_video_credits
    c = parse_video_credits(YRF_DESC)
    assert c["title"] == "Bachna Ae Haseeno" and c["film"] == "Bachna Ae Haseeno" and c["year"] == 2008
    assert c["singers"] == ["Kishore Kumar", "Sumeet Kumar", "Vishal Dadlani"]
    assert c["composers"] == ["Vishal and Shekhar"] and c["lyricists"] == ["Anvita Dutt Guptan"]
    c = parse_video_credits(TSERIES_DESC)
    assert c["film"] == "Delhi-6" and c["label"] == "T-Series"
    assert c["singers"] == ["Rekha Bharadwaj", "Shraddha Pandit", "Sujata Majumdar"]
    assert c["composers"] == ["A R Rahman", "Rajat Dholakia"] and "actors" not in c
    # the same text with its line breaks collapsed, as a page scrape can deliver it
    assert parse_video_credits(TSERIES_DESC.replace("\n", " "))["film"] == "Delhi-6"
    assert parse_video_credits("Thanks for watching! Subscribe for more.") == {}


def test_clean_video_title():
    from mynaphone.identify import clean_video_title
    assert clean_video_title("A R Rahman : Genda Phool Full Song  | Delhi 6 | Abhishek Bachchan") == "Genda Phool"
    assert clean_video_title("Khuda Jaane (Official Video) | Bachna Ae Haseeno - YouTube") == "Khuda Jaane"
    assert clean_video_title("Dilbara - Lyrical Video") == "Dilbara"


def test_unidentified_songs_go_to_unsorted():
    i = Identity(title="Some Title", artist="", album="")
    assert classify(i) == "unsorted" and place(i).rel_dir == Path("Unsorted") and place(i).filename == "Some Title"
    from mynaphone.metadata import _place_with_kind
    assert _place_with_kind(i, "single").rel_dir == Path("Unsorted")


def test_singers_shown_as_artist_when_recording_credits_the_composer():
    from mynaphone.identify import prefer_vocals
    i = Identity(title="T", artist="A. R. Rahman", artists=["A. R. Rahman"], album_artist="A. R. Rahman",
                 composers=["A. R. Rahman"], vocals=["Sonu Nigam", "Shreya Ghoshal"])
    prefer_vocals(i)
    assert (i.artist == "Sonu Nigam, Shreya Ghoshal" and i.album_artist == "A. R. Rahman"
            and i.composers == ["A. R. Rahman"])
    j = Identity(title="T", artist="Sonu Nigam", artists=["Sonu Nigam"], album_artist="A. R. Rahman",
                 vocals=["Sonu Nigam"])
    prefer_vocals(j)
    assert j.artist == "Sonu Nigam"


def test_catalogue_match_rejects_covers():
    from mynaphone.identify import _pick_catalogue_song
    cover = {"title": "Bachna Ae Haseeno", "artists": [{"name": "Arjun Tanwar"}],
             "album": {"name": "Retro Rock & Roll", "id": "c"}, "duration": "3:25"}
    real = {"title": "GENDA PHOOL", "artists": [{"name": "Rekha Bhardwaj"}],
            "album": {"name": "Delhi-6 (Original Motion Picture Soundtrack)", "id": "r"}, "duration": "2:50"}
    singers = ["Kishore Kumar", "Sumeet Kumar", "Vishal Dadlani"]
    assert _pick_catalogue_song([cover], "Bachna Ae Haseeno", "Bachna Ae Haseeno", 201, singers) is None
    assert _pick_catalogue_song([cover], "Bachna Ae Haseeno", "", 201, singers) is None
    assert _pick_catalogue_song([real], "Genda Phool", "Delhi-6", 160, ["Rekha Bharadwaj"])["album"]["id"] == "r"
    assert _pick_catalogue_song([real], "Genda Phool", "", 160, ["Rekha Bharadwaj"])["album"]["id"] == "r"


def test_split_names_keeps_duos_together():
    from mynaphone.identify import same_name, split_names
    assert split_names("Kishore Kumar, Sumeet Kumar & Vishal Dadlani") == [
        "Kishore Kumar", "Sumeet Kumar", "Vishal Dadlani"]
    assert split_names("Vishal and Shekhar") == ["Vishal and Shekhar"]
    assert split_names("Salim-Sulaiman") == ["Salim-Sulaiman"]
    assert split_names("Shreya Ghoshal and Sonu Nigam") == ["Shreya Ghoshal", "Sonu Nigam"]
    assert same_name("Rekha Bhardwaj", "Rekha Bharadwaj") and same_name("Shrradha Pandit", "Shraddha Pandit")
    assert not same_name("Sonu Nigam", "Shreya Ghoshal")
