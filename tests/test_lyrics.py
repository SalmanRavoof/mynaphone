# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""LRCLIB requests: their spacing, the pauses LRCLIB asks for, and the lyrics backfill's line. No network."""
import email.message
import email.utils
import json
import time
import urllib.error

import pytest

import mynaphone.lyrics as L
from mynaphone.postprocess import PostProcessor
from mynaphone.store import Store


class _Reply:
    def __init__(self, body):
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


@pytest.fixture
def lrclib(monkeypatch):
    """LRCLIB on a fake clock. Each answer in `answers` is a reply body, an HTTP status, or (status, Retry-After)."""
    state = {"now": 5000.0, "sent": [], "answers": []}
    monkeypatch.setattr(L.time, "monotonic", lambda: state["now"])

    def sleep(seconds):
        state["now"] += seconds

    monkeypatch.setattr(L.time, "sleep", sleep)
    monkeypatch.setattr(L, "_last_request", 0.0)
    monkeypatch.setattr(L, "_resume_at", 0.0)

    def urlopen(req, timeout=0):
        state["sent"].append(state["now"])
        state.setdefault("urls", []).append(req.full_url)
        answer = state["answers"].pop(0) if state["answers"] else 404
        if isinstance(answer, (int, tuple)):
            code, retry = answer if isinstance(answer, tuple) else (answer, None)
            headers = email.message.Message()
            if retry is not None:
                headers["Retry-After"] = str(retry)
            raise urllib.error.HTTPError(req.full_url, code, "Service Unavailable", headers, None)
        return _Reply(answer)

    monkeypatch.setattr(L.urllib.request, "urlopen", urlopen)
    return state


def test_requests_are_spaced(lrclib):
    L._get("get", {"track_name": "a"})
    L._get("get", {"track_name": "b"})
    L._get("search", {"q": "b"})
    first, second, third = lrclib["sent"]
    assert second - first >= L.MIN_GAP_SECONDS and third - second >= L.MIN_GAP_SECONDS


def test_a_503_pauses_every_lookup(lrclib):
    lrclib["answers"] = [503]
    with pytest.raises(L.Unavailable) as e:
        L.fetch("Enter Sandman", "Metallica", "Metallica", 331)
    assert e.value.retry_after == L.PAUSE_SECONDS
    with pytest.raises(L.Unavailable):
        L.fetch("One", "Metallica", "...And Justice for All", 446)
    assert len(lrclib["sent"]) == 1                     # nothing more went out during the pause
    lrclib["now"] += L.PAUSE_SECONDS
    lrclib["answers"] = [{"syncedLyrics": "[00:01.00] Say your prayers", "plainLyrics": "Say your prayers"}]
    assert L.fetch("Enter Sandman", "Metallica", "Metallica", 331).synced.startswith("[00:01.00]")


def test_exact_matches_read_only_lrclibs_own_database(lrclib):
    """Plain get also asks other sites for a song LRCLIB lacks, and that part answered 503 for weeks."""
    lrclib["answers"] = [404, 404, [], []]
    assert L.fetch("Woh Ladki Jo", "Abhijeet & chorus", "Baadshah", 391) is None
    paths = [u.split("/api/", 1)[1].split("?", 1)[0] for u in lrclib["urls"]]
    assert paths == ["get-cached", "get-cached", "search", "search"]      # the credit, then "Abhijeet"


def test_a_short_busy_answer_is_waited_out_once(lrclib):
    lrclib["answers"] = [(503, 1), {"plainLyrics": "Kahin zulf ka baadal"}]
    assert L._get("search", {"q": "woh ladki jo"}) == {"plainLyrics": "Kahin zulf ka baadal"}
    first, second = lrclib["sent"]
    assert second - first >= 1 and L.paused_for() == 0


def test_the_pause_lrclib_asks_for_is_kept(lrclib):
    lrclib["answers"] = [(429, 120)]
    with pytest.raises(L.Unavailable) as e:
        L._get("get", {"track_name": "a"})
    assert e.value.retry_after == 120 and L.paused_for() == pytest.approx(120)


def test_retry_after_as_a_date():
    when = email.utils.formatdate(time.time() + 300, usegmt=True)
    assert 290 <= L._retry_after(when) <= 301
    assert L._retry_after("soon") is None and L._retry_after(None) is None


def _library_song(store, folder, title):
    f = folder / f"{title}.m4a"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"m4a")
    return store.add_track(artist="Metallica", title=title, album="Metallica", duration_ms=300_000,
                           file_path=str(f), state="library", lyrics_state="none", missing_json='["lyrics"]')


def test_backfill_stops_at_a_pause_and_sends_the_song_to_the_back(tmp_config, monkeypatch):
    store = Store(tmp_config.paths.db_path)
    pp = PostProcessor(tmp_config, store)
    titles = ("Enter Sandman", "Sad but True", "Unforgiven")
    ids = [_library_song(store, tmp_config.paths.library_dir, t) for t in titles]
    asked = []

    def fetch(title, artist, album, duration):
        asked.append(title)
        if len(asked) == 1:
            raise L.Unavailable("LRCLIB answered 503 Service Unavailable", 900)
        return None

    monkeypatch.setattr(L, "fetch", fetch)
    monkeypatch.setattr(L, "paused_for", lambda: 0.0)
    pp.backfill_lyrics()
    assert asked == ["Enter Sandman"]
    first = store.track(ids[0])
    assert first["lyrics_tries"] == 0 and first["lyrics_tried_at"]       # no answer, so no try counted
    pp.backfill_lyrics()
    assert asked == ["Enter Sandman", "Sad but True", "Unforgiven", "Enter Sandman"]
    assert [store.track(i)["lyrics_tries"] for i in ids] == [1, 1, 1]


def test_backfill_waits_while_lrclib_is_paused(tmp_config, monkeypatch):
    store = Store(tmp_config.paths.db_path)
    pp = PostProcessor(tmp_config, store)
    _library_song(store, tmp_config.paths.library_dir, "Enter Sandman")
    monkeypatch.setattr(L, "paused_for", lambda: 600.0)
    monkeypatch.setattr(L, "fetch", lambda *a: pytest.fail("asked LRCLIB during its pause"))
    assert pp.backfill_lyrics() == 0


def test_backfill_yields_to_a_new_song(tmp_config, monkeypatch):
    store = Store(tmp_config.paths.db_path)
    pp = PostProcessor(tmp_config, store)
    _library_song(store, tmp_config.paths.library_dir, "Enter Sandman")
    monkeypatch.setattr(L, "paused_for", lambda: 0.0)
    monkeypatch.setattr(L, "fetch", lambda *a: pytest.fail("looked up lyrics while a new song waited"))
    pp.kick()
    pp.backfill_lyrics()
    assert pp._interrupted


def test_a_busy_search_tries_the_lead_singer(lrclib):
    """LRCLIB's search answered 503 to "Sonu Nigam, Jayesh Gandhi & Amrita Kak", and found Just Chill under
    Sonu Nigam."""
    hit = {"duration": 326.0, "plainLyrics": "Just chill, chill, just chill"}
    lrclib["answers"] = [404, 404, (503, 1), (503, 1), [hit]]
    got = L.fetch("Just Chill", "Sonu Nigam, Jayesh Gandhi & Amrita Kak", "Maine Pyaar Kyun Kiya", 325.6)
    assert got.plain.startswith("Just chill")
    assert "artist_name=Sonu+Nigam&" in lrclib["urls"][-1] or lrclib["urls"][-1].endswith("artist_name=Sonu+Nigam")


def test_no_search_answering_is_not_an_answer(lrclib):
    lrclib["answers"] = [404, 404, (503, 1), (503, 1), (503, 1), (503, 1)]
    with pytest.raises(L.Unavailable):
        L.fetch("Just Chill", "Sonu Nigam, Jayesh Gandhi & Amrita Kak", "Maine Pyaar Kyun Kiya", 325.6)


def test_artist_variants():
    assert L._artist_variants("Sonu Nigam, Jayesh Gandhi & Amrita Kak") == [
        "Sonu Nigam, Jayesh Gandhi & Amrita Kak", "Sonu Nigam"]
    assert L._artist_variants("Parra for Cuva feat. Anna Naklab") == [
        "Parra for Cuva feat. Anna Naklab", "Parra for Cuva"]
    assert L._artist_variants("Metallica") == ["Metallica"]
