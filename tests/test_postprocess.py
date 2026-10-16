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
