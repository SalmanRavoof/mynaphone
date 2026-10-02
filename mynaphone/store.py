# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""SQLite index of archived tracks and a log of every take, used for dedup and status."""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from pathlib import Path

# Ordered quality tiers. Higher index = better. Unknown tiers rank as "unknown" (0).
TIERS = ["unknown", "low", "youtube", "normal", "high", "very_high", "hifi", "hifi24"]


def tier_rank(tier: str | None) -> int:
    t = (tier or "unknown").lower()
    return TIERS.index(t) if t in TIERS else 0


_norm_re = re.compile(r"[^a-z0-9]+")


def norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", s)          # drop bracketed qualifiers like (feat. X) / [Remastered]
    s = re.sub(r"\b(feat|ft)\.?\b.*$", " ", s)
    return _norm_re.sub(" ", s).strip()


def local_time(stamp: str | None, fmt: str = "%H:%M", tz: dt.tzinfo | None = None) -> str:
    """A stored timestamp in this PC's time zone (or `tz`), for display. The database keeps UTC."""
    try:
        return dt.datetime.fromisoformat(stamp).astimezone(tz).strftime(fmt)
    except (TypeError, ValueError):
        return ""


SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    artist TEXT, title TEXT, album TEXT, album_artist TEXT, track_number INTEGER,
    artist_norm TEXT, title_norm TEXT,
    duration_ms INTEGER,
    source_app TEXT, source_uri TEXT, quality_tier TEXT,
    file_path TEXT, state TEXT,            -- inbox | library
    created_at TEXT, meta_json TEXT,
    lyrics_state TEXT, lyrics_tries INTEGER DEFAULT 0, identity_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_tracks_norm ON tracks(artist_norm, title_norm);
CREATE INDEX IF NOT EXISTS idx_tracks_uri ON tracks(source_uri);
CREATE TABLE IF NOT EXISTS takes (
    id INTEGER PRIMARY KEY,
    started_at TEXT, ended_at TEXT,
    artist TEXT, title TEXT, album TEXT, source_app TEXT, source_uri TEXT,
    expected_ms INTEGER, captured_ms INTEGER, wall_ms INTEGER,
    verdict TEXT, reasons TEXT, file_path TEXT, quality_tier TEXT
);
"""


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        have = {r[1] for r in self.conn.execute("PRAGMA table_info(tracks)")}
        for col, typ in (("lyrics_state", "TEXT"), ("lyrics_tries", "INTEGER DEFAULT 0"), ("identity_json", "TEXT"),
                         ("manual_json", "TEXT"), ("missing_json", "TEXT"), ("last_lookup", "TEXT"),
                         ("lookup_tries", "INTEGER DEFAULT 0")):
            if col not in have:
                self.conn.execute(f"ALTER TABLE tracks ADD COLUMN {col} {typ}")
        self.conn.commit()

    # -- dedup -----------------------------------------------------------------------------

    def find_archived(self, artist: str, title: str, duration_ms: int, uri: str | None = None,
                      tolerance_ms: int = 2000) -> sqlite3.Row | None:
        """Best existing copy of this song, matched by source uri or normalized artist/title + duration."""
        if uri:
            row = self.conn.execute(
                "SELECT * FROM tracks WHERE source_uri=? ORDER BY id DESC LIMIT 1", (uri,)).fetchone()
            if row:
                return row
        rows = self.conn.execute(
            "SELECT * FROM tracks WHERE artist_norm=? AND title_norm=?", (norm(artist), norm(title))).fetchall()
        best = None
        for r in rows:
            if r["duration_ms"] and abs(int(r["duration_ms"]) - int(duration_ms)) <= tolerance_ms:
                if best is None or tier_rank(r["quality_tier"]) > tier_rank(best["quality_tier"]):
                    best = r
        return best

    def add_track(self, **fields) -> int:
        fields.setdefault("created_at", dt.datetime.now(dt.timezone.utc).isoformat())
        fields["artist_norm"] = norm(fields.get("artist", ""))
        fields["title_norm"] = norm(fields.get("title", ""))
        if isinstance(fields.get("meta_json"), (dict, list)):
            fields["meta_json"] = json.dumps(fields["meta_json"], ensure_ascii=False)
        cols = ", ".join(fields)
        qs = ", ".join("?" for _ in fields)
        cur = self.conn.execute(f"INSERT INTO tracks ({cols}) VALUES ({qs})", list(fields.values()))
        self.conn.commit()
        return int(cur.lastrowid)

    def replace_track(self, old_id: int, **fields) -> int:
        self.conn.execute("DELETE FROM tracks WHERE id=?", (old_id,))
        return self.add_track(**fields)

    # -- take log --------------------------------------------------------------------------

    def log_take(self, **fields) -> int:
        if isinstance(fields.get("reasons"), (list, tuple)):
            fields["reasons"] = json.dumps(list(fields["reasons"]))
        cols = ", ".join(fields)
        qs = ", ".join("?" for _ in fields)
        cur = self.conn.execute(f"INSERT INTO takes ({cols}) VALUES ({qs})", list(fields.values()))
        self.conn.commit()
        return int(cur.lastrowid)

    # -- status ----------------------------------------------------------------------------

    def summary(self) -> dict:
        c = self.conn
        return {
            "tracks_inbox": c.execute("SELECT COUNT(*) FROM tracks WHERE state='inbox'").fetchone()[0],
            "tracks_library": c.execute("SELECT COUNT(*) FROM tracks WHERE state='library'").fetchone()[0],
            "takes_kept": c.execute("SELECT COUNT(*) FROM takes WHERE verdict='keep'").fetchone()[0],
            "takes_discarded": c.execute("SELECT COUNT(*) FROM takes WHERE verdict='discard'").fetchone()[0],
            "takes_skipped": c.execute("SELECT COUNT(*) FROM takes WHERE verdict='skip'").fetchone()[0],
        }

    def recent_takes(self, n: int = 15) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM takes ORDER BY id DESC LIMIT ?", (n,)).fetchall()

    def library_rows(self, only_incomplete: bool = False) -> list[sqlite3.Row]:
        q = "SELECT * FROM tracks WHERE state='library'"
        if only_incomplete:
            q += " AND missing_json IS NOT NULL AND missing_json != '[]'"
        return self.conn.execute(q + " ORDER BY album_artist, album, track_number, title").fetchall()

    def track(self, track_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM tracks WHERE id=?", (track_id,)).fetchone()

    def incomplete_for_retry(self, min_age_days: float = 7.0, limit: int = 10) -> list[sqlite3.Row]:
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=min_age_days)).isoformat()
        return self.conn.execute(
            "SELECT * FROM tracks WHERE state='library' AND missing_json IS NOT NULL AND missing_json != '[]' "
            "AND (last_lookup IS NULL OR last_lookup < ?) AND COALESCE(lookup_tries,0) < 30 "
            "ORDER BY last_lookup LIMIT ?",
            (cutoff, limit)).fetchall()
