# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Spotify playlists as M3U8 files of the songs in your library.

Each playlist you record or save gets a file in the library's Playlists folder, so the USB export copies it with
the songs. Each line is the song's path relative to that folder (../Soundtracks/Leo (2023)/Ratata.m4a), so the
playlist plays wherever the library goes. A Spotify song is matched to its file by its Spotify id, then by the ids
of its other releases (aliases), then by artist, title and length. Songs the library doesn't have yet stay in the
file as comment lines, in the playlist's order. The playlist's songs are kept in the index, and the files are
written again from it whenever songs are filed or moved, so no line points at an old path.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path

from .library import safe
from .store import Store

log = logging.getLogger("mynaphone.playlists")

FOLDER = "Playlists"


def artist_text(track: dict) -> str:
    return ", ".join(a for a in track.get("artists") or [] if a)


def match(store: Store, track: dict):
    """The library's copy of a playlist song, or None. Inbox songs count as not there yet."""
    row = store.find_archived(artist_text(track), track.get("name", ""), int(track.get("duration_ms") or 0),
                              track.get("uri") or None)
    if row is None or row["state"] != "library" or not row["file_path"]:
        return None
    return row


def wanted(track: dict) -> bool:
    """A song Spotify can play: not an episode, a local file or a song unavailable here."""
    return bool(track.get("uri", "").startswith("spotify:track:") and track.get("playable", True)
                and not track.get("local") and not track.get("episode"))


def summary(store: Store, tracks: list[dict]) -> dict:
    """How much of a playlist the library holds: totals, and the playlist positions still to record."""
    have, todo, unplayable = [], [], []
    for t in tracks:
        if match(store, t) is not None:
            have.append(t["index"])
        elif wanted(t):
            todo.append(t["index"])
        else:
            unplayable.append(t["index"])
    return {"total": len(tracks), "have": have, "todo": todo, "unplayable": unplayable}


def write(store: Store, library_dir: Path, name: str, tracks: list[dict]) -> tuple[Path, int, int]:
    """Write one playlist's M3U8. Returns its path, the songs it lists, and the songs still missing."""
    folder = library_dir / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{safe(name) or 'Playlist'}.m3u8"
    lines = ["#EXTM3U", f"#PLAYLIST:{name}"]
    listed = missing = 0
    for t in tracks:
        label = f"{artist_text(t)} - {t.get('name', '')}"
        row = match(store, t)
        if row is not None and Path(row["file_path"]).exists():
            rel = Path(os.path.relpath(row["file_path"], folder)).as_posix()
            lines += [f"#EXTINF:{round((t.get('duration_ms') or 0) / 1000)},{label}", rel]
            listed += 1
        else:
            lines.append(f"# not in your library yet: {label}")
            missing += 1
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    return path, listed, missing


def save(store: Store, library_dir: Path, uri: str, name: str, tracks: list[dict]) -> tuple[Path, int, int]:
    """Keep a playlist's songs in the index and write its M3U8."""
    path, listed, missing = write(store, library_dir, name, tracks)
    store.conn.execute(
        "INSERT OR REPLACE INTO playlists (uri, name, tracks_json, file, updated_at) VALUES (?, ?, ?, ?, ?)",
        (uri, name, json.dumps(tracks, ensure_ascii=False), str(path), dt.datetime.now(dt.timezone.utc).isoformat()))
    store.conn.commit()
    log.info("wrote %s: %d songs, %d not in the library yet", path.name, listed, missing)
    return path, listed, missing


def rewrite_all(store: Store, library_dir: Path) -> int:
    """Write every saved playlist again from the index, after songs were filed or moved."""
    n = 0
    for r in store.conn.execute("SELECT uri, name, tracks_json, file FROM playlists").fetchall():
        try:
            tracks = json.loads(r["tracks_json"] or "[]")
        except ValueError:
            continue
        path, _, _ = write(store, library_dir, r["name"] or "Playlist", tracks)
        if r["file"] and r["file"] != str(path):
            try:
                Path(r["file"]).unlink(missing_ok=True)         # the playlist was renamed in Spotify
            except OSError:
                pass
            store.conn.execute("UPDATE playlists SET file=? WHERE uri=?", (str(path), r["uri"]))
            store.conn.commit()
        n += 1
    return n
