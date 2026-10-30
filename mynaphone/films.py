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
"""
from __future__ import annotations

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


def plan(library_dir: Path, rows) -> list[Move]:
    """Moves that put each film's songs in one folder. `rows` are library rows of songs under Soundtracks."""
    folders: dict[Path, Folder] = {}
    members: dict[Path, list] = {}
    for r in rows:
        path = Path(r["file_path"] or "")
        try:
            rel = path.parent.relative_to(library_dir)
        except ValueError:
            continue
        if rel.parent != Path("Soundtracks"):
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
    """Library rows of the songs under Soundtracks, as plan() and folder_for() take them."""
    return store.conn.execute(
        "SELECT id, file_path, album, title, identity_json FROM tracks WHERE state='library' AND file_path LIKE ?",
        (f"%{os.sep}Soundtracks{os.sep}%",)).fetchall()


def in_folder(placement, ident, into: Path):
    """`placement` moved into `into`, the folder that already holds the song's film. A "(From X)" single drops the
    "01" it had as the only song of its own release."""
    if into == placement.rel_dir:
        return placement
    film = film_of(ident.album, ident.title)
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
        try:
            old = json.loads(record.read_text(encoding="utf-8")) if record.exists() else []
        except ValueError:
            old = []
        record.write_text(json.dumps(old + done, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(done)


def folder_for(library_dir: Path, rows, album: str, title: str, year: int) -> Path | None:
    """The folder that already holds this film's songs, for a new song from it, or None. `rows` are library rows
    under Soundtracks."""
    film = film_of(album, title)
    if film is None:
        return None
    found: dict[Path, Folder] = {}
    for r in rows:
        path = Path(r["file_path"] or "")
        try:
            rel = path.parent.relative_to(library_dir)
        except ValueError:
            continue
        if rel.parent != Path("Soundtracks"):
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
