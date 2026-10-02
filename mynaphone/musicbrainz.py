# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Minimal MusicBrainz client: polite rate limit, one call per entity, JSON only."""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request

log = logging.getLogger("mynaphone.mb")

BASE = "https://musicbrainz.org/ws/2"
_lock = threading.Lock()
_last = 0.0
_contact = "https://github.com/salmanravoof/mynaphone"


def set_contact(contact: str) -> None:
    global _contact
    if contact and contact.strip():
        _contact = contact.strip()


def _get(path: str, inc: str = "", timeout: float = 20.0) -> dict | None:
    global _last
    url = f"{BASE}/{path}?fmt=json" + (f"&inc={urllib.parse.quote(inc)}" if inc else "")
    with _lock:
        wait = 1.1 - (time.monotonic() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": f"mynaphone/0.1 ( {_contact} )",
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code == 503:
            time.sleep(2.0)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        raise


def credit_string(credits: list[dict]) -> str:
    out = ""
    for c in credits or []:
        out += (c.get("name") or c.get("artist", {}).get("name", "")) + (c.get("joinphrase") or "")
    return out.strip()


def credit_names(credits: list[dict]) -> list[str]:
    return [c.get("name") or c.get("artist", {}).get("name", "") for c in credits or [] if c]


def credit_sort(credits: list[dict]) -> str:
    out = ""
    for c in credits or []:
        out += c.get("artist", {}).get("sort-name", c.get("name", "")) + (c.get("joinphrase") or "")
    return out.strip()


def _genres(obj: dict) -> list[str]:
    gs = sorted(obj.get("genres", []) or [], key=lambda g: -int(g.get("count", 0)))
    names = [g["name"] for g in gs if g.get("name")]
    if not names:
        ts = sorted(obj.get("tags", []) or [], key=lambda g: -int(g.get("count", 0)))
        names = [t["name"] for t in ts[:3] if t.get("name")]
    return names


def release(mbid: str) -> dict | None:
    """Release with media/tracks, label, release-group types, genres."""
    r = _get(f"release/{mbid}", "recordings+artist-credits+release-groups+labels+genres+tags")
    if not r:
        return None
    rg = r.get("release-group", {}) or {}
    out = {
        "title": r.get("title", ""),
        "date": r.get("date", ""),
        "country": r.get("country", ""),
        "status": r.get("status", ""),
        "barcode": r.get("barcode", ""),
        "artist": credit_string(r.get("artist-credit")),
        "artist_sort": credit_sort(r.get("artist-credit")),
        "artist_ids": [c.get("artist", {}).get("id", "") for c in r.get("artist-credit", []) or [] if c.get("artist")],
        "label": "", "catalog": "",
        "rg_id": rg.get("id", ""), "rg_type": (rg.get("primary-type") or "").lower(),
        "rg_secondary": [t for t in rg.get("secondary-types", []) or []],
        "original_date": rg.get("first-release-date", ""),
        "genres": _genres(r) or _genres(rg),
        "disc_total": len(r.get("media", []) or []),
        "media": [],
    }
    for li in r.get("label-info", []) or []:
        if li.get("label", {}).get("name") and not out["label"]:
            out["label"] = li["label"]["name"]
        if li.get("catalog-number") and not out["catalog"]:
            out["catalog"] = li["catalog-number"]
    for m in r.get("media", []) or []:
        out["media"].append({
            "position": int(m.get("position", 0) or 0),
            "track_count": int(m.get("track-count", 0) or len(m.get("tracks", []) or [])),
            "format": m.get("format", ""),
            "tracks": [{"position": int(t.get("position", 0) or 0), "number": t.get("number", ""),
                        "title": t.get("title", ""), "recording_id": t.get("recording", {}).get("id", ""),
                        "artist": credit_string(t.get("artist-credit") or t.get("recording", {}).get("artist-credit")),
                        "length": t.get("length")} for t in m.get("tracks", []) or []],
        })
    return out


def recording(mbid: str) -> dict | None:
    """Recording with ISRCs, performer relationships and linked works."""
    r = _get(f"recording/{mbid}", "artist-credits+isrcs+artist-rels+work-rels+genres+tags")
    if not r:
        return None
    out = {
        "title": r.get("title", ""),
        "artist": credit_string(r.get("artist-credit")),
        "artist_sort": credit_sort(r.get("artist-credit")),
        "artist_ids": [c.get("artist", {}).get("id", "") for c in r.get("artist-credit", []) or [] if c.get("artist")],
        "isrcs": r.get("isrcs", []) or [],
        "genres": _genres(r),
        "performers": [], "vocals": [], "producers": [], "works": [],
        "length": r.get("length"),
    }
    for rel in r.get("relations", []) or []:
        t = (rel.get("type") or "").lower()
        if rel.get("target-type") == "artist":
            name = rel.get("artist", {}).get("name", "")
            if not name:
                continue
            if t in ("vocal",):
                out["vocals"].append(name)
            elif t in ("producer",):
                out["producers"].append(name)
            elif t in ("instrument", "performer", "performing orchestra", "conductor"):
                out["performers"].append(name)
        elif rel.get("target-type") == "work" and rel.get("work", {}).get("id"):
            out["works"].append(rel["work"]["id"])
    return out


def work(mbid: str) -> dict | None:
    """Work with composer / lyricist / writer credits."""
    w = _get(f"work/{mbid}", "artist-rels")
    if not w:
        return None
    out = {"title": w.get("title", ""), "composers": [], "lyricists": [], "writers": [],
           "language": w.get("language", "")}
    for rel in w.get("relations", []) or []:
        t = (rel.get("type") or "").lower()
        name = rel.get("artist", {}).get("name", "")
        if not name:
            continue
        if t == "composer":
            out["composers"].append(name)
        elif t in ("lyricist", "librettist"):
            out["lyricists"].append(name)
        elif t == "writer":
            out["writers"].append(name)
    return out
