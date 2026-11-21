# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""One folder per film under Soundtracks.

A film's songs used to scatter: each "(From "Leo")" single got its own folder, a second spelling of the album
name ("Aavesham" and "Aavesham (Original Motion Picture Soundtrack)") made a second folder, and a single released
the year before its album ("Hukum Reloaded", 2025, from Jailer 2, 2026) a folder of its own year. On October 30, 10
films were spread over 24 folders. Here every soundtrack song gets a film key: the film's name, the language when the
album's name gives one (a dubbed album such as "Vettaiyan (telugu)" stays apart), and whether the album is a
background score (it stays apart from the songs). Songs with the same key, released within a few years of each other,
share one folder.

A folder's songs also share one album artist. Songs matched to 2 MusicBrainz releases of a film carried both releases'
credits, so a player that groups by album artist showed the film twice: on November 20, 9 film folders did, among them
Aashiq Banaya Aapne with "Himesh Reshammiya & Sameer" and "Himesh Reshammiya", and Zeher with its composers and
"Various Artists". The album artist they share is the names every song's credit has, which is usually the music
director (shared_album_artist).

They share one album name as well. A single kept its own, such as "Ratata (From “Leo”)", and MusicBrainz and Spotify
spell an album differently, so a player that groups by album name showed 11 films more than once on November 20. The
name they share is the album's own, spelled the way most of its songs spell it (shared_album), and a single joining
it is numbered after the album's songs (film_tags). Each song keeps its own album and track number in the index,
since they file it and look it up, and its tags carry its film's (tagged_as).
"""
from __future__ import annotations

import collections
import dataclasses
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .store import norm

log = logging.getLogger("mynaphone.films")

YEARS_APART = 3                 # a film's singles, album and reissues fall within this many years; remakes don't
LANGUAGES = ("tamil", "telugu", "hindi", "malayalam", "kannada", "bengali", "marathi", "punjabi")
_FROM = re.compile(r"\(\s*from\s+[\"“”'‘’]?(.+?)[\"“”'‘’]?\s*\)", re.I)
_SCORE = re.compile(r"\b(score|bgm)\b", re.I)
_QUALIFIER = re.compile(
    # "(Original Motion Picture Soundtrack)", then a trailing "Original Background Score" as in Master's
    r"\s*[\(\[][^\)\]]*\b(sound\s*track|score|ost|bgm)\b[^\)\]]*[\)\]]"
    r"|\s*[:\-–]?\s*\b(original\s+)?(motion\s+picture\s+|film\s+|movie\s+|background\s+)*"
    r"(sound\s*track|score|ost|bgm)\s*$", re.I)
_LANGUAGE = re.compile(r"[\(\[]\s*(" + "|".join(LANGUAGES) + r")(\s+version)?\s*[\)\]]"
                       r"|[\-–]\s*(" + "|".join(LANGUAGES) + r")(\s+version)?\s*$", re.I)


@dataclass(frozen=True)
class Film:
    key: tuple[str, str, bool]      # (normalized name, language from the album's name, background score)
    name: str                       # the film's name as written, for a folder made from singles alone
    single: bool                    # a "(From X)" single rather than the film's own album


def film_of(album: str, title: str = "") -> Film | None:
    """The film a soundtrack song belongs to, read from its album, or from a "(From X)" in its album or title."""
    album = album or ""
    m = _FROM.search(album) or _FROM.search(title or "")
    if m:
        name = m.group(1).strip()
        return Film((norm(name), "", False), name, True)
    lang = _LANGUAGE.search(album)
    language = (lang.group(1) or lang.group(3) or "").lower() if lang else ""
    score = bool(_SCORE.search(album))
    name = _LANGUAGE.sub("", album)
    for _ in range(3):                  # "The Greatest Of All Time Ost (Original Motion Picture Soundtrack)"
        name = _QUALIFIER.sub("", name).strip(" -–:")
    if not norm(name):
        return None
    return Film((norm(name), language, score), name, False)


@dataclass
class Folder:
    rel: Path                       # under the library, Soundtracks/<folder>
    film: Film
    year: int
    songs: int = 0
    singles_only: bool = True       # every song in it is a "(From X)" single: the film's album isn't here


def folder_year(rel: Path) -> int:
    m = re.search(r"\((\d{4})\)\s*$", rel.name)
    return int(m.group(1)) if m else 0


def choose(folders: list[Folder]) -> Folder:
    """The folder a film's songs gather in: the film's own album's, then the earliest year (reissues come later),
    then the one holding the most songs, then the shortest name."""
    return min(folders, key=lambda f: (f.singles_only, f.year or 9999, -f.songs, len(f.rel.name)))


def groups(folders: list[Folder]) -> list[list[Folder]]:
    """Folders of one film: the same key, each within YEARS_APART of the group's earliest."""
    by_key: dict[tuple, list[Folder]] = {}
    for f in folders:
        by_key.setdefault(f.film.key, []).append(f)
    out = []
    for same in by_key.values():
        same.sort(key=lambda f: f.year or 9999)
        current: list[Folder] = []
        for f in same:
            if current and f.year and current[0].year and f.year - current[0].year > YEARS_APART:
                out.append(current)
                current = []
            current.append(f)
        out.append(current)
    return [g for g in out if len(g) > 1]


@dataclass
class Move:
    track_id: int
    src: Path
    dst: Path


def film_folder(library_dir: Path, file_path) -> Path | None:
    """The `Soundtracks/<folder>` a file is in, under the library, or None for a file anywhere else."""
    try:
        rel = Path(file_path or "").parent.relative_to(library_dir)
    except ValueError:
        return None
    return rel if rel.parent == Path("Soundtracks") else None


def plan(library_dir: Path, rows) -> list[Move]:
    """Moves that put each film's songs in one folder. `rows` are library rows of songs under Soundtracks."""
    folders: dict[Path, Folder] = {}
    members: dict[Path, list] = {}
    for r in rows:
        rel = film_folder(library_dir, r["file_path"])
        if rel is None:
            continue
        try:
            ident = json.loads(r["identity_json"] or "{}")
        except ValueError:
            ident = {}
        film = film_of(ident.get("album") or r["album"] or "", ident.get("title") or r["title"] or "")
        if film is None:
            continue
        if rel not in folders:
            folders[rel] = Folder(rel, film, folder_year(rel))
            members[rel] = []
        folders[rel].songs += 1
        folders[rel].singles_only = folders[rel].singles_only and film.single
        members[rel].append((r, film))
    moves = []
    for group in groups(list(folders.values())):
        main = choose(group)
        target = main.rel
        if main.singles_only:
            # only singles so far: they gather under the film's own name and the earliest year
            year = min((f.year for f in group if f.year), default=0)
            target = Path("Soundtracks") / (_safe(main.film.name) + (f" ({year})" if year else ""))
        here = library_dir / target
        taken = {p.name.lower() for p in here.glob("*")} if here.exists() else set()
        for f in group:
            if f.rel == target:
                continue
            for r, film in members[f.rel]:
                src = Path(r["file_path"])
                name = src.name
                if film.single:
                    name = re.sub(r"^\d+(-\d+)?\s+", "", name)       # its "01" means nothing in the film's folder
                stem, ext = Path(name).stem, Path(name).suffix
                n = 2
                while name.lower() in taken:
                    name = f"{stem} ({n}){ext}"
                    n += 1
                taken.add(name.lower())
                moves.append(Move(int(r["id"]), src, library_dir / target / name))
    return moves


def soundtrack_rows(store):
    """Library rows of the songs under Soundtracks, as plan(), folder_for() and the album artist rule take them."""
    return store.conn.execute(
        "SELECT id, file_path, artist, album, album_artist, title, identity_json, manual_json FROM tracks "
        "WHERE state='library' AND file_path LIKE ?", (f"%{os.sep}Soundtracks{os.sep}%",)).fetchall()


def in_folder(placement, ident, into: Path):
    """`placement` moved into `into`, the folder that already holds the song's film. A "(From X)" single drops the
    "01" it had as the only song of its own release."""
    if into == placement.rel_dir:
        return placement
    film = film_of(ident.release_album or ident.album, ident.title)
    name = re.sub(r"^\d+(-\d+)?\s+", "", placement.filename) if film and film.single else placement.filename
    return type(placement)(placement.kind, into, name)


def _safe(s: str) -> str:
    from .library import safe
    return safe(s)


def apply(store, moves: list[Move], record: Path | None = None) -> int:
    """Move each song with its lyrics file, point its row at the new path, and remove the folders left empty.
    The moves are appended to `record`, a JSON list of [from, to] pairs, so they can be undone by hand."""
    done = []
    for mv in moves:
        if not mv.src.exists() or mv.dst.exists():
            log.warning("didn't move %s to %s: %s", mv.src.name, mv.dst.parent.name,
                        "it's gone" if not mv.src.exists() else "a file of that name is there")
            continue
        mv.dst.parent.mkdir(parents=True, exist_ok=True)
        mv.src.rename(mv.dst)
        lrc = mv.src.with_suffix(".lrc")
        if lrc.exists():
            lrc.rename(mv.dst.with_suffix(".lrc"))
        store.conn.execute("UPDATE tracks SET file_path=? WHERE id=?", (str(mv.dst), mv.track_id))
        store.conn.commit()
        done.append([str(mv.src), str(mv.dst)])
        log.info("moved %s into %s", mv.src.name, mv.dst.parent.name)
        try:
            parent = mv.src.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass
    if done and record is not None:
        append_record(record, done)
    return len(done)


def append_record(record: Path, entries: list) -> None:
    """Add `entries` to the JSON list in `record`, which keeps each change a job made so it can be undone by hand."""
    try:
        old = json.loads(record.read_text(encoding="utf-8")) if record.exists() else []
    except ValueError:
        old = []
    record.write_text(json.dumps(old + entries, ensure_ascii=False, indent=1), encoding="utf-8")


def folder_for(library_dir: Path, rows, album: str, title: str, year: int) -> Path | None:
    """The folder that already holds this film's songs, for a new song from it, or None. `rows` are library rows
    under Soundtracks."""
    film = film_of(album, title)
    if film is None:
        return None
    found: dict[Path, Folder] = {}
    for r in rows:
        rel = film_folder(library_dir, r["file_path"])
        if rel is None:
            continue
        try:
            ident = json.loads(r["identity_json"] or "{}")
        except ValueError:
            ident = {}
        other = film_of(ident.get("album") or r["album"] or "", ident.get("title") or r["title"] or "")
        if other is None or other.key != film.key:
            continue
        y = folder_year(rel)
        if year and y and abs(y - year) > YEARS_APART:
            continue
        f = found.setdefault(rel, Folder(rel, other, y))
        f.songs += 1
        f.singles_only = f.singles_only and other.single
    return choose(list(found.values())).rel if found else None


# -- one album artist per film ---------------------------------------------------------------

VARIOUS = ("various artists", "various")


@dataclass
class Credit:
    """One song's say in the album artist its film's songs share."""
    credit: str                 # the album artist its own release credits
    counts: bool = True         # False when that only repeats the song's own artist
    typed: str = ""             # an album artist typed in the Library editor
    sort: str = ""              # the sort name and MusicBrainz ids its tags carry with its album artist
    ids: tuple[str, ...] = ()
    own: bool = True            # its tags carry its own credit, so its sort name and ids are that credit's


@dataclass(frozen=True)
class AlbumArtist:
    """A film's album artist, with the sort name and MusicBrainz ids that go with it in the tags."""
    name: str
    sort: str = ""
    ids: tuple[str, ...] = ()


def _key(name: str) -> str:
    """Spellings of one name match: "Jatin‐Lalit" and "Jatin-Lalit", "Kalyanji Anandji" and "Kalyanji - Anandji"."""
    return norm(name) or name.casefold().strip()


def _names(credit: str) -> list[str]:
    """The people in a credit, as written: "Himesh Reshammiya & Sameer" is two."""
    from .identify import _names_list
    return _names_list(credit) or ([credit.strip()] if credit.strip() else [])


def _keys(credit: str) -> frozenset[str]:
    return frozenset(_key(n) for n in _names(credit))


def _counts(credit: str, artist: str, source: str) -> bool:
    """Whether a song's album artist tells anything about its album. A song filed from the player's tags gets its own
    artist as album artist: DC's Ain't Nobody had Anirudh Ravichander, where the 14 songs MusicBrainz knew had the
    album's 4 names."""
    return source == "acoustid" or _key(credit) != _key(artist)


def credit_of(row) -> Credit:
    """A library row's say in its film's album artist. `row` is one of soundtrack_rows()."""
    try:
        ident = json.loads(row["identity_json"] or "{}")
    except ValueError:
        ident = {}
    try:
        typed = str((json.loads(row["manual_json"] or "{}") or {}).get("album_artist") or "")
    except (ValueError, AttributeError):
        typed = ""
    now = row["album_artist"] or ident.get("album_artist") or ""
    credit = ident.get("album_credit") or now
    artist = row["artist"] or ident.get("artist") or ""
    return Credit(credit, _counts(credit, artist, ident.get("source") or ""), typed,
                  ident.get("album_artist_sort") or "", tuple(ident.get("mb_album_artist_ids") or ()),
                  not typed and _keys(now) == _keys(credit))


def credit_from(ident) -> Credit:
    """A song's say in its film's album artist, read from its identity while it's filed or refreshed."""
    credit = ident.album_credit or ident.album_artist
    return Credit(credit, _counts(credit, ident.artist, ident.source), "", ident.album_artist_sort,
                  tuple(ident.mb_album_artist_ids), _keys(ident.album_artist) == _keys(credit))


def tagged(row) -> AlbumArtist:
    """The album artist a library row's tags carry now, with its sort name and MusicBrainz ids."""
    try:
        ident = json.loads(row["identity_json"] or "{}")
    except ValueError:
        ident = {}
    return AlbumArtist(row["album_artist"] or "", ident.get("album_artist_sort") or "",
                       tuple(ident.get("mb_album_artist_ids") or ()))


def _ranked(values: list[str]) -> list[str]:
    """Each credit once, the one most songs have first, then the shorter. Spellings of the same names count together,
    under the spelling most of them use."""
    groups: dict[frozenset, list[str]] = {}
    for v in values:
        groups.setdefault(_keys(v), []).append(v)
    best = [(len(vs), min(set(vs), key=lambda s: (-vs.count(s), len(s), s))) for vs in groups.values()]
    return [s for _, s in sorted(best, key=lambda b: (-b[0], len(b[1]), b[1]))]


def shared_album_artist(credits: list[Credit]) -> str:
    """The one album artist a film's songs share: the names every song's credit has, which is usually the music
    director. Aashiq Banaya Aapne's "Himesh Reshammiya & Sameer" and "Himesh Reshammiya" give "Himesh Reshammiya",
    spelled the way most of the songs spell it. When no name is in every credit, the names in the most credits count,
    so one odd credit can't take a film over. An album artist typed in the Library editor wins. "Various Artists"
    counts only when no song names people, and a credit that only repeats a song's own artist only when no other song
    has a credit. Empty when no song has an album artist."""
    typed = [c.typed for c in credits if c.typed.strip()]
    if typed:
        return _ranked(typed)[0]
    pool = ([c.credit for c in credits if c.credit.strip() and c.counts]
            or [c.credit for c in credits if c.credit.strip()])
    named = [v for v in pool if v.strip().casefold() not in VARIOUS] or pool
    if not named:
        return ""
    ranked = _ranked(named)
    held = collections.Counter(k for v in named for k in _keys(v))
    most = max(held.values())
    core = frozenset(k for k, n in held.items() if n == most)
    whole = [v for v in ranked if core <= _keys(v)]
    if not whole:
        return ranked[0]        # those names are in different credits: the credit most songs have, the shorter on a tie
    for v in whole:
        if _keys(v) == core:
            return v
    # no song has just those names: write them out, in the order the leading credit gives them
    names: list[str] = []
    for n in _names(whole[0]):
        if _key(n) in core and _key(n) not in {_key(m) for m in names}:
            names.append(n)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " & " + names[-1]


def film_album_artist(credits: list[Credit]) -> AlbumArtist | None:
    """The album artist a film's songs share (shared_album_artist), with the sort name and MusicBrainz ids that most
    of the songs credited with those names carry, so a player that sorts by the sort name keeps the film together too.
    A name no song's own release gives, such as one typed in the Library editor, goes without them. None when no song
    has an album artist."""
    name = shared_album_artist(credits)
    if not name:
        return None
    pairs = [(c.sort, c.ids) for c in credits if c.own and (c.sort or c.ids) and _keys(c.credit) == _keys(name)]
    sort, ids = collections.Counter(pairs).most_common(1)[0][0] if pairs else ("", ())
    return AlbumArtist(name, sort, ids)


@dataclass
class Retag:
    track_id: int
    path: Path
    old: AlbumArtist
    new: AlbumArtist


def album_artist_plan(library_dir: Path, rows) -> list[Retag]:
    """Songs whose tags carry another album artist, sort name or MusicBrainz ids than their film's folder shares. A
    typed album artist never changes. `rows` are soundtrack_rows()."""
    folders: dict[Path, list] = {}
    for r in rows:
        rel = film_folder(library_dir, r["file_path"])
        if rel is not None:
            folders.setdefault(rel, []).append(r)
    out = []
    for rs in folders.values():
        if len(rs) < 2:
            continue
        credits = [credit_of(r) for r in rs]
        want = film_album_artist(credits)
        if want is None:
            continue
        for r, c in zip(rs, credits):
            have = tagged(r)
            if not c.typed and have != want:
                out.append(Retag(int(r["id"]), Path(r["file_path"]), have, want))
    return out


def album_artist_for(library_dir: Path, rows, folder: Path, own: Credit,
                     exclude: int | None = None) -> AlbumArtist | None:
    """The album artist a song gets in `folder` (`Soundtracks/<folder>`), worked out with its own credit among those of
    the folder's songs: a Leo single credited to "Anirudh Ravichander & Nikhita Gandhi" gets "Anirudh Ravichander".
    `exclude` is the song's own row. None when no other song is in the folder."""
    peers = [credit_of(r) for r in rows
             if film_folder(library_dir, r["file_path"]) == folder and int(r["id"]) != exclude]
    return film_album_artist(peers + [own]) if peers else None


def take_album_artist(ident, film: AlbumArtist | None) -> None:
    """The song takes its film's album artist, sort name and MusicBrainz ids. The credit its own release gives stays
    in album_credit, so the song keeps its say when the film's album artist is worked out again."""
    if film is None:
        return
    if film.name != ident.album_artist:
        ident.album_credit = ident.album_credit or ident.album_artist
        ident.album_artist = film.name
    ident.album_artist_sort = film.sort
    ident.mb_album_artist_ids = list(film.ids)


# -- one album name per film -----------------------------------------------------------------

@dataclass
class Song:
    """One song's say in the album name its film's songs share, and in where the film's singles go."""
    id: int
    album: str                  # its album: its own release's, or one typed in the Library editor
    release: str                # its own release's album, which says whether it's a single
    title: str = ""
    date: str = ""              # its release's date, which puts the film's singles in order
    track: tuple[int, int, int, int] = (0, 0, 0, 0)     # its own track, tracks, disc and discs
    typed: bool = False         # its album was typed in the Library editor
    typed_track: bool = False   # so was its track number

    @property
    def film(self) -> Film | None:
        return film_of(self.release or self.album, self.title)

    @property
    def single(self) -> bool:
        film = self.film
        return bool(film and film.single)


@dataclass(frozen=True)
class FilmTags:
    """What a song in a film's folder carries in its tags: the album name the film's songs share and, for a single
    numbered after the film's album, its place there."""
    album: str
    track: tuple[int, ...] = ()         # track, tracks, disc and discs; empty to keep its own


def _json(text) -> dict:
    try:
        value = json.loads(text or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def song_of(row) -> Song:
    """A library row's say in its film's album name. `row` is one of soundtrack_rows()."""
    ident, typed = _json(row["identity_json"]), _json(row["manual_json"])
    album = ident.get("album") if "album" in ident else row["album"]
    return Song(int(row["id"]), album or "", ident.get("release_album") or album or "", ident.get("title") or "",
                ident.get("date") or str(ident.get("year") or ""),
                tuple(_int(ident.get(k)) for k in ("track_number", "track_total", "disc_number", "disc_total")),
                bool(str(typed.get("album") or "").strip()), bool(typed.get("track_number")))


def song_from(ident, typed: dict | None = None, track_id: int = -1) -> Song:
    """A song's say in its film's album name, read from its identity while it's filed or refreshed. `typed` is what
    was typed for it in the Library editor."""
    typed = typed or {}
    return Song(track_id, ident.album, ident.release_album or ident.album, ident.title,
                ident.date or str(ident.year or ""),
                (ident.track_number, ident.track_total, ident.disc_number, ident.disc_total),
                bool(str(typed.get("album") or "").strip()), bool(typed.get("track_number")))


def _most(values: list[str]) -> str:
    """The value most of them have, the shorter on a tie."""
    counts = collections.Counter(values)
    return min(counts, key=lambda v: (-counts[v], len(v), v)) if counts else ""


def shared_album(songs: list[Song]) -> str:
    """The album name a film's songs share: the album's own name, spelled the way most of its songs spell it, so Leo's
    singles take "Leo" from its 7 album songs, and Aavesham's 2 songs filed as "Aavesham (Original Motion Picture
    Soundtrack)" take the "Aavesham" of its other 5. A tie goes to the shorter spelling. A film with only singles takes
    the film's name from their "(From X)", and songs that already share a name keep it. An album typed in the Library
    editor wins. Empty when no song has an album."""
    typed = [s.album for s in songs if s.typed and s.album.strip()]
    if typed:
        return _most(typed)
    names = [s.album for s in songs if s.album.strip()]
    if len(set(names)) <= 1:
        return names[0] if names else ""
    albums = [s.album for s in songs if s.album.strip() and not s.single]
    if albums:
        return _most(albums)
    return _most([s.film.name for s in songs if s.film]) or _most(names)


def film_tags(songs: list[Song]) -> dict[int, FilmTags]:
    """What each song of a film's folder carries in its tags, by track id: the album name the film's songs share, and
    for a single joining another release's songs, a track number after the album's own songs, in the order the singles
    came out. Leo's 4 singles, each track 1 of 1, become tracks 8 to 11 of 11 after the album's 7. A film with only
    singles numbers them from 1, and they move after the album once it arrives. A typed album or track number stays.
    Empty for a folder of one song."""
    if len(songs) < 2:
        return {}
    name = shared_album(songs)
    if not name:
        return {}
    numbered: dict[int, tuple[int, ...]] = {}
    if len({s.release or s.album for s in songs}) > 1:
        singles = sorted((s for s in songs if s.single and not s.typed_track),
                         key=lambda s: (s.date or "9999", s.title.casefold(), s.id))
        albums = [s for s in songs if not s.single]
        disc = max((s.track[2] for s in albums), default=0)
        discs = max((s.track[3] for s in albums), default=0)
        last = [s for s in albums if s.track[2] == disc]
        count = max([n for s in last for n in s.track[:2]], default=0)     # its count, or its last song's number
        for i, s in enumerate(singles, start=1):
            numbered[s.id] = (count + i, count + len(singles), *((disc, discs) if discs > 1 else s.track[2:]))
    return {s.id: FilmTags(s.album if s.typed else name, numbered.get(s.id, ())) for s in songs}


def film_tags_for(library_dir: Path, rows, folder: Path, own: Song) -> FilmTags | None:
    """What a song carries in its tags in `folder` (Soundtracks/<folder>), worked out with the folder's other songs.
    `own.id` is the song's own row, or -1 for a song being filed. None when no other song is in the folder."""
    peers = [song_of(r) for r in rows if film_folder(library_dir, r["file_path"]) == folder and int(r["id"]) != own.id]
    return film_tags(peers + [own]).get(own.id) if peers else None


def take_film_tags(ident, tags: FilmTags | None) -> None:
    """The song's tags carry its film's album name, and a single's its place after the film's album. Its own album and
    track number stay in its identity, since they file it and look it up. Outside a film's folder it carries its own."""
    own = (ident.track_number, ident.track_total, ident.disc_number, ident.disc_total)
    ident.film_album = tags.album if tags is not None and tags.album != ident.album else ""
    ident.film_track = list(tags.track) if tags is not None and tags.track and tuple(tags.track) != own else []


def tagged_as(ident):
    """A copy of the song's identity with what its tags carry: its film's album name and, for a single, its place
    after the film's album."""
    shown = dataclasses.replace(ident, album=ident.film_album or ident.album)
    if len(ident.film_track) == 4:
        shown.track_number, shown.track_total, shown.disc_number, shown.disc_total = ident.film_track
    return shown


def tagged_album(row) -> tuple:
    """The album, track, tracks, disc and discs a library row's tags carry now."""
    ident = _json(row["identity_json"])
    album = ident.get("film_album") or (ident.get("album") if "album" in ident else row["album"]) or ""
    track = ident.get("film_track") or []
    if len(track) != 4:
        track = [_int(ident.get(k)) for k in ("track_number", "track_total", "disc_number", "disc_total")]
    return (album, *(_int(n) for n in track))


@dataclass
class Retitle:
    track_id: int
    path: Path
    old: tuple                  # the album, track, tracks, disc and discs its tags carry
    new: tuple                  # and the ones its film's folder gives it


def album_plan(library_dir: Path, rows) -> list[Retitle]:
    """Songs whose tags carry another album name or track number than their film's folder gives them (film_tags), and
    songs left alone in a folder that still carry their film's. A typed album or track number never changes. `rows`
    are soundtrack_rows()."""
    folders: dict[Path, list] = {}
    for r in rows:
        rel = film_folder(library_dir, r["file_path"])
        if rel is not None:
            folders.setdefault(rel, []).append(r)
    out = []
    for rs in folders.values():
        songs = [song_of(r) for r in rs]
        tags = film_tags(songs)
        for r, s in zip(rs, songs):
            t = tags.get(s.id)
            want = (t.album if t else s.album, *(t.track if t and t.track else s.track))
            have = tagged_album(r)
            if want != have:
                out.append(Retitle(s.id, Path(r["file_path"]), have, want))
    return out
