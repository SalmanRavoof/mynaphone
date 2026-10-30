# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Lyricist and composer credits for Indian film songs from JioSaavn, where MusicBrainz has none.

Off unless you turn it on in Settings. JioSaavn's web API isn't published, and its terms, updated October 7, 2026,
forbid automated access, so the choice is yours. It asks politely: a request every 3 seconds at most, 2 searches
per song, 200 requests a day, and after any reply it can't read it leaves JioSaavn alone for hours.

One JioSaavn record can't be trusted on its own. On October 30 every Jailer 2 track, an instrumental too, listed
the same 6 lyricists; label singles named the composer as lyricist; and the Kabhi Khushi Kabhie Gham title song's
lyricist changed between two requests 3 minutes apart. So the copies of one recording, which share a vcode, are
read together, each is cleaned, and a name is taken only when 2 copies agree on it, or when the copy on the film's
own album names it and no other copy disagrees. Credits only fill empty fields; MusicBrainz and your own edits win.
"""
from __future__ import annotations

import difflib
import html
import json
import logging
import random
import re
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import films

log = logging.getLogger("mynaphone.jiosaavn")

API = "https://www.jiosaavn.com/api.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/141.0 Safari/537.36",
           "Accept": "application/json, text/plain, */*", "Referer": "https://www.jiosaavn.com/"}
GAP_SECONDS = 3.0
DAILY_REQUESTS = 200
PAUSE_SECONDS = (3600.0, 86400.0)       # after a reply it can't read: an hour, doubling up to a day
LANGUAGES = {"ta": "tamil", "tam": "tamil", "te": "telugu", "tel": "telugu", "hi": "hindi", "hin": "hindi",
             "ml": "malayalam", "mal": "malayalam", "kn": "kannada", "kan": "kannada", "bn": "bengali",
             "ben": "bengali", "mr": "marathi", "mar": "marathi", "pa": "punjabi", "pan": "punjabi"}
VERSION_WORDS = ("remix", "reprise", "jhankar", "unplugged", "sad", "lofi", "lo-fi", "karaoke", "cover",
                 "instrumental", "recreated", "slowed", "reverb", "sped up", "mashup")

_lock = threading.Lock()
_last = 0.0
_day = ("", 0)                          # (date, requests made that day)
_resume_at = 0.0
_pause = PAUSE_SECONDS[0]


class Unavailable(Exception):
    """JioSaavn didn't answer as expected, or the day's requests are used up. Not the same as "not found"."""


@dataclass
class Credits:
    lyricists: list[str] = field(default_factory=list)
    composers: list[str] = field(default_factory=list)
    song_id: str = ""
    vcode: str = ""
    copies: int = 0


# -- requests ---------------------------------------------------------------------------------

def _get(params: dict) -> dict:
    global _last, _day, _resume_at, _pause
    if time.monotonic() < _resume_at:
        raise Unavailable(f"JioSaavn is paused for {(_resume_at - time.monotonic()) / 60:.0f} more minutes")
    today = time.strftime("%Y-%m-%d")
    with _lock:
        if _day[0] != today:
            _day = (today, 0)
        if _day[1] >= DAILY_REQUESTS:
            raise Unavailable("today's JioSaavn requests are used up")
        _day = (today, _day[1] + 1)
        wait = GAP_SECONDS + random.uniform(0, 1.0) - (time.monotonic() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.monotonic()
    query = {"_format": "json", "_marker": "0", "api_version": "4", "ctx": "web6dot0", **params}
    req = urllib.request.Request(f"{API}?{urllib.parse.urlencode(query)}", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
    except Exception as e:
        _resume_at = time.monotonic() + _pause
        _pause = min(_pause * 2, PAUSE_SECONDS[1])
        raise Unavailable(f"JioSaavn's reply couldn't be read ({e}); trying again in {_pause / 7200:.0f} h") from e
    _pause = PAUSE_SECONDS[0]
    return data


def search(query: str, n: int = 30) -> list[dict]:
    data = _get({"__call": "search.getResults", "q": query, "n": str(n), "p": "1"})
    if "results" not in data:
        # an empty reply can mean a firewall quietly refusing this address, so it isn't taken as "no such song"
        raise Unavailable("JioSaavn's search answered without results")
    return [r for r in data["results"] or [] if isinstance(r, dict)]


# -- matching ---------------------------------------------------------------------------------

def _text(s) -> str:
    return html.unescape(str(s or "")).strip()


def fold(s: str) -> str:
    """A title or name for comparing transliterations: no accents, punctuation, doubled letters or long vowels."""
    s = unicodedata.normalize("NFKD", _text(s)).encode("ascii", "ignore").decode().casefold()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = s.replace("aa", "a").replace("ee", "i").replace("oo", "u")
    s = re.sub(r"(.)\1+", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def title_core(title: str) -> str:
    """The song's own name: no "(From X)", language tag or version note."""
    t = re.sub(r"\((?:from|feat|ft)[^)]*\)", " ", title or "", flags=re.I)
    t = re.sub(r"\s[-–]\s.*$", " ", t)
    t = re.sub(r"[\(\[].*?[\)\]]", " ", t)
    return re.sub(r"\s+", " ", t).strip() or (title or "")


def language_hint(title: str, album: str, language: str = "") -> str:
    m = re.search(r"\b(" + "|".join(sorted(set(LANGUAGES.values()))) + r")\b", f"{title} {album}", re.I)
    if m:
        return m.group(1).lower()
    return LANGUAGES.get((language or "").lower(), "")


def _people(r: dict) -> dict:
    mi = r.get("more_info") or {}
    am = mi.get("artistMap") or {}
    roles: dict[str, list[str]] = {}
    for a in am.get("artists") or []:
        roles.setdefault(a.get("role") or "", []).append(_text(a.get("name")))
    roles["primary"] = [_text(a.get("name")) for a in am.get("primary_artists") or []]
    return roles


def _accept(r: dict, core: str, ours: list[str], duration_s: float, language: str) -> bool:
    if r.get("type") != "song":
        return False
    title = _text(r.get("title"))
    if difflib.SequenceMatcher(None, fold(title_core(title)), fold(core)).ratio() < 0.9:
        return False
    low, ours_low = title.lower(), core.lower()
    if any(w in low and w not in ours_low for w in VERSION_WORDS):
        return False
    try:
        if abs(float((r.get("more_info") or {}).get("duration") or 0) - duration_s) > 3.0:
            return False
    except (TypeError, ValueError):
        return False
    if language and (r.get("language") or "").lower() not in ("", language):
        return False
    people = _people(r)
    theirs = {fold(n) for role in ("primary", "singer", "music") for n in people.get(role, [])}
    return bool(theirs & {fold(n) for n in ours})


def _clean(r: dict) -> tuple[list[str], list[str]]:
    """One copy's lyricists and composers, without the patterns that made JioSaavn's records wrong."""
    people = _people(r)
    lyricists, composers = people.get("lyricist", []), people.get("music", [])
    singers, primary = people.get("singer", []), people.get("primary", [])
    if singers and not ({fold(s) for s in singers} & {fold(p) for p in primary}):
        return [], []           # the singers aren't the song's own: the record belongs to another song
    if len(lyricists) > 3:
        lyricists = []          # the whole album's lyricists, not this song's
    if len(lyricists) == 1 and composers == lyricists and singers == lyricists:
        lyricists = []          # a label default that names the one artist everywhere
    if len(composers) >= 2:
        composers = [c for c in composers if fold(c) not in {fold(x) for x in lyricists}]
    return lyricists, composers


def _agree(copies: list[tuple[dict, list[str]]], film: str) -> list[str]:
    """Names 2 copies agree on, or the film album copy's names when no other copy disagrees."""
    if not copies:
        return []
    counts: dict[str, int] = {}
    shown: dict[str, str] = {}
    for _, names in copies:
        for n in dict.fromkeys(names):
            counts[fold(n)] = counts.get(fold(n), 0) + 1
            shown.setdefault(fold(n), n)
    agreed = [shown[k] for k, c in counts.items() if c >= 2]
    if agreed:
        return agreed
    def names_film(r):
        return bool(film) and fold(film) in fold((r.get("more_info") or {}).get("album"))

    # copies left empty by the cleaning don't count either way: the Jailer 2 album's 6 lyricists aren't a vote
    film_named = [names for r, names in copies if names and names_film(r)]
    others = [names for r, names in copies if names and not names_film(r)]
    if film_named and all(set(map(fold, n)) == set(map(fold, film_named[0])) for n in film_named + others):
        return film_named[0]
    return []


def credits_for(title: str, artists: list[str], album: str, duration_s: float, language: str = "") -> Credits | None:
    """The credits JioSaavn's copies of this recording agree on, or None. Raises Unavailable when JioSaavn
    can't be asked; that isn't "not found"."""
    core = title_core(title)
    film_info = films.film_of(album, title)
    film = film_info.name if film_info else ""
    hint = language_hint(title, album, language)
    queries = [f"{core} {film}".strip()]
    if artists:
        queries.append(f"{core} {artists[0]}")
    for q in dict.fromkeys(queries):
        results = search(q)
        ok = [r for r in results if _accept(r, core, artists, duration_s, hint)]
        if not ok:
            continue
        # the recording: the candidate sharing most artists with ours, then the closest length
        ours = {fold(n) for n in artists}

        def score(r):
            people = _people(r)
            overlap = len(ours & {fold(n) for role in ("primary", "singer") for n in people.get(role, [])})
            return (-overlap, abs(float(r["more_info"].get("duration") or 0) - duration_s))
        best = min(ok, key=score)
        vcode = (best.get("more_info") or {}).get("vcode") or ""
        same = [r for r in ok if vcode and (r.get("more_info") or {}).get("vcode") == vcode] or [best]
        cleaned = [(r, _clean(r)) for r in same]
        found = Credits(lyricists=_agree([(r, c[0]) for r, c in cleaned], film),
                        composers=_agree([(r, c[1]) for r, c in cleaned], film),
                        song_id=best.get("id", ""), vcode=vcode, copies=len(same))
        if found.lyricists or found.composers:
            return found
    return None
