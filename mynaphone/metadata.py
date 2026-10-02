# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Metadata completeness, manual overrides and the shared "refresh one song" routine.

Every library song carries: the identity we found (identity_json), the fields a person typed in
(manual_json, never overwritten by lookups) and the list of fields still missing (missing_json).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

from . import genres, identify, lyrics as lyr, tools
from .config import Config
from .identify import Identity
from .library import classify, place, resolve_cover, tag, write_lyrics_sidecar
from .store import Store

log = logging.getLogger("mynaphone.metadata")

# field key -> label shown to people. Order = importance.
FIELDS = [
    ("title", "Title"), ("artist", "Artist"), ("album", "Album"), ("album_artist", "Album artist"),
    ("year", "Year"), ("track_number", "Track number"), ("track_total", "Track count"),
    ("disc_number", "Disc number"), ("cover", "Cover art"), ("lyrics", "Lyrics"), ("synced_lyrics", "Synced lyrics"),
    ("composers", "Composer"), ("lyricists", "Lyricist"), ("genres", "Genre"), ("isrc", "ISRC"),
    ("label", "Label"), ("mb_recording_id", "MusicBrainz id"),
]
LABELS = dict(FIELDS)

# fields a person can edit; the rest are lookup-only
EDITABLE = ["title", "artist", "album", "album_artist", "year", "track_number", "track_total",
            "disc_number", "disc_total", "composers", "lyricists", "genres", "isrc", "label", "kind"]
LIST_FIELDS = {"composers", "lyricists", "genres", "artists"}


def missing_fields(ident: Identity, has_cover: bool, lyrics_state: str) -> list[str]:
    miss = []
    for key, _ in FIELDS:
        if key == "cover":
            ok = has_cover
        elif key == "lyrics":
            ok = lyrics_state in ("plain", "synced", "instrumental")
        elif key == "synced_lyrics":
            ok = lyrics_state in ("synced", "instrumental")
        elif key == "year":
            ok = bool(ident.year)
        elif key == "lyricists" and lyrics_state == "instrumental":
            ok = True                     # no words, so no lyricist
        else:
            v = getattr(ident, key, None)
            ok = bool(v)
        if not ok:
            miss.append(key)
    return miss


def apply_manual(ident: Identity, manual: dict) -> None:
    for k, v in (manual or {}).items():
        if k == "kind":
            if v == "soundtrack" and not ident.is_soundtrack:
                ident.secondary_types.append("Soundtrack")
            elif v in ("album", "single") and ident.is_soundtrack:
                ident.secondary_types = [t for t in ident.secondary_types if t.lower() != "soundtrack"]
            if v == "single":
                ident.release_type = "single"
            elif v == "album" and ident.release_type == "single":
                ident.release_type = "album"
            continue
        if k in LIST_FIELDS:
            v = [x.strip() for x in str(v).split(";") if x.strip()] if isinstance(v, str) else list(v)
        elif k in ("year", "track_number", "track_total", "disc_number", "disc_total"):
            try:
                v = int(v)
            except (TypeError, ValueError):
                continue
        if hasattr(ident, k):
            setattr(ident, k, v)
    if "year" in (manual or {}) and ident.year and not ident.date.startswith(str(ident.year)):
        ident.date = str(ident.year)


def identity_from_row(row) -> Identity:
    ident = Identity()
    try:
        d = json.loads(row["identity_json"] or "{}")
    except Exception:
        d = {}
    for k, v in d.items():
        if hasattr(ident, k):
            setattr(ident, k, v)
    ident.title = ident.title or (row["title"] or "")
    ident.artist = ident.artist or (row["artist"] or "")
    ident.album = ident.album or (row["album"] or "")
    ident.album_artist = ident.album_artist or (row["album_artist"] or "")
    ident.track_number = ident.track_number or int(row["track_number"] or 0)
    return ident


def read_file_extras(path: Path) -> tuple[tuple[bytes, str] | None, str]:
    """Cover and lyrics currently embedded in a library file."""
    try:
        from .library import read_extras
        return read_extras(path)
    except Exception as e:
        log.warning("could not read %s: %s", path.name, e)
        return None, ""


def lyrics_state_of(text: str) -> str:
    if not text:
        return "none"
    return "synced" if "[" in text[:12] else "plain"


def refresh_track(cfg: Config, store: Store, row, lookup: bool = True, manual: dict | None = None,
                  new_cover: tuple[bytes, str] | None = None, new_lyrics: str | None = None,
                  move: bool = True) -> dict:
    """Re-identify (optional), apply manual edits, re-tag, maybe move, and recompute what's missing.

    Returns a summary dict with 'missing', 'path'.
    """
    path = Path(row["file_path"] or "")
    if not path.exists():
        raise FileNotFoundError(path)
    ident = identity_from_row(row)
    manual_all = json.loads(row["manual_json"] or "{}") if "manual_json" in row.keys() else {}
    if manual:
        manual_all.update({k: v for k, v in manual.items() if v not in (None, "")})
        for k, v in list(manual.items()):
            if v in (None, ""):
                manual_all.pop(k, None)
    meta = json.loads(row["meta_json"] or "{}")
    meta.update({"source_uri": row["source_uri"] or "", "quality_tier": row["quality_tier"] or ""})

    note = ""
    if lookup:
        try:
            if not ident.mb_recording_id and cfg.identify.acoustid_key.strip() and tools.fpcalc():
                hints = dict(hint_album="" if identify.looks_like_count(ident.album) else ident.album,
                             hint_track=ident.track_number, hint_artist=ident.artist, hint_title=ident.title)
                found, note = identify.lookup_with_retry(cfg.identify.acoustid_key.strip(), str(path), hints)
                if found is not None:
                    ident = found
            src = row["source_uri"] or ""
            if (not ident.mb_recording_id and src.startswith("youtube:video:")
                    and ident.source in ("youtube", "tags", "none")):
                extra = meta.setdefault("extra", {})
                extra.setdefault("youtube", {}).setdefault("video_id", src.rsplit(":", 1)[-1])
                yt = identify.from_youtube(meta)
                if yt is not None and (yt.artist or yt.album):
                    ident = yt
                    note = note or "YouTube credits and catalogue"
            if ident.mb_recording_id or ident.mb_release_id:
                identify.enrich_from_musicbrainz(ident, cfg.identify.musicbrainz_contact)
            if not ident.is_soundtrack and identify.looks_like_soundtrack(ident.album, ident.title):
                ident.secondary_types.append("Soundtrack")
            identify.apply_spotify(ident, meta)
        except Exception as e:
            note = f"lookup failed: {e}"
            log.info("refresh lookup failed for %s: %s", path.name, e)
        genres.resolve(ident, row["artist"] or "", (row["duration_ms"] or 0) / 1000.0, cfg)
    # never let a YouTube view count stand as an album, whatever an older capture stored
    if identify.looks_like_count(ident.album):
        ident.album = ""
        ident.release_type = ident.release_type or "single"
    apply_manual(ident, manual_all)

    cover, lyrics_text = read_file_extras(path)
    if new_cover:
        cover = new_cover
    if cover is None and lookup:
        cover = resolve_cover(path, ident, meta.get("cover_url") or "")
    instrumental = (identify.is_instrumental(ident.title, ident.album)
                    or ("lyrics_state" in row.keys() and row["lyrics_state"] == "instrumental"))
    if new_lyrics is not None:
        lyrics_text = new_lyrics
    elif lookup and not instrumental and lyrics_state_of(lyrics_text) != "synced":
        try:
            got = lyr.fetch(ident.title, ident.artist, ident.album, (row["duration_ms"] or 0) / 1000.0)
            if got and got.best and (got.synced or not lyrics_text):
                lyrics_text = got.best
        except Exception:
            pass
    lyr_state = lyrics_state_of(lyrics_text)
    if lyr_state == "none" and instrumental:
        lyr_state = "instrumental"

    kind = manual_all.get("kind") or classify(ident)
    capture = {"source_app": row["source_app"] or "", "source_uri": row["source_uri"] or "",
               "quality_tier": row["quality_tier"] or "", "captured_at": row["created_at"] or "", "kind": kind}
    tag(path, ident, cover, lyrics_text, capture)
    write_lyrics_sidecar(path, lyrics_text)
    if lyr_state != "synced":
        try:
            path.with_suffix(".lrc").unlink(missing_ok=True)
        except OSError:
            pass

    new_path = path
    if move:
        pl = place(ident)
        if manual_all.get("kind"):
            pl.kind = manual_all["kind"]
            pl = _place_with_kind(ident, manual_all["kind"])
        target = cfg.paths.library_dir / pl.rel_dir / f"{pl.filename}{path.suffix}"
        if target != path:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target.unlink()
            path.rename(target)
            lrc = path.with_suffix(".lrc")
            if lrc.exists():
                lrc.rename(target.with_suffix(".lrc"))
            new_path = target
            _prune_empty(path.parent, cfg.paths.library_dir)

    missing = missing_fields(ident, cover is not None, lyr_state)
    store.conn.execute(
        "UPDATE tracks SET file_path=?, title=?, artist=?, album=?, album_artist=?, track_number=?, lyrics_state=?, "
        "identity_json=?, manual_json=?, missing_json=?, last_lookup=?, lookup_tries=COALESCE(lookup_tries,0)+? "
        "WHERE id=?",
        (str(new_path), ident.title, ident.artist, ident.album, ident.album_artist, ident.track_number, lyr_state,
         json.dumps(ident.to_json(), ensure_ascii=False), json.dumps(manual_all, ensure_ascii=False),
         json.dumps(missing), dt.datetime.now(dt.timezone.utc).isoformat() if lookup else row["last_lookup"],
         1 if lookup else 0, int(row["id"])))
    store.conn.commit()
    return {"missing": missing, "path": str(new_path), "note": note, "ident": ident}


def _place_with_kind(ident: Identity, kind: str):
    from .library import Placement, safe
    num = f"{ident.track_number:02d} " if ident.track_number else ""
    album = safe(ident.album)
    year = ident.year
    album_dir = f"{album} ({year})" if year and kind != "single" else album
    if kind == "unsorted" or (not ident.artist.strip() and not ident.album_artist.strip()):
        return Placement("unsorted", Path("Unsorted"), safe(ident.title))
    if kind == "soundtrack":
        return Placement(kind, Path("Soundtracks") / album_dir, f"{num}{safe(ident.title)}")
    if kind == "compilation":
        return Placement(kind, Path("Artists") / "Various Artists" / album_dir, f"{num}{safe(ident.title)}")
    artist_dir = safe(ident.album_artist or ident.artist)
    if kind == "single":
        return Placement(kind, Path("Artists") / artist_dir / "Singles", safe(ident.title))
    return Placement(kind, Path("Artists") / artist_dir / album_dir, f"{num}{safe(ident.title)}")


def _prune_empty(d: Path, stop: Path) -> None:
    try:
        while d != stop and d.exists() and not any(d.iterdir()):
            d.rmdir()
            d = d.parent
    except OSError:
        pass
