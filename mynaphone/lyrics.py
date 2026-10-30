# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Synced lyrics from LRCLIB (free, keyless). Returns LRC text when available, else plain text."""
from __future__ import annotations

import email.utils
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

log = logging.getLogger("mynaphone.lyrics")

BASE = "https://lrclib.net/api"
USER_AGENT = "mynaphone/0.1 (https://github.com/salmanravoof/mynaphone)"
MIN_GAP_SECONDS = 1.0       # between requests, from every thread, to keep a whole backfill polite
PAUSE_SECONDS = 900.0       # how long to leave LRCLIB alone after a 429 or 503 that doesn't say
SHORT_WAIT_SECONDS = 5.0    # a "busy, retry in a moment" this short is waited out once, then asked again

_lock = threading.Lock()
_last_request = 0.0
_resume_at = 0.0


class Unavailable(Exception):
    """LRCLIB asked for a pause or is down. `retry_after` is how long to leave it alone, in seconds."""

    def __init__(self, message: str, retry_after: float):
        super().__init__(message)
        self.retry_after = retry_after


def paused_for() -> float:
    """Seconds left before LRCLIB may be asked again; 0 when it may."""
    return max(0.0, _resume_at - time.monotonic())


def _retry_after(value: str | None) -> float | None:
    """A Retry-After header as seconds: either a number or an HTTP date."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
        return max(0.0, when.timestamp() - time.time())
    except (TypeError, ValueError):
        return None


@dataclass
class Lyrics:
    synced: str = ""
    plain: str = ""
    instrumental: bool = False
    source: str = "lrclib"

    @property
    def best(self) -> str:
        return self.synced or self.plain


def _get(path: str, params: dict, timeout: float = 15.0, again: bool = True):
    global _last_request, _resume_at
    wait = paused_for()
    if wait:
        raise Unavailable(f"LRCLIB asked for a pause, {wait / 60:.0f} min left", wait)
    with _lock:
        gap = time.monotonic() - _last_request
        if gap < MIN_GAP_SECONDS:
            time.sleep(MIN_GAP_SECONDS - gap)
        _last_request = time.monotonic()
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Lrclib-Client": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code in (429, 503):
            retry = _retry_after(e.headers.get("Retry-After") if e.headers else None)
            if again and retry is not None and retry <= SHORT_WAIT_SECONDS:
                time.sleep(retry)
                return _get(path, params, timeout, again=False)
            retry = retry or PAUSE_SECONDS
            _resume_at = time.monotonic() + retry
            raise Unavailable(f"LRCLIB answered {e.code} {e.reason}", retry) from e
        raise


def _closest(hits: list, duration_s: float) -> dict | None:
    """The hit within 3 s of the song's length, else the first hit if it's within 8 s."""
    for h in hits:
        if abs(float(h.get("duration") or 0) - duration_s) <= 3.0:
            return h
    if hits and abs(float(hits[0].get("duration") or 0) - duration_s) <= 8.0:
        return hits[0]
    return None


def _artist_variants(artist: str) -> list[str]:
    """The whole credit, then its first name: LRCLIB lists film songs under the lead singer, and its search
    answered 503 to some long credits ("Sonu Nigam, Jayesh Gandhi & Amrita Kak") that it answered for the first."""
    first = re.split(r",|&| and | feat\.? | ft\.? | x ", artist or "", maxsplit=1)[0].strip()
    return [artist] if not first or first == artist else [artist, first]


def fetch(title: str, artist: str, album: str, duration_s: float) -> Lyrics | None:
    """Exact match first (LRCLIB tolerates ±2 s on duration), then a search.

    The exact match asks get-cached, which reads only LRCLIB's own database. Plain get also asks other sites when a
    song isn't there, and that part was overloaded: for weeks it answered 503 "The server is busy" to such songs,
    while get-cached and search answered at once."""
    params = {"track_name": title, "artist_name": artist, "duration": int(round(duration_s))}
    if album:
        params["album_name"] = album
    d = _get("get-cached", params)
    if d is None and album:
        d = _get("get-cached", {k: v for k, v in params.items() if k != "album_name"})
    if d is None:
        busy = None
        for who in _artist_variants(artist):
            try:
                d = _closest(_get("search", {"track_name": title, "artist_name": who}) or [], duration_s)
                busy = None
            except Unavailable as e:
                if e.retry_after > SHORT_WAIT_SECONDS:
                    raise
                busy = e
                time.sleep(e.retry_after)       # busy with this query; the next one may go through
                continue
            if d is not None:
                break
        if d is None and busy is not None:
            raise busy                          # no search answered, so this wasn't a try
    if not d:
        return None
    return Lyrics(synced=d.get("syncedLyrics") or "", plain=d.get("plainLyrics") or "",
                  instrumental=bool(d.get("instrumental")))
