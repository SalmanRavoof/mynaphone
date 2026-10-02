# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Genre for each song, from the first source that has one: Apple's catalog, MusicBrainz, Last.fm, the folder.

Apple's search API is free and keyless and gives one genre per song (Bollywood, Rock, Soundtrack). MusicBrainz's
genres come with the identification. Last.fm's tags are listeners' labels, so only tags that are genre names (see
genres.txt) count, and only with a free API key. A soundtrack nothing else knows becomes Soundtrack. A genre
typed in the Library editor always wins; that happens after this, in metadata.apply_manual.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import cache
from pathlib import Path

from .lyrics import USER_AGENT
from .store import norm

log = logging.getLogger("mynaphone.genres")

APPLE_SEARCH = "https://itunes.apple.com/search"
APPLE_GAP_S = 3.1                         # Apple asks for no more than about 20 calls a minute
LASTFM_API = "https://ws.audioscrobbler.com/2.0/"
_apple_lock = threading.Lock()
_apple_last = 0.0
# Apple files a few items under its store's catch-all, which says nothing about the song
APPLE_IGNORED = {"music"}
# spellings worth keeping when a Last.fm tag is turned into a genre name
PRETTY = {"r&b": "R&B", "edm": "EDM", "idm": "IDM", "uk garage": "UK Garage", "lo-fi": "Lo-Fi",
          "k-pop": "K-Pop", "j-pop": "J-Pop", "hip hop": "Hip Hop"}


@cache
def known_genres() -> frozenset[str]:
    text = Path(__file__).with_name("genres.txt").read_text(encoding="utf-8")
    return frozenset(line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#"))


def pretty(name: str) -> str:
    name = name.strip().lower()
    return PRETTY.get(name) or " ".join(w[:1].upper() + w[1:] for w in name.split())


def _key(text: str) -> str:
    """A title or name as compared across catalogs: no brackets, no ' - From ...' tail, no punctuation."""
    return norm(re.sub(r"\s+-\s+.*$", "", text or ""))


def _get_json(url: str, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def pick_apple(results: list, title: str, artist: str, duration_s: float) -> dict | None:
    """The search result that is this song: the same title, plus the same artist or the same length."""
    want_title = _key(title)
    want_artists = [a for a in (_key(x) for x in re.split(r",|&| and |/", artist or "")) if a]
    best, best_score = None, 0.0
    for r in results:
        if not want_title or _key(r.get("trackName", "")) != want_title:
            continue
        score = 1.0
        got_artist = _key(r.get("artistName", ""))
        if any(a in got_artist or got_artist in a for a in want_artists if got_artist):
            score += 1.0
        ms = r.get("trackTimeMillis")
        if duration_s and ms:
            diff = abs(ms / 1000.0 - duration_s)
            score += 1.0 if diff <= 3.0 else -1.0 if diff > 15.0 else 0.0
        if score > best_score:
            best, best_score = r, score
    return best if best_score >= 2.0 else None


def apple_genre(title: str, artist: str, duration_s: float, country: str = "US") -> str:
    """Apple's genre for the song, or "" when its catalog doesn't have it. Network errors propagate."""
    global _apple_last
    bare_title = re.sub(r"[(\[].*?[)\]]", " ", title or "")
    query = urllib.parse.urlencode({"term": f"{artist} {bare_title}".strip(), "entity": "song", "limit": 10,
                                    "country": country or "US"})
    with _apple_lock:
        wait = APPLE_GAP_S - (time.monotonic() - _apple_last)
        if wait > 0:
            time.sleep(wait)
        _apple_last = time.monotonic()
    data = _get_json(f"{APPLE_SEARCH}?{query}")
    hit = pick_apple(data.get("results") or [], title, artist, duration_s)
    genre = ((hit or {}).get("primaryGenreName") or "").strip()
    return "" if genre.lower() in APPLE_IGNORED else genre


def lastfm_genre(title: str, artist: str, api_key: str) -> str:
    """The highest-ranked Last.fm tag that is a genre name, for the track, else for the artist."""
    for method, params in (("track.gettoptags", {"artist": artist, "track": title}),
                           ("artist.gettoptags", {"artist": artist})):
        query = urllib.parse.urlencode({"method": method, "api_key": api_key, "autocorrect": 1, "format": "json",
                                        **params})
        try:
            data = _get_json(f"{LASTFM_API}?{query}")
        except urllib.error.HTTPError as e:
            if e.code in (400, 403, 404):  # Last.fm answers "not found" and a bad key this way too
                data = json.loads(e.read().decode("utf-8") or "{}")
            else:
                raise
        if data.get("error"):
            if data["error"] in (10, 26):
                log.warning("Last.fm refused the API key (%s); check it on the Set up page", data.get("message"))
                return ""
            if data["error"] == 29:
                raise OSError("Last.fm rate limit")
            continue                     # 6: no such track or artist
        for tag in (data.get("toptags") or {}).get("tag") or []:
            name = (tag.get("name") or "").strip().lower()
            if name in known_genres():
                return pretty(name)
    return ""


def resolve(ident, artist: str, duration_s: float, cfg) -> None:
    """Set ident.genres from the first source that has a genre. Lookups that fail leave it for a later retry."""
    title = ident.title
    artist = ident.artist or artist
    failed = False
    try:
        apple = apple_genre(title, artist, duration_s, cfg.identify.apple_country)
    except (OSError, ValueError) as e:
        log.info("Apple genre lookup failed for %s: %s", title, e)
        apple, failed = "", True
    if apple:
        ident.genres = [apple] + [g for g in ident.genres if g.lower() != apple.lower()]
        return
    if ident.genres:                      # MusicBrainz's
        return
    key = cfg.identify.lastfm_api_key.strip()
    if key:
        try:
            tag = lastfm_genre(title, artist, key)
        except (OSError, ValueError) as e:
            log.info("Last.fm genre lookup failed for %s: %s", title, e)
            tag, failed = "", True
        if tag:
            ident.genres = [tag]
            return
    if ident.is_soundtrack and not failed:
        ident.genres = ["Soundtrack"]
