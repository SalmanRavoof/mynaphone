# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Filing: a recording already in the library isn't filed twice. Identification, lyrics, covers and encoding are
stubbed, so no network or ffmpeg is needed."""
import json

import mynaphone.postprocess as P
from mynaphone.identify import Identity
from mynaphone.postprocess import PostProcessor
from mynaphone.store import Store


def _processor(cfg, monkeypatch):
    events = []
    pp = PostProcessor(cfg, Store(cfg.paths.db_path), on_event=events.append)
    pp.identify_take = lambda path, meta: (Identity(source="acoustid", title="Hukum - Thalaivar Alappara",
                                                    artist="Anirudh Ravichander", album="Jailer",
                                                    mb_recording_id="rec-1", isrc="QMBZ92351475"), "")
    monkeypatch.setattr(P, "resolve_cover", lambda *a: None)
    monkeypatch.setattr(P.lyr, "fetch", lambda *a, **k: None)

    def fake_file_take(src, library_dir, ident, fmt, bitrate, text, capture, cover):
        dst = library_dir / "Soundtracks" / "Jailer (2023)" / f"{capture['quality_tier']} Hukum.m4a"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"m4a")
        return dst
    monkeypatch.setattr(P, "file_take", fake_file_take)
    return pp, events


def _inbox_take(cfg, store, title, uri, tier="high"):
    flac = cfg.paths.inbox_dir / f"{title}.flac"
    flac.parent.mkdir(parents=True, exist_ok=True)
    flac.write_bytes(b"fLaC")
    meta = {"artist": "Anirudh Ravichander", "title": title, "source_uri": uri, "quality_tier": tier,
            "expected_ms": 207_600}
    flac.with_suffix(".json").write_text(json.dumps({"meta": meta, "capture": {}}), encoding="utf-8")
    store.add_track(artist=meta["artist"], title=title, duration_ms=207_600, source_uri=uri, quality_tier=tier,
                    file_path=str(flac), state="inbox")
    store.log_take(verdict="keep", reasons=[], artist=meta["artist"], title=title, file_path=str(flac))
    return flac


def test_second_copy_of_a_recording_is_set_aside(tmp_config, monkeypatch):
    """The Jailer album track and its single are one recording; the second take used to overwrite the first file."""
    pp, events = _processor(tmp_config, monkeypatch)
    filed = pp.process(_inbox_take(tmp_config, pp.store, "Hukum", "spotify:track:album"))
    second = _inbox_take(tmp_config, pp.store, "Hukum - Tamil (From Jailer)", "spotify:track:single")
    assert pp.process(second) == filed
    assert filed.exists() and not second.exists()
    assert (tmp_config.paths.discard_dir / second.name).exists()
    rows = pp.store.conn.execute("SELECT source_uri, state FROM tracks").fetchall()
    assert [(r["source_uri"], r["state"]) for r in rows] == [("spotify:track:album", "library")]
    assert pp.store.find_archived("x", "y", 1, uri="spotify:track:single") is not None   # its next play is skipped
    assert [e["kind"] for e in events] == ["filed", "duplicate"]


def test_better_copy_of_a_recording_replaces_the_filed_one(tmp_config, monkeypatch):
    pp, events = _processor(tmp_config, monkeypatch)
    old = pp.process(_inbox_take(tmp_config, pp.store, "Hukum (Official Video)", "youtube:abc", tier="youtube"))
    new = pp.process(_inbox_take(tmp_config, pp.store, "Hukum", "spotify:track:album", tier="high"))
    assert new != old and new.exists() and not old.exists()
    rows = pp.store.conn.execute("SELECT source_uri, quality_tier FROM tracks").fetchall()
    assert [(r["source_uri"], r["quality_tier"]) for r in rows] == [("spotify:track:album", "high")]
    assert pp.store.find_archived("x", "y", 1, uri="youtube:abc")["source_uri"] == "spotify:track:album"
    assert [e["kind"] for e in events] == ["filed", "filed"]


def test_a_lyrics_lookup_without_an_answer_is_not_a_try(tmp_config, monkeypatch):
    """Songs used to file with one of their 10 lyrics tries spent even when LRCLIB answered 503."""
    pp, events = _processor(tmp_config, monkeypatch)

    def busy(*args, **kwargs):
        raise P.lyr.Unavailable("LRCLIB answered 503 Service Unavailable", 900)

    monkeypatch.setattr(P.lyr, "fetch", busy)
    pp.process(_inbox_take(tmp_config, pp.store, "Hukum", "spotify:track:album"))
    row = pp.store.conn.execute("SELECT lyrics_state, lyrics_tries, lyrics_tried_at FROM tracks").fetchone()
    assert tuple(row) == ("none", 0, None)


def test_has_no_words():
    from mynaphone.identify import has_no_words
    assert has_no_words(Identity(title="Nothing Sinister", album="Casino Royale", language="zxx"))
    assert has_no_words(Identity(title="Soul of K3G", album="Kabhi Khushi Kabhie Gham"), "Soul Of K3G - Instrumental")
    assert has_no_words(Identity(title="Metro Fight", album="Karuppu - Side B (God Mode Begins) [Original Score]"))
    assert has_no_words(Identity(title="Wade In", album="Sinners: Original Motion Picture Score"))
    assert not has_no_words(Identity(title="Ratata", album="Leo (Original Motion Picture Soundtrack)", language="tam"))
    assert not has_no_words(Identity(title="Score", album="Score"))


def _song(store, folder, title, album, lyrics_state="none", manual=None, **ident):
    f = folder / album.replace(":", " -") / f"{title}.m4a"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"m4a")
    ident = {"title": title, "album": album, **ident}
    return store.add_track(artist="A", title=title, album=album, album_artist="A", duration_ms=200_000,
                           file_path=str(f), state="library", lyrics_state=lyrics_state,
                           identity_json=json.dumps(ident), manual_json=json.dumps(manual or {}),
                           missing_json='["lyrics", "synced_lyrics", "lyricists", "isrc"]')


def test_scores_and_wordless_albums_are_marked_instrumental(tmp_config):
    store = Store(tmp_config.paths.db_path)
    pp = PostProcessor(tmp_config, store)
    lib = tmp_config.paths.library_dir
    pof = "Guild Wars 2: Path of Fire (Original Soundtrack)"
    score = [_song(store, lib, f"Theme {i}", pof, mb_release_id="pof") for i in range(5)]
    sung = _song(store, lib, "Sung Theme", pof, mb_release_id="pof", vocals=["Singer"])
    kept_vocal = _song(store, lib, "Theme 9", pof, mb_release_id="pof", manual={"instrumental": False})
    zxx = _song(store, lib, "Nothing Sinister", "Casino Royale", language="zxx")
    film = [_song(store, lib, f"Song {i}", "Leo (Original Motion Picture Soundtrack)", mb_release_id="leo",
                  lyrics_state="synced" if i else "none") for i in range(6)]
    assert pp.mark_instrumentals() == 6
    state = {i: store.track(i)["lyrics_state"] for i in score + [sung, kept_vocal, zxx] + film}
    assert all(state[i] == "instrumental" for i in score + [zxx])
    assert state[sung] == "none" and state[kept_vocal] == "none"       # a credited singer, and your own edit
    assert state[film[0]] == "none"                                     # a film album with words isn't a score
    assert json.loads(store.track(score[0])["missing_json"]) == ["isrc"]
