# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Indian film credits from JioSaavn, on its own replies saved on October 30, 2026 (trimmed to the fields read)."""
import json
from pathlib import Path

import pytest

import mynaphone.jiosaavn as J
import mynaphone.postprocess as P
from mynaphone.postprocess import PostProcessor
from mynaphone.store import Store

SAVED = json.loads((Path(__file__).parent / "data" / "jiosaavn_searches.json").read_text(encoding="utf-8"))


def _answering(monkeypatch, name):
    monkeypatch.setattr(J, "search", lambda q, n=30: SAVED[name])


@pytest.mark.parametrize("name, title, artists, album, seconds, lyricists, composers", [
    ("rukja", "Ruk Ja O Dil Deewane", ["Udit Narayan"], "Dilwale Dulhania Le Jayenge", 310.5,
     ["Anand Bakshi"], ["Jatin-Lalit"]),
    ("k3g", "Kabhi Khushi Kabhie Gham", ["Lata Mangeshkar"], "Kabhi Khushi Kabhie Gham", 472.2,
     ["Sameer Anjaan"], ["Jatin Pandit", "Lalit Pandit"]),
    # the album copy lists the whole album's 6 lyricists; the single names the song's own
    ("hukum_reloaded", 'Hukum Reloaded - Tamil (From "Jailer 2")', ["Anirudh Ravichander"],
     'Hukum Reloaded - Tamil (From "Jailer 2")', 91.5, ["Super Subu"], ["Anirudh Ravichander"]),
    # one compilation names a lyricist no other copy has: not enough
    ("ratata_leo", 'Ratata (From "Leo")', ["Anirudh Ravichander", "Vijay"], "Ratata (From “Leo”)", 131.6,
     [], ["Anirudh Ravichander"]),
])
def test_credits_the_copies_agree_on(monkeypatch, name, title, artists, album, seconds, lyricists, composers):
    _answering(monkeypatch, name)
    got = J.credits_for(title, artists, album, seconds)
    assert got.lyricists == lyricists and got.composers == composers


def test_a_record_rewritten_with_another_songs_credits_gives_nothing(monkeypatch):
    """3 minutes after the first reply, the K3G title song's record named A.M. Turaz and two other singers."""
    _answering(monkeypatch, "k3g_again")
    assert J.credits_for("Kabhi Khushi Kabhie Gham", ["Lata Mangeshkar"], "Kabhi Khushi Kabhie Gham", 472.2) is None


def test_a_different_edit_or_language_is_not_the_song(monkeypatch):
    _answering(monkeypatch, "rukja")
    assert J.credits_for("Ruk Ja O Dil Deewane", ["Udit Narayan"], "Dilwale Dulhania Le Jayenge", 330.0) is None
    _answering(monkeypatch, "hukum_reloaded")
    language = {r["id"]: r["language"] for r in SAVED["hukum_reloaded"]}
    got = J.credits_for("Hukum Reloaded", ["Anirudh Ravichander"], "Jailer 2", 91.5, language="kn")
    assert got is None or language[got.song_id] == "kannada"     # 5 languages share the title and length


def test_requests_are_spaced_and_a_bad_reply_pauses_them(monkeypatch):
    state = {"now": 1000.0, "sent": []}
    monkeypatch.setattr(J.time, "monotonic", lambda: state["now"])
    monkeypatch.setattr(J.time, "sleep", lambda s: state.__setitem__("now", state["now"] + s))
    monkeypatch.setattr(J, "_last", 0.0)
    monkeypatch.setattr(J, "_resume_at", 0.0)
    monkeypatch.setattr(J, "_pause", J.PAUSE_SECONDS[0])
    monkeypatch.setattr(J, "_day", ("", 0))
    replies = [b'{"results": []}', b'<html>blocked</html>']

    class Reply:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self.body

    def urlopen(req, timeout=0):
        state["sent"].append(state["now"])
        return Reply(replies.pop(0))

    monkeypatch.setattr(J.urllib.request, "urlopen", urlopen)
    assert J.search("ratata leo") == []
    with pytest.raises(J.Unavailable):
        J.search("ratata leo")
    assert state["sent"][1] - state["sent"][0] >= J.GAP_SECONDS
    with pytest.raises(J.Unavailable, match="paused"):
        J.search("ratata leo")                          # nothing goes out during the pause
    assert len(state["sent"]) == 2


def test_the_job_fills_only_empty_credits_and_keeps_your_edits(tmp_config, monkeypatch):
    store = Store(tmp_config.paths.db_path)
    f = tmp_config.paths.library_dir / "Soundtracks" / "DDLJ (1995)" / "01 Ruk Ja O Dil Deewane.m4a"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"m4a")
    ident = {"title": "Ruk Ja O Dil Deewane", "artist": "Udit Narayan", "album": "Dilwale Dulhania Le Jayenge",
             "composers": ["Jatin–Lalit"], "secondary_types": ["Soundtrack"], "year": 1995}
    tid = store.add_track(artist="Udit Narayan", title="Ruk Ja O Dil Deewane", album="Dilwale Dulhania Le Jayenge",
                          duration_ms=310_500, file_path=str(f), state="library", lyrics_state="synced",
                          identity_json=json.dumps(ident), missing_json='["lyricists"]')
    pp = PostProcessor(tmp_config, store)
    _answering(monkeypatch, "rukja")
    tagged = []
    monkeypatch.setattr(P, "refresh_track", lambda cfg, st, row, lookup, move: tagged.append(row["id"]))
    assert pp.fill_indian_credits() == 1
    got = json.loads(store.track(tid)["identity_json"])
    assert got["lyricists"] == ["Anand Bakshi"] and got["composers"] == ["Jatin–Lalit"]    # MusicBrainz's stays
    assert got["credits_from"].startswith("JioSaavn ") and "9 copies" in got["credits_from"] and tagged == [tid]
    assert pp.fill_indian_credits() == 0                        # asked once a month at most

    def down(*a, **k):
        raise J.Unavailable("JioSaavn's reply couldn't be read")
    store.conn.execute("UPDATE tracks SET credits_tried_at=NULL, identity_json=? WHERE id=?", (json.dumps(ident), tid))
    store.conn.commit()
    monkeypatch.setattr(J, "credits_for", down)
    pp.fill_indian_credits()
    assert store.track(tid)["credits_tried_at"] is None         # no answer isn't an answer
