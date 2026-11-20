# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""The albums your songs come from, how many of each album's songs you have, and which albums you want whole.

An album is counted against the edition you played: the Spotify album your songs came from, with Spotify's own count
of its songs. Spotify can list one album more than once (a remaster and a deluxe box set, or one soundtrack from two
labels), so listings whose names differ only by edition words (Deluxe, Remastered, Original Soundtrack) and that
share an album artist are one album here, counted against the listing with the fewest songs. Songs that only a
bigger edition has are bonus songs, never missing ones. A film's dubbed album, such as Master (Telugu), and its
background score keep counts of their own.

Until an album's songs are read from Spotify, its count is the songs you recorded from that listing. Once they are,
each of its songs counts as yours when the library has it from any release, its single or another edition, matched
the way the recorder matches a song before it records it.

An album you don't have whole goes on the Wanted list once you have enough of its songs (3 unless you change it), or
when you add it yourself, and stays off once you take it off.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import playlists
from .store import Store

KINDS = ("album", "ep", "compilation")      # Spotify's kinds of album counted here; a single is a song
# words that only tell an album's editions apart, and the words of its soundtrack label
EDITION_WORDS = frozenset("""
    deluxe super edition editions version versions remaster remastered remasters anniversary expanded extended
    special bonus track tracks box set limited collector collectors s legacy definitive reissue standard mono stereo
    original motion picture game video film movie soundtrack soundtracks ost music from the with and of dvd cd
    high resolution hi res digital
    """.split())
_WORD = re.compile(r"[^\W_]+")
_GROUP = re.compile(r"[\(\[]([^\(\)\[\]]*)[\)\]]")
_TAIL = re.compile(r"(?:\s[-–]\s|:\s)([^:\-–]*)$")
_NUMBER = re.compile(r"\d+(?:st|nd|rd|th|s)?")
VARIOUS = "various artists"


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _edition_only(text: str) -> bool:
    words = _WORD.findall(text.casefold())
    return bool(words) and all(w in EDITION_WORDS or _NUMBER.fullmatch(w) for w in words)


def edition_key(name: str) -> str:
    """An album's name without the words that tell its editions apart, so "Master Of Puppets (Deluxe Box Set /
    Remastered)" and "Master Of Puppets (Remastered)" are both "master of puppets". Words that make another album
    stay: a language ("Master (Telugu)"), a background score, a dialogues version, remixes."""
    s = _GROUP.sub(lambda m: " " if _edition_only(m.group(1)) else f" {m.group(1)} ", name or "").rstrip()
    while True:
        m = _TAIL.search(s)                 # "The Wall: The High Resolution Remasters", "Garam Masala: Original ..."
        if not m or not _edition_only(m.group(1)):
            break
        s = s[:m.start()].rstrip()
    words = _WORD.findall(s.casefold())
    while len(words) > 1 and words[-1] in ("ost", "soundtrack"):
        words.pop()                         # "Divinity: Original Sin 2 OST"
    return " ".join(words)


# -- what the library holds ------------------------------------------------------------------

@dataclass
class Listing:
    """One Spotify album you have songs from: the edition you played."""
    uri: str
    name: str
    artists: list[str]
    kind: str
    total: int
    date: str
    songs: list[dict] = field(default_factory=list)     # your library songs recorded from it


def _song(row, meta: dict) -> dict:
    md = (meta.get("extra") or {}).get("track_metadata") or {}
    return {"id": int(row["id"]), "artist": row["artist"] or "", "title": row["title"] or "",
            "source_uri": row["source_uri"] or "", "file_path": row["file_path"] or "",
            "album_uri": meta.get("album_uri") or "", "duration_ms": _int(row["duration_ms"]),
            "track_number": _int(md.get("album_track_number")) or _int(row["track_number"]),
            "disc_number": _int(md.get("album_disc_number")) or 1}


def listings(store: Store) -> dict[str, Listing]:
    """Every Spotify album the library has songs from, with those songs. Its name is the one Spotify showed, since a
    filed song's album field holds MusicBrainz's name."""
    played = {r[0]: r[1] for r in store.conn.execute(
        "SELECT source_uri, album FROM takes WHERE verdict='keep' AND source_uri IS NOT NULL AND album IS NOT NULL "
        "ORDER BY id")}
    out: dict[str, Listing] = {}
    for r in store.conn.execute("SELECT * FROM tracks WHERE state='library' ORDER BY id"):
        try:
            meta = json.loads(r["meta_json"] or "{}")
        except ValueError:
            continue
        uri = meta.get("album_uri") or ""
        info = (meta.get("extra") or {}).get("album_info") or {}
        total = _int(info.get("total_tracks"))
        if not uri.startswith("spotify:album:") or not total:
            continue
        ls = out.get(uri)
        if ls is None:
            name = meta.get("played_album") or played.get(r["source_uri"]) or r["album"] or ""
            ls = out[uri] = Listing(uri, name, [a for a in info.get("artists") or [] if a],
                                    (info.get("album_type") or "").lower(), total, info.get("release_date") or "")
        ls.songs.append(_song(r, meta))
    return out


def _same_album(a: Listing, b: Listing) -> bool:
    x = {n.casefold() for n in a.artists}
    y = {n.casefold() for n in b.artists}
    if x & (y - {VARIOUS}):
        return True
    # one label lists a soundtrack under Various Artists and another under its composers, with the same songs
    return a.total == b.total and (VARIOUS in x or VARIOUS in y or not x or not y)


def groups(found: dict[str, Listing]) -> list[list[Listing]]:
    """The listings of each album: the same name once edition words are left out, and an album artist in common."""
    by_key: dict[str, list[Listing]] = {}
    for ls in found.values():
        if ls.kind in KINDS:
            by_key.setdefault(edition_key(ls.name) or ls.uri, []).append(ls)
    out: list[list[Listing]] = []
    for same in by_key.values():
        parts: list[list[Listing]] = []
        for ls in same:
            joined = [p for p in parts if any(_same_album(ls, o) for o in p)]
            parts = [p for p in parts if all(p is not j for j in joined)] + [[ls] + [o for p in joined for o in p]]
        out.extend(parts)
    return out


def counted(group: list[Listing]) -> Listing:
    """The listing an album is counted against: the one with the fewest songs, so a deluxe edition's extra songs never
    count as missing. Of two listings that size, the one you have more songs from."""
    return min(group, key=lambda ls: (ls.total, -len(ls.songs), ls.date or "9999", ls.uri))


# -- albums and their counts -----------------------------------------------------------------

@dataclass
class Album:
    uri: str                            # the listing it's counted against
    name: str
    artists: list[str]
    kind: str                           # album, ep or compilation
    total: int                          # the songs that edition has
    date: str
    listings: list[str]                 # every listing of it you have songs from
    songs: list[dict]                   # your songs from those listings
    wanted: int | None = None           # 1 you added it to the Wanted list, 0 you took it off, None its count decides
    tracks: list[dict] | None = None    # its songs as Spotify lists them, once read
    held: list[dict | None] = field(default_factory=list)   # your copy of each of those songs, or None
    have: int = 0                       # how many of its songs you have
    yours: int = 0                      # how many of your songs come from it, through any listing or release
    bonus: int = 0                      # your songs from a bigger edition that this one doesn't have
    unplayable: int = 0                 # songs you don't have that Spotify can't play where you are

    @property
    def artist(self) -> str:
        return ", ".join(self.artists)

    @property
    def year(self) -> int:
        return _int((self.date or "")[:4])

    @property
    def missing(self) -> int:
        return max(0, self.total - self.have)

    @property
    def to_record(self) -> int:
        """The missing songs Spotify can play."""
        return max(0, self.missing - self.unplayable)

    @property
    def whole(self) -> bool:
        return self.have >= self.total


def _copy(row) -> dict:
    return {k: row[k] for k in ("id", "artist", "title", "file_path", "quality_tier", "source_uri")}


def count(store: Store, album: Album, main: Listing) -> None:
    """How many of the album's songs you have. Without its songs from Spotify, that's the songs you recorded from the
    listing it's counted against, one per place on the album."""
    mine = {s["id"] for s in album.songs}
    album.held, album.unplayable = [], 0
    if album.tracks:
        album.total = len(album.tracks)
        used = set()
        for t in album.tracks:
            row = playlists.match(store, t)
            album.held.append(_copy(row) if row is not None else None)
            if row is not None:
                used.add(int(row["id"]))
            elif not playlists.wanted(t):
                album.unplayable += 1
        album.have = sum(1 for h in album.held if h is not None)
    else:
        places = {(s["disc_number"], s["track_number"] or s["source_uri"]) for s in main.songs}
        album.have = min(len(places), album.total)
        used = {s["id"] for s in main.songs}
    album.bonus = len(mine - used)
    album.yours = len(mine | used)


def build(store: Store) -> list[Album]:
    """Every album the library has songs from, counted, by artist and name."""
    saved = store.album_rows()
    out = []
    for group in groups(listings(store)):
        main = counted(group)
        decided = [saved[ls.uri] for ls in group if ls.uri in saved and saved[ls.uri]["wanted"] is not None]
        latest = max(decided, key=lambda r: r["wanted_at"] or "") if decided else None
        tracks = None
        if main.uri in saved and saved[main.uri]["tracks_json"]:
            try:
                tracks = json.loads(saved[main.uri]["tracks_json"]) or None
            except ValueError:
                tracks = None
        others = [ls for ls in group if ls is not main]
        album = Album(main.uri, main.name, main.artists, main.kind, main.total, main.date,
                      [main.uri] + [ls.uri for ls in others], [s for ls in [main] + others for s in ls.songs],
                      wanted=None if latest is None else int(latest["wanted"]), tracks=tracks)
        count(store, album, main)
        out.append(album)
    out.sort(key=lambda a: (a.artist.casefold(), a.name.casefold(), a.uri))
    return out


def find(albums: list[Album], uri: str) -> Album | None:
    """The album a Spotify album id belongs to, through any of its listings."""
    return next((a for a in albums if uri in a.listings), None)


# -- the Wanted list -------------------------------------------------------------------------

def on_wanted_list(album: Album, min_songs: int) -> bool:
    """An album you don't have whole is on the Wanted list when you added it, or when you have `min_songs` of its songs
    and haven't taken it off. With `min_songs` 0, only the albums you add are."""
    if album.whole or album.wanted == 0:
        return False
    return album.wanted == 1 or (min_songs > 0 and album.yours >= min_songs)


def wanted_list(albums: list[Album], min_songs: int) -> list[Album]:
    """The Wanted list, nearest to whole first: the fewest songs left to record, then the biggest share you have.
    Albums whose missing songs Spotify can't play where you are come last."""
    picked = [a for a in albums if on_wanted_list(a, min_songs)]
    return sorted(picked, key=lambda a: (a.to_record == 0, a.to_record, -a.have / max(1, a.total),
                                         a.name.casefold()))


def average_song_ms(store: Store) -> int:
    v = store.conn.execute("SELECT AVG(duration_ms) FROM tracks WHERE state='library' AND duration_ms > 0").fetchone()
    return int(v[0] or 225_000)


def minutes_to_record(album: Album, average_ms: int) -> int:
    """About how long Spotify takes to play the album's missing songs once. Until its songs are read from Spotify,
    each missing song counts as one of your average length."""
    if album.tracks:
        ms = sum(_int(t.get("duration_ms")) or average_ms for t, h in zip(album.tracks, album.held)
                 if h is None and playlists.wanted(t))
    else:
        ms = album.missing * average_ms
    return max(1, round(ms / 60000)) if ms else 0
