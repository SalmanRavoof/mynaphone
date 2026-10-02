# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Filing: classify, encode (AAC or FLAC), tag, write lyrics, place in the library tree."""
from __future__ import annotations

import base64
import logging
import re
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC,
    COMM,
    ID3,
    SYLT,
    TALB,
    TCOM,
    TCON,
    TCOP,
    TDRC,
    TEXT,
    TIT2,
    TPE1,
    TPE2,
    TPOS,
    TPUB,
    TRCK,
    TSO2,
    TSOP,
    TSRC,
    TXXX,
    USLT,
    Encoding,
    ID3NoHeaderError,
)
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
from mutagen.oggopus import OggOpus

from . import tools
from .identify import Identity
from .store import tier_rank

log = logging.getLogger("mynaphone.library")

EXT = {"aac": ".m4a", "mp3": ".mp3", "opus": ".opus", "flac": ".flac"}

_bad = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe(s: str, limit: int = 90) -> str:
    s = _bad.sub("", s or "").strip(" .")
    s = re.sub(r"\s+", " ", s)
    return (s or "Unknown")[:limit].rstrip(" .")


@dataclass
class Placement:
    kind: str           # soundtrack | album | single | compilation | unsorted
    rel_dir: Path
    filename: str       # without extension


def classify(ident: Identity) -> str:
    if not ident.artist.strip() and not ident.album_artist.strip():
        return "unsorted"       # nothing to file it under yet; a person or a later lookup decides
    if ident.is_soundtrack:
        return "soundtrack"
    rt = (ident.release_type or "").lower()
    if rt in ("single", "ep") or (ident.track_total and ident.track_total <= 3 and rt != "album"):
        return "single"
    if (any(t.lower() == "compilation" for t in ident.secondary_types)
            or ident.album_artist.lower() in ("various artists", "various")):
        return "compilation"
    if not ident.album or ident.album.strip().lower() == ident.title.strip().lower():
        return "single"
    return "album"


def place(ident: Identity) -> Placement:
    kind = classify(ident)
    num = ""
    if ident.track_number:
        num = f"{ident.track_number:02d} "
        if ident.disc_total and ident.disc_total > 1 and ident.disc_number:
            num = f"{ident.disc_number}-{ident.track_number:02d} "
    album = safe(ident.album)
    year = ident.year or (int(ident.original_date[:4]) if ident.original_date[:4].isdigit() else 0)
    album_dir = f"{album} ({year})" if (year and kind in ("soundtrack", "album", "compilation")) else album
    if kind == "unsorted":
        return Placement(kind, Path("Unsorted"), safe(ident.title))
    if kind == "soundtrack":
        return Placement(kind, Path("Soundtracks") / album_dir, f"{num}{safe(ident.title)}")
    if kind == "compilation":
        return Placement(kind, Path("Artists") / "Various Artists" / album_dir, f"{num}{safe(ident.title)}")
    artist_dir = safe(ident.album_artist or ident.artist)
    if kind == "single":
        return Placement(kind, Path("Artists") / artist_dir / "Singles", safe(ident.title))
    return Placement(kind, Path("Artists") / artist_dir / album_dir, f"{num}{safe(ident.title)}")


def encode(src_flac: Path, dst: Path, fmt: str, bitrate: int) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "flac":
        shutil.copy2(src_flac, dst)
        return
    exe = tools.ffmpeg()
    if not exe:
        raise RuntimeError("ffmpeg not found")
    codec = {"aac": ["-c:a", "aac", "-b:a", f"{bitrate}k", "-movflags", "+faststart"],
             "mp3": ["-c:a", "libmp3lame", "-b:a", f"{bitrate}k", "-id3v2_version", "3"],
             "opus": ["-c:a", "libopus", "-b:a", f"{bitrate}k", "-vbr", "on"]}.get(fmt)
    if codec is None:
        raise ValueError(f"unknown library format {fmt!r}")
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src_flac), "-vn", "-map_metadata", "-1",
           *codec, str(dst)]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if out.returncode != 0 or not dst.exists():
        raise RuntimeError(f"ffmpeg failed: {out.stderr.strip()[:300]}")


# ----------------------------------------------------------------------------- cover art

def cover_from_flac(src: Path) -> tuple[bytes, str] | None:
    try:
        f = FLAC(str(src))
        if f.pictures:
            p = f.pictures[0]
            return p.data, p.mime
    except Exception:
        pass
    return None


def _fetch(url: str, timeout: float = 15.0) -> tuple[bytes, str] | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mynaphone/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        if data[:3] == b"\xff\xd8\xff":
            return data, "image/jpeg"
        if data[:4] == b"\x89PNG":
            return data, "image/png"
    except Exception:
        pass
    return None


def resolve_cover(src_flac: Path, ident: Identity, cover_url: str = "") -> tuple[bytes, str] | None:
    """Embedded picture, else the Spotify 640px cover, else the Cover Art Archive front image."""
    c = cover_from_flac(src_flac)
    if c:
        return c
    if cover_url.startswith("http"):
        c = _fetch(cover_url)
        if c:
            return c
    if ident.mb_release_id:
        c = _fetch(f"https://coverartarchive.org/release/{ident.mb_release_id}/front-500")
        if c:
            return c
    if ident.mb_release_group_id:
        c = _fetch(f"https://coverartarchive.org/release-group/{ident.mb_release_group_id}/front-500")
        if c:
            return c
    return None


# ----------------------------------------------------------------------------- tagging

def _free_fields(ident: Identity, capture: dict) -> dict[str, str]:
    """Extended tags shared by both containers (names follow the MusicBrainz Picard mapping)."""
    f = {
        "MUSICBRAINZ_TRACKID": ident.mb_recording_id,
        "MUSICBRAINZ_ALBUMID": ident.mb_release_id,
        "MUSICBRAINZ_RELEASEGROUPID": ident.mb_release_group_id,
        "MUSICBRAINZ_ARTISTID": "; ".join(ident.mb_artist_ids),
        "MUSICBRAINZ_ALBUMARTISTID": "; ".join(ident.mb_album_artist_ids),
        "ACOUSTID_ID": ident.acoustid_id,
        "ACOUSTID_FINGERPRINT": ident.acoustid_fingerprint,
        "ISRC": ident.isrc,
        "LABEL": ident.label,
        "CATALOGNUMBER": ident.catalog,
        "BARCODE": ident.barcode,
        "RELEASECOUNTRY": ident.country,
        "RELEASESTATUS": ident.status,
        "RELEASETYPE": "; ".join([ident.release_type] + [t.lower() for t in ident.secondary_types])
                       if ident.release_type or ident.secondary_types else "",
        "ORIGINALDATE": ident.original_date,
        "ORIGINALYEAR": ident.original_date[:4] if ident.original_date[:4].isdigit() else "",
        "MEDIA": ident.media_format,
        "LANGUAGE": ident.language,
        "LYRICIST": "; ".join(ident.lyricists),
        "PERFORMER": "; ".join([f"{v} (vocals)" for v in ident.vocals] + ident.performers),
        "PRODUCER": "; ".join(ident.producers),
        "ARTISTSORT": ident.artist_sort,
        "ALBUMARTISTSORT": ident.album_artist_sort,
        "SPOTIFY_TRACK_URI": ident.spotify_track_uri,
        "SPOTIFY_ALBUM_URI": ident.spotify_album_uri,
        "SPOTIFY_ARTIST_URI": "; ".join(ident.spotify_artist_uris),
        "SPOTIFY_POPULARITY": str(ident.popularity) if ident.popularity is not None else "",
        "SPOTIFY_RELEASE_DATE": ident.spotify_release_date,
        "MYNAPHONE_SOURCE_APP": capture.get("source_app", ""),
        "MYNAPHONE_QUALITY_TIER": capture.get("quality_tier", ""),
        "MYNAPHONE_CAPTURED_AT": capture.get("captured_at", ""),
        "MYNAPHONE_CAPTURE_FORMAT": capture.get("capture_format", ""),
        "MYNAPHONE_IDENTIFIED_BY": ident.source,
        "MYNAPHONE_ACOUSTID_SCORE": f"{ident.score:.2f}" if ident.source == "acoustid" else "",
    }
    return {k: v for k, v in f.items() if v}


def _lrc_to_sylt(text: str) -> list[tuple[str, int]] | None:
    """Parse LRC lines into (text, ms) pairs for an ID3 SYLT frame; None if not synced."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^\[(\d+):(\d+)(?:\.(\d+))?\](.*)$", line)
        if not m:
            continue
        frac = (m.group(3) or "0").ljust(3, "0")[:3]
        ms = int(m.group(1)) * 60000 + int(m.group(2)) * 1000 + int(frac)
        out.append((m.group(4).strip(), ms))
    return out or None


def tag(dst: Path, ident: Identity, cover: tuple[bytes, str] | None, lyrics_text: str, capture: dict) -> None:
    kind = capture.get("kind", "")
    genre = ident.genres[0].title() if ident.genres else ("Soundtrack" if kind == "soundtrack" else "")
    comment = f"Captured with Mynaphone from {capture.get('source_app', 'Spotify')}; identified by {ident.source}."
    ext = dst.suffix.lower()
    if ext == ".mp3":
        try:
            f = ID3(str(dst))
            f.delete()
        except ID3NoHeaderError:
            f = ID3()
        f.add(TIT2(encoding=Encoding.UTF8, text=ident.title))
        f.add(TPE1(encoding=Encoding.UTF8, text=ident.artist))
        if ident.album:
            f.add(TALB(encoding=Encoding.UTF8, text=ident.album))
        if ident.album_artist:
            f.add(TPE2(encoding=Encoding.UTF8, text=ident.album_artist))
        if ident.date or ident.year:
            f.add(TDRC(encoding=Encoding.UTF8, text=ident.date or str(ident.year)))
        if ident.track_number:
            f.add(TRCK(encoding=Encoding.UTF8, text=f"{ident.track_number}/{ident.track_total}"
                                                    if ident.track_total else str(ident.track_number)))
        if ident.disc_number:
            f.add(TPOS(encoding=Encoding.UTF8, text=f"{ident.disc_number}/{ident.disc_total}"
                                                    if ident.disc_total else str(ident.disc_number)))
        if genre:
            f.add(TCON(encoding=Encoding.UTF8, text=genre))
        if ident.composers:
            f.add(TCOM(encoding=Encoding.UTF8, text="; ".join(ident.composers)))
        if ident.lyricists:
            f.add(TEXT(encoding=Encoding.UTF8, text="; ".join(ident.lyricists)))
        if ident.label:
            f.add(TPUB(encoding=Encoding.UTF8, text=ident.label))
        if ident.isrc:
            f.add(TSRC(encoding=Encoding.UTF8, text=ident.isrc))
        if ident.copyright:
            f.add(TCOP(encoding=Encoding.UTF8, text=ident.copyright))
        if ident.artist_sort:
            f.add(TSOP(encoding=Encoding.UTF8, text=ident.artist_sort))
        if ident.album_artist_sort:
            f.add(TSO2(encoding=Encoding.UTF8, text=ident.album_artist_sort))
        f.add(COMM(encoding=Encoding.UTF8, lang="eng", desc="", text=comment))
        if lyrics_text:
            f.add(USLT(encoding=Encoding.UTF8, lang="xxx", desc="", text=lyrics_text))
            sylt = _lrc_to_sylt(lyrics_text)
            if sylt:
                f.add(SYLT(encoding=Encoding.UTF8, lang="xxx", format=2, type=1, desc="", text=sylt))
        for k, v in _free_fields(ident, capture).items():
            if k in ("ISRC", "LYRICIST", "LABEL"):
                continue
            f.add(TXXX(encoding=Encoding.UTF8, desc=k, text=v))
        if cover:
            data, mime = cover
            f.add(APIC(encoding=Encoding.UTF8, mime=mime, type=3, desc="Cover", data=data))
        f.save(str(dst), v2_version=3)
        return
    if ext == ".opus":
        f = OggOpus(str(dst))
        f.delete()
        f["TITLE"] = ident.title
        f["ARTIST"] = ident.artist
        if ident.artists and len(ident.artists) > 1:
            f["ARTISTS"] = ident.artists
        if ident.album:
            f["ALBUM"] = ident.album
        if ident.album_artist:
            f["ALBUMARTIST"] = ident.album_artist
        if ident.date or ident.year:
            f["DATE"] = ident.date or str(ident.year)
        if ident.track_number:
            f["TRACKNUMBER"] = str(ident.track_number)
            if ident.track_total:
                f["TRACKTOTAL"] = str(ident.track_total)
        if ident.disc_number:
            f["DISCNUMBER"] = str(ident.disc_number)
            if ident.disc_total:
                f["DISCTOTAL"] = str(ident.disc_total)
        if genre:
            f["GENRE"] = ident.genres[:3] if ident.genres else [genre]
        if ident.composers:
            f["COMPOSER"] = ident.composers
        if ident.copyright:
            f["COPYRIGHT"] = ident.copyright
        if kind == "compilation":
            f["COMPILATION"] = "1"
        if lyrics_text:
            f["LYRICS"] = lyrics_text
        f["COMMENT"] = comment
        f["ENCODER"] = "Mynaphone"
        for k, v in _free_fields(ident, capture).items():
            f[k] = v.split("; ") if k in ("MUSICBRAINZ_ARTISTID", "MUSICBRAINZ_ALBUMARTISTID", "LYRICIST",
                                          "PERFORMER", "PRODUCER", "RELEASETYPE") else v
        if cover:
            data, mime = cover
            pic = Picture()
            pic.type = 3
            pic.mime = mime
            pic.data = data
            f["METADATA_BLOCK_PICTURE"] = [base64.b64encode(pic.write()).decode("ascii")]
        f.save()
        return
    if ext == ".m4a":
        f = MP4(str(dst))
        f.delete()
        f["\xa9nam"] = ident.title
        f["\xa9ART"] = ident.artist
        if ident.album:
            f["\xa9alb"] = ident.album
        if ident.album_artist:
            f["aART"] = ident.album_artist
        if ident.date or ident.year:
            f["\xa9day"] = ident.date or str(ident.year)
        if ident.track_number:
            f["trkn"] = [(ident.track_number, ident.track_total or 0)]
        if ident.disc_number:
            f["disk"] = [(ident.disc_number, ident.disc_total or 0)]
        if genre:
            f["\xa9gen"] = genre
        if ident.composers:
            f["\xa9wrt"] = "; ".join(ident.composers)
        if ident.artist_sort:
            f["soar"] = ident.artist_sort
        if ident.album_artist_sort:
            f["soaa"] = ident.album_artist_sort
        if ident.copyright:
            f["cprt"] = ident.copyright
        if ident.explicit is not None:
            f["rtng"] = [4 if ident.explicit else 2]
        if kind == "compilation":
            f["cpil"] = True
        if lyrics_text:
            f["\xa9lyr"] = lyrics_text
        f["\xa9cmt"] = comment
        f["\xa9too"] = "Mynaphone (ffmpeg aac)"
        if cover:
            data, mime = cover
            f["covr"] = [MP4Cover(data, MP4Cover.FORMAT_PNG if "png" in mime else MP4Cover.FORMAT_JPEG)]
        for k, v in _free_fields(ident, capture).items():
            f[f"----:com.apple.iTunes:{k}"] = MP4FreeForm(v.encode("utf-8"))
        f.save()
    else:
        f = FLAC(str(dst))
        f.delete()
        f["TITLE"] = ident.title
        f["ARTIST"] = ident.artist
        if ident.artists and len(ident.artists) > 1:
            f["ARTISTS"] = ident.artists
        if ident.album:
            f["ALBUM"] = ident.album
        if ident.album_artist:
            f["ALBUMARTIST"] = ident.album_artist
        if ident.date or ident.year:
            f["DATE"] = ident.date or str(ident.year)
        if ident.track_number:
            f["TRACKNUMBER"] = str(ident.track_number)
            if ident.track_total:
                f["TRACKTOTAL"] = str(ident.track_total)
        if ident.disc_number:
            f["DISCNUMBER"] = str(ident.disc_number)
            if ident.disc_total:
                f["DISCTOTAL"] = str(ident.disc_total)
        if genre:
            f["GENRE"] = ident.genres[:3] if ident.genres else [genre]
        if ident.composers:
            f["COMPOSER"] = ident.composers
        if ident.copyright:
            f["COPYRIGHT"] = ident.copyright
        if kind == "compilation":
            f["COMPILATION"] = "1"
        if lyrics_text:
            f["LYRICS"] = lyrics_text
        f["COMMENT"] = comment
        f["ENCODER"] = "Mynaphone"
        for k, v in _free_fields(ident, capture).items():
            f[k] = v.split("; ") if k in ("MUSICBRAINZ_ARTISTID", "MUSICBRAINZ_ALBUMARTISTID", "LYRICIST",
                                          "PERFORMER", "PRODUCER", "RELEASETYPE") else v
        if cover:
            data, mime = cover
            pic = Picture()
            pic.type = 3
            pic.mime = mime
            pic.data = data
            f.clear_pictures()
            f.add_picture(pic)
        f.save()


def write_lyrics_sidecar(dst: Path, lyrics_text: str) -> None:
    if lyrics_text and "[" in lyrics_text[:12]:
        dst.with_suffix(".lrc").write_text(lyrics_text, encoding="utf-8")


def write_lyrics(path: Path, text: str) -> None:
    """Replace just the lyrics in an existing library file of any supported format."""
    ext = path.suffix.lower()
    if ext == ".m4a":
        f = MP4(str(path))
        f["\xa9lyr"] = text
        f.save()
    elif ext == ".mp3":
        f = ID3(str(path))
        f.delall("USLT")
        f.delall("SYLT")
        f.add(USLT(encoding=Encoding.UTF8, lang="xxx", desc="", text=text))
        sylt = _lrc_to_sylt(text)
        if sylt:
            f.add(SYLT(encoding=Encoding.UTF8, lang="xxx", format=2, type=1, desc="", text=sylt))
        f.save(str(path), v2_version=3)
    elif ext == ".opus":
        f = OggOpus(str(path))
        f["LYRICS"] = text
        f.save()
    else:
        f = FLAC(str(path))
        f["LYRICS"] = text
        f.save()


def read_extras(path: Path) -> tuple[tuple[bytes, str] | None, str]:
    """Cover and lyrics currently embedded in a library file of any supported format."""
    ext = path.suffix.lower()
    if ext == ".m4a":
        f = MP4(str(path))
        cover = None
        if f.get("covr"):
            c = f["covr"][0]
            cover = (bytes(c), "image/png" if c.imageformat == 13 else "image/jpeg")
        return cover, (f["\xa9lyr"][0] if f.get("\xa9lyr") else "")
    if ext == ".mp3":
        f = ID3(str(path))
        pics = f.getall("APIC")
        cover = (pics[0].data, pics[0].mime) if pics else None
        us = f.getall("USLT")
        return cover, (us[0].text if us else "")
    if ext == ".opus":
        f = OggOpus(str(path))
        cover = None
        if f.get("METADATA_BLOCK_PICTURE"):
            pic = Picture(base64.b64decode(f["METADATA_BLOCK_PICTURE"][0]))
            cover = (pic.data, pic.mime)
        return cover, (f["LYRICS"][0] if f.get("LYRICS") else "")
    f = FLAC(str(path))
    cover = (f.pictures[0].data, f.pictures[0].mime) if f.pictures else None
    return cover, (f["LYRICS"][0] if f.get("LYRICS") else "")


def file_take(src_flac: Path, library_dir: Path, ident: Identity, fmt: str, bitrate: int,
              lyrics_text: str, capture: dict, cover: tuple[bytes, str] | None,
              keep_flac_for_lossless: bool = True) -> Path:
    """Encode, tag and place the file. Returns the final path."""
    tier = capture.get("quality_tier", "")
    use_fmt = "flac" if (keep_flac_for_lossless and tier_rank(tier) >= tier_rank("hifi")) else fmt
    ext = EXT.get(use_fmt, ".m4a")
    pl = place(ident)
    capture = dict(capture, kind=pl.kind)
    dst = library_dir / pl.rel_dir / f"{pl.filename}{ext}"
    if dst.exists():
        dst.unlink()
    encode(src_flac, dst, use_fmt, bitrate)
    tag(dst, ident, cover, lyrics_text, capture)
    write_lyrics_sidecar(dst, lyrics_text)
    return dst
