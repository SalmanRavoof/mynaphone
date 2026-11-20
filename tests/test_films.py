# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""One folder, one album artist and one album name per film: film keys, the folds planned and done on a temporary
library, the album artist and album name a film's songs share, its singles' track numbers, filing and editing."""
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from mutagen.flac import FLAC

import mynaphone.library as lib
import mynaphone.metadata as md
import mynaphone.musicbrainz as mb
import mynaphone.postprocess as P
from mynaphone import films
from mynaphone.identify import Identity
from mynaphone.postprocess import PostProcessor
from mynaphone.store import Store


def test_film_of():
    assert films.film_of("Ratata (From “Leo”)").key == films.film_of("Leo").key
    assert films.film_of("Ratata (From “Leo”)").single and not films.film_of("Leo").single
    assert films.film_of('Hukum Reloaded - Tamil (From "Jailer 2")').key == \
        films.film_of("Jailer 2 (Original Motion Picture Soundtrack)").key
    assert films.film_of("Aavesham (Original Motion Picture Soundtrack)").key == films.film_of("Aavesham").key
    assert films.film_of("Vettaiyan (telugu)").key != films.film_of("Vettaiyan").key        # a dubbed album
    assert films.film_of("Master Original Background Score").key != \
        films.film_of("Master Original Motion Picture Soundtrack").key                    # the score stays apart
    assert films.film_of("The Greatest Of All Time Ost (Original Motion Picture Soundtrack)").name == \
        "The Greatest Of All Time"
    assert films.film_of("Kabhi Khushi Kabhie Gham").name == "Kabhi Khushi Kabhie Gham"


def _library(tmp_path):
    root = tmp_path / "library"
    store = Store(tmp_path / "db.sqlite")
    ids = {}

    def song(folder, filename, album, title, lyrics=False):
        f = root / "Soundtracks" / folder / filename
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"m4a")
        if lyrics:
            f.with_suffix(".lrc").write_text("[00:01.00] la", encoding="utf-8")
        ids[filename] = store.add_track(artist="A", title=title, album=album, duration_ms=1, file_path=str(f),
                                        state="library", identity_json=json.dumps({"album": album, "title": title}))
        return f

    song("Leo (2023)", "01 Bloody Sweet.m4a", "Leo", "Bloody Sweet")
    song("Ratata (From “Leo”) (2023)", "01 Ratata.m4a", "Ratata (From “Leo”)", "Ratata", lyrics=True)
    song("Vettaiyan (2024)", "03 Hunter Vantaar.m4a", "Vettaiyan", "Hunter Vantaar")
    song("Vettaiyan (telugu) (2024)", "02 Clean Shot.m4a", "Vettaiyan (telugu)", "Clean Shot")
    song("Master Original Background Score (2021)", "01 Theme.m4a", "Master Original Background Score", "Theme")
    song("Master Original Motion Picture Soundtrack (2020)", "01 Vaathi.m4a",
         "Master Original Motion Picture Soundtrack", "Vaathi")
    song("Aashiq Banaya Aapne (2005)", "03 Aap Ki Kashish.m4a", "Aashiq Banaya Aapne", "Aap Ki Kashish")
    song("Aashiq Banaya Aapne (2008)", "01 Aashiq Banaya Aapne.m4a", "Aashiq Banaya Aapne", "Aashiq Banaya Aapne")
    song("Alaakaa Loova (From OM Chapter 1) (2026)", "01 Alaakaa Loova.m4a", 'Alaakaa Loova (From "OM Chapter 1")',
         "Alaakaa Loova")
    song("The Wild Theme (From OM Chapter 1) (2026)", "01 The Wild Theme.m4a", 'The Wild Theme (From "OM Chapter 1")',
         "The Wild Theme")
    song("Devdas (1955)", "01 Mitwa.m4a", "Devdas", "Mitwa")
    song("Devdas (2002)", "01 Silsila.m4a", "Devdas", "Silsila")                         # a remake, decades on
    return root, store, ids


def test_folding_puts_each_films_songs_in_one_folder(tmp_path):
    root, store, ids = _library(tmp_path)
    moves = films.plan(root, films.soundtrack_rows(store))
    pairs = sorted((m.src.relative_to(root).as_posix(), m.dst.relative_to(root).as_posix()) for m in moves)
    assert pairs == [
        ("Soundtracks/Aashiq Banaya Aapne (2008)/01 Aashiq Banaya Aapne.m4a",
         "Soundtracks/Aashiq Banaya Aapne (2005)/01 Aashiq Banaya Aapne.m4a"),
        ("Soundtracks/Alaakaa Loova (From OM Chapter 1) (2026)/01 Alaakaa Loova.m4a",
         "Soundtracks/OM Chapter 1 (2026)/Alaakaa Loova.m4a"),
        ("Soundtracks/Ratata (From “Leo”) (2023)/01 Ratata.m4a", "Soundtracks/Leo (2023)/Ratata.m4a"),
        ("Soundtracks/The Wild Theme (From OM Chapter 1) (2026)/01 The Wild Theme.m4a",
         "Soundtracks/OM Chapter 1 (2026)/The Wild Theme.m4a"),
    ]
    record = tmp_path / "folder-moves.json"
    assert films.apply(store, moves, record) == 4
    leo = root / "Soundtracks" / "Leo (2023)"
    assert (leo / "Ratata.m4a").exists() and (leo / "Ratata.lrc").exists()          # its lyrics went along
    assert not (root / "Soundtracks" / "Ratata (From “Leo”) (2023)").exists()        # the empty folder is gone
    assert store.track(ids["01 Ratata.m4a"])["file_path"] == str(leo / "Ratata.m4a")
    assert len(json.loads(record.read_text(encoding="utf-8"))) == 4
    assert films.plan(root, films.soundtrack_rows(store)) == []                         # nothing left to fold


def test_a_new_song_goes_to_its_films_folder(tmp_path, monkeypatch):
    root, store, _ = _library(tmp_path)
    rows = films.soundtrack_rows(store)
    assert films.folder_for(root, rows, "Naa Ready (From “Leo”)", "Naa Ready", 2023) == Path("Soundtracks/Leo (2023)")
    assert films.folder_for(root, rows, "Jailer", "Hukum", 2023) is None
    monkeypatch.setattr(lib, "encode", lambda src, dst, fmt, kbps: dst.parent.mkdir(parents=True, exist_ok=True)
                        or dst.write_bytes(b"m4a"))
    monkeypatch.setattr(lib, "tag", lambda *a, **k: None)
    ident = Identity(title="Naa Ready", album="Naa Ready (From “Leo”)", artist="Vijay", album_artist="Anirudh",
                     year=2023, track_number=1, secondary_types=["Soundtrack"])
    dst = lib.file_take(tmp_path / "take.flac", root, ident, "aac", 256, "", {}, None,
                        into=Path("Soundtracks/Leo (2023)"))
    assert dst == root / "Soundtracks" / "Leo (2023)" / "Naa Ready.m4a"


def test_saving_in_the_library_editor_keeps_a_gathered_song_in_place(tmp_path, monkeypatch, tmp_config):
    root, store, ids = _library(tmp_path)
    films.apply(store, films.plan(root, films.soundtrack_rows(store)))
    tmp_config.paths.library_dir = root
    monkeypatch.setattr(md, "tag", lambda *a, **k: None)
    monkeypatch.setattr(md, "read_file_extras", lambda path: (None, ""))
    monkeypatch.setattr(md, "read_kept_tags", lambda path: {})
    row = store.track(ids["01 Ratata.m4a"])
    ident = json.loads(row["identity_json"])
    ident.update(secondary_types=["Soundtrack"], year=2023, track_number=1, artist="Anirudh")
    store.conn.execute("UPDATE tracks SET identity_json=? WHERE id=?", (json.dumps(ident), row["id"]))
    store.conn.commit()
    res = md.refresh_track(tmp_config, store, store.track(row["id"]), lookup=False, move=True)
    assert res["path"] == str(root / "Soundtracks" / "Leo (2023)" / "Ratata.m4a")


DC = "Anirudh Ravichander, Heisenberg, Vedan, Ashwin Krishna"
ZEHER = "Anu Malik, Mithun Sharma, Roop Kumar Rathod & Naresh Sharma"


def test_the_album_artist_a_films_songs_share():
    """The 9 films that showed up twice in a player on November 20, then the cases around them."""
    def share(*credits):
        return films.shared_album_artist([c if isinstance(c, films.Credit) else films.Credit(c) for c in credits])

    assert share(*["Himesh Reshammiya & Sameer"] * 3, *["Himesh Reshammiya"] * 2) == "Himesh Reshammiya"
    assert share(*["Anirudh Ravichander, Srinivasa Mouli, Krishna Kanth & Heisenberg"] * 3,
                 *["Anirudh Ravichander"] * 3) == "Anirudh Ravichander"
    # Ain't Nobody, filed from Spotify's tags, had only its own artist as album artist
    assert share(*[DC] * 14, films.Credit("Anirudh Ravichander", counts=False)) == DC
    assert share("Shashwat Sachdev, Charanjit Ahuja, Hanumankind, Jasmine Sandlas, Babu Singh Maan, Irshad Kamil, "
                 "Reble & Raj Ranjodh", "Shashwat Sachdev") == "Shashwat Sachdev"
    assert share(*["Anirudh Ravichander"] * 4, "Various Artists") == "Anirudh Ravichander"
    assert share(*["Jatin‐Lalit, Sandesh Shandilya & Sameer"] * 10,        # MusicBrainz's hyphen, U+2010
                 "Jatin-Lalit, Sandesh Shandilya & Sameer") == "Jatin‐Lalit, Sandesh Shandilya & Sameer"
    assert share(*["Anirudh Ravichander"] * 9, "Anirudh Ravichander & Shakthisree Gopalan",
                 "Anirudh Ravichander & Nikhita Gandhi") == "Anirudh Ravichander"
    assert share("Kalyanji Anandji", "Kalyanji Anandji", "Kalyanji - Anandji") == "Kalyanji Anandji"
    assert share(ZEHER, ZEHER, "Various Artists", "Various Artists") == ZEHER

    assert share("Anu Malik", "Anu Malik", "Himesh Reshammiya") == "Anu Malik"          # no name in common
    assert share("Pritam", "Anu Malik") == "Pritam"                                     # a tie: the shorter
    # one odd credit doesn't take the film over: the name in the most credits stays
    assert share(*["Himesh Reshammiya & Sameer"] * 3, *["Himesh Reshammiya"] * 2, "Himesh") == "Himesh Reshammiya"
    assert share("Various Artists", "Various Artists") == "Various Artists"
    assert share("A, B & C", "A, B & D") == "A & B"                     # no song has just the names they share
    assert share(films.Credit("Sid Sriram", counts=False)) == "Sid Sriram"    # nothing better to go on
    assert share(films.Credit("Anirudh Ravichander"), films.Credit("Various Artists", typed="Anirudh")) == "Anirudh"
    assert share() == "" and share("") == ""


def _flac(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    x = np.zeros(4800, dtype=np.float32)
    sf.write(str(path), np.stack([x, x], axis=1), 48000, subtype="PCM_16")
    return path


def _films(cfg):
    """Real FLAC files of 4 films whose songs carry more than one album artist, as on November 20."""
    store = Store(cfg.paths.db_path)
    ids = {}

    def song(folder, title, album_artist, artist="Singer", source="acoustid", typed="", **extra):
        f = _flac(cfg.paths.library_dir / "Soundtracks" / folder / f"{title}.flac")
        album = folder.rsplit(" (", 1)[0]
        ident = {"title": title, "album": album, "artist": artist, "album_artist": album_artist, "source": source,
                 "secondary_types": ["Soundtrack"], "year": int(folder[-5:-1]), **extra}
        ids[title] = store.add_track(artist=artist, title=title, album=album, album_artist=typed or album_artist,
                                     duration_ms=100, file_path=str(f), state="library", meta_json={},
                                     identity_json=json.dumps(ident),
                                     manual_json=json.dumps({"album_artist": typed} if typed else {}))

    for title in ("Aashiq Banaya Aapne", "Mar Jaawan Mit Jaawan", "Dilnashin Dilnashin"):
        song("Aashiq Banaya Aapne (2005)", title, "Himesh Reshammiya & Sameer", mb_release_id="aba-2008")
    for title in ("Aap Ki Kashish", "Aap Ki Kashish (Remix)"):
        song("Aashiq Banaya Aapne (2005)", title, "Himesh Reshammiya", mb_release_id="aba-2005")
    song("DC (2026)", "Hangova", DC)
    song("DC (2026)", "Vizhigale", DC)
    song("DC (2026)", "Ain't Nobody", "Anirudh Ravichander", artist="Anirudh Ravichander", source="spotify")
    song("Zeher (2005)", "Woh Lamhe Woh Baatein", ZEHER)
    song("Zeher (2005)", "Agar Tum Mil Jao", "Various Artists")
    song("Jailer (2023)", "Hukum", "Anirudh Ravichander")
    song("Jailer (2023)", "Jujubee", "Anirudh Ravichander")
    song("Jailer (2023)", "Jailer Swag-up", "Various Artists", typed="Anirudh")        # typed on the Library page
    return store, ids


def test_each_films_songs_get_one_album_artist(tmp_config):
    store, ids = _films(tmp_config)
    pp = PostProcessor(tmp_config, store)
    assert pp.share_film_tags() == 7
    now = {title: store.track(i)["album_artist"] for title, i in ids.items()}
    assert {now[t] for t in ("Aashiq Banaya Aapne", "Mar Jaawan Mit Jaawan", "Dilnashin Dilnashin", "Aap Ki Kashish",
                             "Aap Ki Kashish (Remix)")} == {"Himesh Reshammiya"}
    assert {now[t] for t in ("Hangova", "Vizhigale", "Ain't Nobody")} == {DC}
    assert {now[t] for t in ("Woh Lamhe Woh Baatein", "Agar Tum Mil Jao")} == {ZEHER}
    assert {now[t] for t in ("Hukum", "Jujubee", "Jailer Swag-up")} == {"Anirudh"}     # the typed one wins
    song = store.track(ids["Aashiq Banaya Aapne"])
    assert FLAC(song["file_path"])["ALBUMARTIST"] == ["Himesh Reshammiya"]                # the file says so too
    ident = json.loads(song["identity_json"])
    assert ident["album_artist"] == "Himesh Reshammiya" and ident["album_credit"] == "Himesh Reshammiya & Sameer"
    assert json.loads(store.track(ids["Jailer Swag-up"])["manual_json"]) == {"album_artist": "Anirudh"}
    record = json.loads((tmp_config.paths.db_path.parent / "album-artists.json").read_text(encoding="utf-8"))
    assert len(record) == 7 and {"file": song["file_path"], "from": "Himesh Reshammiya & Sameer",
                                 "to": "Himesh Reshammiya", "sort": ["", ""], "ids": [[], []]} in record
    assert pp.share_film_tags() == 0                                                     # nothing left to change


def test_the_sort_name_and_ids_go_with_the_films_album_artist(tmp_config):
    """A player that sorts by album artist reads the sort name: "Reshammiya, Himesh & Sameer" on 3 songs kept them apart
    from the 2 sorted as "Reshammiya, Himesh"."""
    store, ids = _films(tmp_config)
    for title, sort, mbids in (("Aashiq Banaya Aapne", "Reshammiya, Himesh & Sameer", ["himesh", "sameer"]),
                               ("Mar Jaawan Mit Jaawan", "Reshammiya, Himesh & Sameer", ["himesh", "sameer"]),
                               ("Dilnashin Dilnashin", "Reshammiya, Himesh & Sameer", ["himesh", "sameer"]),
                               ("Aap Ki Kashish", "Reshammiya, Himesh", ["himesh"]),
                               ("Aap Ki Kashish (Remix)", "Reshammiya, Himesh", ["himesh"]),
                               ("Hukum", "Ravichander, Anirudh", ["anirudh"])):
        ident = json.loads(store.track(ids[title])["identity_json"])
        ident.update(album_artist_sort=sort, mb_album_artist_ids=mbids)
        store.conn.execute("UPDATE tracks SET identity_json=? WHERE id=?", (json.dumps(ident), ids[title]))
    store.conn.commit()
    PostProcessor(tmp_config, store).share_film_tags()
    song = store.track(ids["Aashiq Banaya Aapne"])
    ident = json.loads(song["identity_json"])
    assert ident["album_artist_sort"] == "Reshammiya, Himesh" and ident["mb_album_artist_ids"] == ["himesh"]
    assert FLAC(song["file_path"])["ALBUMARTISTSORT"] == ["Reshammiya, Himesh"]
    assert FLAC(song["file_path"])["MUSICBRAINZ_ALBUMARTISTID"] == ["himesh"]
    # a typed name no release gives goes without them: Hukum's belonged to "Anirudh Ravichander"
    hukum = json.loads(store.track(ids["Hukum"])["identity_json"])
    assert (hukum["album_artist"], hukum["album_artist_sort"], hukum["mb_album_artist_ids"]) == ("Anirudh", "", [])


def _inbox(cfg, store, title, album, album_artist):
    flac = _flac(cfg.paths.inbox_dir / f"{title}.flac")
    meta = {"artist": "Singer", "title": title, "album": album, "expected_ms": 100}
    flac.with_suffix(".json").write_text(json.dumps({"meta": meta, "capture": {}}), encoding="utf-8")
    store.add_track(artist="Singer", title=title, duration_ms=100, file_path=str(flac), state="inbox")
    return flac, Identity(source="acoustid", title=title, artist="Singer", album=album, album_artist=album_artist,
                          album_credit=album_artist, year=2023, secondary_types=["Soundtrack"])


def test_a_new_song_takes_its_films_album_artist(tmp_config, monkeypatch):
    """A single joining Leo takes the name it shares with the film, and a song with fewer names narrows its film."""
    store, ids = _films(tmp_config)
    tmp_config.library.format = "flac"                      # the take is copied as it is, so no encoder is needed
    pp = PostProcessor(tmp_config, store)
    assert pp.share_film_tags() == 7
    monkeypatch.setattr(P, "resolve_cover", lambda *a: None)
    monkeypatch.setattr(P.lyr, "fetch", lambda *a, **k: None)
    leo = tmp_config.paths.library_dir / "Soundtracks" / "Leo (2023)"
    for title in ("Naa Ready", "Badass"):
        f = _flac(leo / f"{title}.flac")
        store.add_track(artist="Anirudh Ravichander", title=title, album="Leo", album_artist="Anirudh Ravichander",
                        duration_ms=100, file_path=str(f), state="library",
                        identity_json=json.dumps({"album": "Leo", "title": title, "source": "acoustid"}))

    take, ident = _inbox(tmp_config, store, "Ordinary Person", "Ordinary Person (From “Leo”)",
                         "Anirudh Ravichander & Nikhita Gandhi")
    pp.identify_take = lambda path, meta: (ident, "")
    dst = pp.process(take)
    assert dst == leo / "Ordinary Person.flac" and FLAC(dst)["ALBUMARTIST"] == ["Anirudh Ravichander"]
    row = store.conn.execute("SELECT album_artist, identity_json FROM tracks WHERE file_path=?", (str(dst),)).fetchone()
    assert row["album_artist"] == "Anirudh Ravichander"
    assert json.loads(row["identity_json"])["album_credit"] == "Anirudh Ravichander & Nikhita Gandhi"
    pp._film_tags_stale = False
    assert pp.share_film_tags() == 0                        # Leo's other songs already had it

    # a Zeher song from a release that credits only Anu Malik leaves the film with the one name they all have
    take, ident = _inbox(tmp_config, store, "Zeher Theme", "Zeher", "Anu Malik")
    ident.year = 2005
    pp.identify_take = lambda path, meta: (ident, "")
    dst = pp.process(take)
    assert dst.parent.name == "Zeher (2005)" and FLAC(dst)["ALBUMARTIST"] == ["Anu Malik"]
    assert pp._film_tags_stale                               # so the film's other songs follow right after filing
    assert pp.share_film_tags() == 2
    assert FLAC(store.track(ids["Agar Tum Mil Jao"])["file_path"])["ALBUMARTIST"] == ["Anu Malik"]


def _release(artist):
    return {"title": "Aashiq Banaya Aapne", "artist": artist, "artist_sort": artist, "artist_ids": [], "date": "2008",
            "country": "IN", "status": "Official", "barcode": "", "label": "", "catalog": "", "original_date": "",
            "rg_type": "album", "rg_secondary": ["Soundtrack"], "genres": [], "disc_total": 1, "media": []}


def test_a_look_up_keeps_its_films_album_artist(tmp_config, monkeypatch):
    """The weekly retry looks songs up again, and MusicBrainz gives each its own release's credit again."""
    store, ids = _films(tmp_config)
    PostProcessor(tmp_config, store).share_film_tags()
    monkeypatch.setattr(mb, "release", lambda mbid: _release("Himesh Reshammiya & Sameer"))
    monkeypatch.setattr(md.genres, "resolve", lambda *a, **k: None)
    monkeypatch.setattr(md.lyr, "fetch", lambda *a, **k: None)
    monkeypatch.setattr(md, "resolve_cover", lambda *a, **k: None)
    row = store.track(ids["Mar Jaawan Mit Jaawan"])
    res = md.refresh_track(tmp_config, store, row, lookup=True, move=True)
    assert res["path"] == row["file_path"]                                    # it stays in its film's folder
    assert res["ident"].album_artist == "Himesh Reshammiya" == store.track(row["id"])["album_artist"]
    assert res["ident"].album_credit == "Himesh Reshammiya & Sameer"
    assert FLAC(row["file_path"])["ALBUMARTIST"] == ["Himesh Reshammiya"]

    # an album artist typed on the Library page stays, and the film's other songs take it
    res = md.refresh_track(tmp_config, store, store.track(ids["Aap Ki Kashish"]), lookup=False,
                           manual={"album_artist": "Himesh Reshammiya (Music Director)"}, move=False)
    assert res["ident"].album_artist == "Himesh Reshammiya (Music Director)"
    assert PostProcessor(tmp_config, store).share_film_tags() == 4


# -- one album name per film -----------------------------------------------------------------

LEO_SINGLES = ("I’m Scared (From “Leo”)", "Ratata (From “Leo”)", "Villain Yaaru (From “Leo”)",
               "Ordinary Person (From “Leo”)")
JAILER_2 = "Jailer 2 (Original Motion Picture Soundtrack)"
OM = "OM Chapter 1: Udhiram - The Blood Wood"


def _songs(*albums):
    return [films.Song(i, album, album) for i, album in enumerate(albums)]


def test_the_album_name_a_films_songs_share():
    """The 11 films a player that groups by album name showed more than once on November 20."""
    def share(*albums):
        return films.shared_album(_songs(*albums))

    assert share(*["Leo"] * 7, *LEO_SINGLES) == "Leo"
    assert share(*["Aavesham"] * 5, *["Aavesham (Original Motion Picture Soundtrack)"] * 2) == "Aavesham"
    assert share("Saripodhaa Sanivaaram", "Saripodhaa Sanivaaram (Original Motion Picture Soundtrack)") == \
        "Saripodhaa Sanivaaram"                                                     # a tie goes to the shorter
    assert share(*["Super"] * 2, *["Super (Original Motion Picture Soundtrack)"] * 2) == "Super"
    odyssey = "The Odyssey: Original Motion Picture Soundtrack"
    assert share(*[odyssey] * 22, "The Odyssey (Original Motion Picture Soundtrack)") == odyssey
    assert share(*["Kabhi Khushi Kabhie Gham"] * 10, "Kabhi Khushi Kabhie Gham...") == "Kabhi Khushi Kabhie Gham"
    assert share(*["Muqaddar Ka Sikandar: Original Soundtrack"] * 2, "Muqaddar Ka Sikandar") == \
        "Muqaddar Ka Sikandar: Original Soundtrack"
    assert share(*[JAILER_2] * 11, 'Hukum Reloaded - Tamil (From "Jailer 2")',
                 'Tiger Muthuvel Pandian (From "Jailer 2")') == JAILER_2
    assert share("Jailer", "Jailer", 'Jailer Swag-up (From "Jailer")') == "Jailer"
    assert share("Devara Part 1", 'All Hail The Tiger (From "Devara Part 1")') == "Devara Part 1"
    # a film with only singles takes the film's name from them
    assert share(f'The Wild Theme (From "{OM}")', f'Alaakaa Loova (From "{OM}") [Tamil]',
                 f'Alaakaa Loova Unplugged (From "{OM}") [Tamil]') == OM

    assert share('Hukum (From "Jailer")', 'Hukum (From "Jailer")') == 'Hukum (From "Jailer")'     # shared already
    typed = _songs("Leo", "Leo", "Ratata (From “Leo”)")
    typed[2].album, typed[2].typed = "Leo (2023 film)", True
    assert films.shared_album(typed) == "Leo (2023 film)"                           # a typed album wins
    assert share() == "" and share("", "") == ""


def _single(i, album, date, track=(1, 1, 1, 1), **kw):
    return films.Song(i, album, album, album.split(" (")[0], date, track, **kw)


def test_a_films_singles_are_numbered_after_its_album():
    """Each single's tags said track 1 of 1, so a player that showed Leo as one album listed 5 songs as track 1."""
    leo = [films.Song(i, "Leo", "Leo", f"Song {i}", "2023-10-19", (i, 7, 1, 1)) for i in range(1, 8)]
    leo += [_single(10 + i, album, date) for i, (album, date) in
            enumerate(zip(LEO_SINGLES, ("2023-10-27", "2023-11-09", "2023-10-20", "2023-10-24")))]
    tags = films.film_tags(leo)
    assert {t.album for t in tags.values()} == {"Leo"}
    assert all(tags[i].track == () for i in range(1, 8))                            # the album's songs keep theirs
    assert [tags[10 + i].track[:2] for i in range(4)] == [(10, 11), (11, 11), (8, 11), (9, 11)]

    # Jailer 2's album has 12 songs and the library 11 of them, so its singles come after the 12th
    songs = [films.Song(i, JAILER_2, JAILER_2, track=(i, 12, 1, 1)) for i in range(1, 12)]
    songs += [_single(20, 'Hukum Reloaded - Tamil (From "Jailer 2")', "2025-01-14"),
              _single(21, 'Tiger Muthuvel Pandian (From "Jailer 2")', "2026-10-20")]
    tags = films.film_tags(songs)
    assert (tags[20].track, tags[21].track) == ((13, 14, 1, 1), (14, 14, 1, 1))

    # a film with only singles numbers them from 1, in the order they came out
    tags = films.film_tags([_single(1, f'Alaakaa Loova (From "{OM}") [Tamil]', "2026-07-28"),
                            _single(2, f'The Wild Theme (From "{OM}")', "2026-06-19")])
    assert (tags[1].album, tags[1].track, tags[2].track) == (OM, (2, 2, 1, 1), (1, 2, 1, 1))

    # a typed track number stays, and an album on 2 discs gets its singles after the second
    songs = [films.Song(1, "Ghajini", "Ghajini", track=(5, 5, 1, 2)),
             films.Song(2, "Ghajini", "Ghajini", track=(3, 4, 2, 2)),
             _single(3, 'Behka (From "Ghajini")', "2008-11-01"),
             _single(4, 'Guzarish (From "Ghajini")', "2008-11-02", track=(12, 1, 1, 1), typed_track=True)]
    tags = films.film_tags(songs)
    assert (tags[3].track, tags[4].track) == ((5, 5, 2, 2), ())

    # songs from one release keep their numbers, as do the album's songs from a second edition
    one = films.film_tags([_single(1, 'Hukum (From "Jailer")', "2023", (1, 2, 1, 1)),
                           _single(2, 'Hukum (From "Jailer")', "2023", (2, 2, 1, 1))])
    assert [t.track for t in one.values()] == [(), ()]
    tags = films.film_tags([films.Song(1, "Muqaddar Ka Sikandar: Original Soundtrack", "", track=(2, 8, 1, 1)),
                            films.Song(2, "Muqaddar Ka Sikandar", "", track=(12, 13, 1, 1))])
    assert (tags[1].track, tags[2].track) == ((), ())
    assert films.film_tags(_songs("Leo")) == {}                                     # a song alone keeps its own


def _soundtracks(cfg):
    """Real FLAC files of 3 films whose songs carry more than one album name, as on November 20."""
    store = Store(cfg.paths.db_path)
    ids = {}

    def song(folder, name, album, title, track, date, source="acoustid", **extra):
        f = _flac(cfg.paths.library_dir / "Soundtracks" / folder / f"{name}.flac")
        ident = {"title": title, "album": album, "artist": "Singer", "album_artist": "Anirudh Ravichander",
                 "source": source, "secondary_types": ["Soundtrack"], "year": int(date[:4]), "date": date,
                 "track_number": track[0], "track_total": track[1], "disc_number": 1, "disc_total": 1, **extra}
        ids[title] = store.add_track(artist="Singer", title=title, album=album, album_artist="Anirudh Ravichander",
                                     track_number=track[0], duration_ms=100, file_path=str(f), state="library",
                                     meta_json={}, identity_json=json.dumps(ident))

    for n, title in enumerate(("Bloody Sweet", "Naa Ready", "Badass"), start=1):
        song("Leo (2023)", f"0{n} {title}", "Leo", title, (n, 7), "2023-10-19")
    song("Leo (2023)", "Ratata", "Ratata (From “Leo”)", "Ratata", (1, 1), "2023-11-09",
         mb_release_id="ratata-single", mb_recording_id="ratata")
    song("Leo (2023)", "Villain Yaaru", "Villain Yaaru (From “Leo”)", "Villain Yaaru", (1, 1), "2023-10-20")
    for n, title in ((4, "Galatta"), (5, "The Last Dance"), (6, "Odimaga")):
        song("Aavesham (2024)", f"0{n} {title}", "Aavesham", title, (n, 9), "2024-04-11")
    song("Aavesham (2024)", "01 Mathapithakkale", "Aavesham (Original Motion Picture Soundtrack)", "Mathapithakkale",
         (1, 9), "2024-04-11", source="spotify")
    folder = "OM Chapter 1 Udhiram - The Blood Wood (2026)"
    song(folder, "Alaakaa Loova (From OM Chapter 1 Udhiram - The Blood Wood) [Tamil]",
         f'Alaakaa Loova (From "{OM}") [Tamil]', f'Alaakaa Loova (From "{OM}") [Tamil]', (1, 1), "2026-07-28",
         source="spotify")
    song(folder, "The Wild Theme (From OM Chapter 1 Udhiram - The Blood Wood)", f'The Wild Theme (From "{OM}")',
         f'The Wild Theme (From "{OM}")', (1, 1), "2026-06-19", source="spotify")
    return store, ids


def test_each_films_songs_get_one_album_name(tmp_config):
    store, ids = _soundtracks(tmp_config)
    pp = PostProcessor(tmp_config, store)
    assert pp.share_film_tags() == 5              # Leo's 2 singles, 1 Aavesham song, OM Chapter 1's 2 singles
    ratata = store.track(ids["Ratata"])
    assert (ratata["album"], ratata["track_number"]) == ("Leo", 9)
    assert Path(ratata["file_path"]).name == "Ratata.flac"                          # its file keeps its name
    tags = FLAC(ratata["file_path"])
    assert (tags["ALBUM"], tags["TRACKNUMBER"], tags["TRACKTOTAL"]) == (["Leo"], ["9"], ["9"])
    ident = json.loads(ratata["identity_json"])
    assert (ident["album"], ident["track_number"], ident["track_total"]) == ("Ratata (From “Leo”)", 1, 1)
    assert (ident["film_album"], ident["film_track"]) == ("Leo", [9, 9, 1, 1])
    own = md.identity_from_row(ratata)                                              # its own album and number stay
    assert (own.album, own.track_number, own.film_album) == ("Ratata (From “Leo”)", 1, "Leo")
    assert FLAC(store.track(ids["Villain Yaaru"])["file_path"])["TRACKNUMBER"] == ["8"]
    assert FLAC(store.track(ids["Mathapithakkale"])["file_path"])["ALBUM"] == ["Aavesham"]
    assert FLAC(store.track(ids["Mathapithakkale"])["file_path"])["TRACKNUMBER"] == ["1"]
    wild = FLAC(store.track(ids[f'The Wild Theme (From "{OM}")'])["file_path"])
    assert (wild["ALBUM"], wild["TRACKNUMBER"], wild["TRACKTOTAL"]) == ([OM], ["1"], ["2"])
    record = json.loads((tmp_config.paths.db_path.parent / "album-names.json").read_text(encoding="utf-8"))
    assert len(record) == 5 and {"file": ratata["file_path"], "from": "Ratata (From “Leo”)", "to": "Leo",
                                 "track": [[1, 1, 1, 1], [9, 9, 1, 1]]} in record
    assert pp.share_film_tags() == 0                                                # nothing left to change

    # a song left alone in its folder gets its own album and number back
    store.conn.execute("DELETE FROM tracks WHERE id=?", (ids[f'The Wild Theme (From "{OM}")'],))
    store.conn.commit()
    assert pp.share_film_tags() == 1
    alaakaa = store.track(ids[f'Alaakaa Loova (From "{OM}") [Tamil]'])
    assert (alaakaa["album"], alaakaa["track_number"]) == (f'Alaakaa Loova (From "{OM}") [Tamil]', 1)
    assert FLAC(alaakaa["file_path"])["TRACKNUMBER"] == ["1"]


def test_a_look_up_keeps_a_singles_film_album(tmp_config, monkeypatch):
    """MusicBrainz gives a single its own release's album and number again, and Library edits move songs."""
    store, ids = _soundtracks(tmp_config)
    PostProcessor(tmp_config, store).share_film_tags()
    release = dict(_release(""), title="Ratata (From “Leo”)", date="2023-11-09", rg_type="single",
                   media=[{"position": 1, "track_count": 1, "format": "Digital Media",
                           "tracks": [{"position": 1, "recording_id": "ratata", "title": "Ratata", "artist": ""}]}])
    monkeypatch.setattr(mb, "release", lambda mbid: release)
    monkeypatch.setattr(mb, "recording", lambda mbid: None)
    monkeypatch.setattr(md.genres, "resolve", lambda *a, **k: None)
    monkeypatch.setattr(md.lyr, "fetch", lambda *a, **k: None)
    monkeypatch.setattr(md, "resolve_cover", lambda *a, **k: None)
    row = store.track(ids["Ratata"])
    res = md.refresh_track(tmp_config, store, row, lookup=True, move=True)
    assert res["path"] == row["file_path"]                      # still Ratata.flac, with no 01 or 09 in front
    assert (store.track(row["id"])["album"], store.track(row["id"])["track_number"]) == ("Leo", 9)
    assert FLAC(row["file_path"])["ALBUM"] == ["Leo"] and FLAC(row["file_path"])["TRACKNUMBER"] == ["9"]
    assert (res["ident"].album, res["ident"].release_album) == ("Ratata (From “Leo”)",) * 2

    # a typed track number stays, and the film's other single closes up after the album
    md.refresh_track(tmp_config, store, store.track(ids["Villain Yaaru"]), lookup=False,
                     manual={"track_number": 12}, move=False)
    assert FLAC(store.track(ids["Villain Yaaru"])["file_path"])["TRACKNUMBER"] == ["12"]
    assert PostProcessor(tmp_config, store).share_film_tags() == 1
    assert FLAC(row["file_path"])["TRACKNUMBER"] == ["8"] and FLAC(row["file_path"])["TRACKTOTAL"] == ["8"]

    # an album typed on the Library page stays, and the film's other songs take it
    md.refresh_track(tmp_config, store, store.track(ids["Galatta"]), lookup=False,
                     manual={"album": "Aavesham (2024 film)"}, move=False)
    assert PostProcessor(tmp_config, store).share_film_tags() == 3
    assert {store.track(ids[t])["album"] for t in ("Galatta", "The Last Dance", "Odimaga", "Mathapithakkale")} == \
        {"Aavesham (2024 film)"}


def test_a_new_single_joins_its_films_album(tmp_config, monkeypatch):
    store, ids = _soundtracks(tmp_config)
    tmp_config.library.format = "flac"
    pp = PostProcessor(tmp_config, store)
    pp.share_film_tags()
    monkeypatch.setattr(P, "resolve_cover", lambda *a: None)
    monkeypatch.setattr(P.lyr, "fetch", lambda *a, **k: None)
    take, ident = _inbox(tmp_config, store, "I'm Scared", "I’m Scared (From “Leo”)", "Anirudh Ravichander")
    ident.date, ident.track_number, ident.track_total = "2023-10-27", 1, 1
    pp.identify_take = lambda path, meta: (ident, "")
    dst = pp.process(take)
    leo = tmp_config.paths.library_dir / "Soundtracks" / "Leo (2023)"
    assert dst == leo / "I'm Scared.flac"
    assert (FLAC(dst)["ALBUM"], FLAC(dst)["TRACKNUMBER"]) == (["Leo"], ["9"])      # after Villain Yaaru, before Ratata
    row = store.conn.execute("SELECT album, track_number, identity_json FROM tracks WHERE file_path=?",
                             (str(dst),)).fetchone()
    assert (row["album"], row["track_number"]) == ("Leo", 9)
    assert json.loads(row["identity_json"])["release_album"] == "I’m Scared (From “Leo”)"
    assert pp._film_tags_stale and pp.share_film_tags() == 2      # Villain Yaaru's count and Ratata's place change
    assert FLAC(store.track(ids["Ratata"])["file_path"])["TRACKNUMBER"] == ["10"]
