# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Synced lyrics from LRCLIB (free, keyless). Returns LRC text when available, else plain text."""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass

log = logging.getLogger("mynaphone.lyrics")

BASE = "https://lrclib.net/api"
USER_AGENT = "mynaphone/0.1 (https://github.com/salmanravoof/mynaphone)"


@dataclass
class Lyrics:
    synced: str = ""
    plain: str = ""
    instrumental: bool = False
    source: str = "lrclib"

    @property
    def best(self) -> str:
        return self.synced or self.plain


def _get(path: str, params: dict, timeout: float = 15.0):
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Lrclib-Client": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def fetch(title: str, artist: str, album: str, duration_s: float) -> Lyrics | None:
    """Exact match first (LRCLIB tolerates ±2 s on duration), then a search fallback."""
    params = {"track_name": title, "artist_name": artist, "duration": int(round(duration_s))}
    if album:
        params["album_name"] = album
    d = _get("get", params)
    if d is None and album:
        d = _get("get", {k: v for k, v in params.items() if k != "album_name"})
    if d is None:
        hits = _get("search", {"track_name": title, "artist_name": artist}) or []
        for h in hits:
            if abs(float(h.get("duration") or 0) - duration_s) <= 3.0:
                d = h
                break
        if d is None and hits:
            d = hits[0] if abs(float(hits[0].get("duration") or 0) - duration_s) <= 8.0 else None
    if not d:
        return None
    return Lyrics(synced=d.get("syncedLyrics") or "", plain=d.get("plainLyrics") or "",
                  instrumental=bool(d.get("instrumental")))
