# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""One folder per film: film keys, the folds planned and done on a temporary library, filing and editing."""
import json
from pathlib import Path

import mynaphone.library as lib
import mynaphone.metadata as md
from mynaphone import films
from mynaphone.identify import Identity
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
    row = store.track(ids["01 Ratata.m4a"])
    ident = json.loads(row["identity_json"])
    ident.update(secondary_types=["Soundtrack"], year=2023, track_number=1, artist="Anirudh")
    store.conn.execute("UPDATE tracks SET identity_json=? WHERE id=?", (json.dumps(ident), row["id"]))
    store.conn.commit()
    res = md.refresh_track(tmp_config, store, store.track(row["id"]), lookup=False, move=True)
    assert res["path"] == str(root / "Soundtracks" / "Leo (2023)" / "Ratata.m4a")
