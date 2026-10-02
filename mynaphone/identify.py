# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Identify a captured file: Chromaprint fingerprint -> AcoustID -> best MusicBrainz release.

AcoustID's lookup with the release/track metadata is enough to get the canonical title, artist,
album, year, track and disc numbers and the release-group type (soundtrack, single...) without a
separate MusicBrainz call. When AcoustID knows nothing (common for Indian film music), the caller
falls back to the provisional Spotify tags.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import tools
from .store import norm

log = logging.getLogger("mynaphone.identify")

ACOUSTID_URL = "https://api.acoustid.org/v2/lookup"
USER_AGENT = "mynaphone/0.1"


@dataclass
class Identity:
    source: str = "none"               # acoustid | spotify | tags
    score: float = 0.0
    title: str = ""
    artist: str = ""
    artists: list[str] = field(default_factory=list)
    album: str = ""
    album_artist: str = ""
    year: int = 0
    date: str = ""
    track_number: int = 0
    track_total: int = 0
    disc_number: int = 0
    disc_total: int = 0
    release_type: str = ""             # album | single | ep | ...
    secondary_types: list[str] = field(default_factory=list)   # soundtrack, compilation, live...
    mb_recording_id: str = ""
    mb_release_id: str = ""
    mb_release_group_id: str = ""
    mb_artist_ids: list[str] = field(default_factory=list)
    mb_album_artist_ids: list[str] = field(default_factory=list)
    acoustid_id: str = ""
    acoustid_fingerprint: str = ""
    # enrichment (MusicBrainz + Spotify)
    artist_sort: str = ""
    album_artist_sort: str = ""
    composers: list[str] = field(default_factory=list)
    lyricists: list[str] = field(default_factory=list)
    vocals: list[str] = field(default_factory=list)
    performers: list[str] = field(default_factory=list)
    producers: list[str] = field(default_factory=list)
    isrc: str = ""
    genres: list[str] = field(default_factory=list)
    label: str = ""
    catalog: str = ""
    barcode: str = ""
    country: str = ""
    status: str = ""
    original_date: str = ""
    language: str = ""
    media_format: str = ""
    explicit: bool | None = None
    popularity: int | None = None
    copyright: str = ""
    spotify_track_uri: str = ""
    spotify_album_uri: str = ""
    spotify_artist_uris: list[str] = field(default_factory=list)
    spotify_label: str = ""
    spotify_release_date: str = ""

    @property
    def is_soundtrack(self) -> bool:
        return any(t.lower() == "soundtrack" for t in self.secondary_types)

    def to_json(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "acoustid_fingerprint"}


class ToolMissing(RuntimeError):
    pass


COUNT_RE = re.compile(r"\b\d[\d.,]*\s*[KMB]?\s*(views?|likes?|subscribers?)\b", re.I)


def looks_like_count(text: str) -> bool:
    """True for YouTube byline fragments such as '54M views' that must never become an album name."""
    return bool(text) and bool(COUNT_RE.search(text) or re.fullmatch(r"\s*\d[\d.,]*\s*[KMB]?\s*", text))


def fingerprint(path: str, offset_s: float = 0.0, length_s: int = 120) -> tuple[int, str]:
    """Chromaprint fingerprint of `length_s` seconds starting at `offset_s`.

    A music video often opens with dialogue, so a second attempt from the middle of the recording
    matches where the first did not.
    """
    exe = tools.fpcalc()
    if not exe:
        raise ToolMissing("fpcalc not found")
    src = path
    tmp = None
    if offset_s > 0:
        ff = tools.ffmpeg()
        if not ff:
            raise ToolMissing("ffmpeg not found")
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        cut = subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-ss", str(offset_s), "-t", str(length_s),
                              "-i", path, "-vn", tmp.name], capture_output=True, text=True, timeout=120,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if cut.returncode != 0:
            raise RuntimeError(f"ffmpeg cut failed: {cut.stderr.strip()[:200]}")
        src = tmp.name
    try:
        out = subprocess.run([exe, "-json", "-length", str(length_s), src], capture_output=True, text=True, timeout=120,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        if tmp is not None:
            try:
                import os
                os.unlink(tmp.name)
            except OSError:
                pass
    if out.returncode != 0:
        raise RuntimeError(f"fpcalc failed: {out.stderr.strip()[:200]}")
    d = json.loads(out.stdout)
    duration = int(round(float(d["duration"])))
    if offset_s > 0:
        # AcoustID wants the whole recording's duration, not the window's
        try:
            from mutagen import File as MFile
            info = MFile(path)
            if info is not None and getattr(info, "info", None) is not None:
                duration = int(round(info.info.length))
        except Exception:
            pass
    return duration, d["fingerprint"]


def lookup_with_retry(key: str, path: str, hints: dict) -> tuple[Identity | None, str]:
    """Fingerprint from the start, then from 45 s in, returning the first confident match."""
    last_fp = ""
    for offset in (0.0, 45.0):
        dur, fp = fingerprint(path, offset)
        last_fp = fp
        res = acoustid_lookup(key, dur, fp)
        if res.get("status") != "ok":
            raise RuntimeError(f"acoustid: {res.get('error', {}).get('message', res.get('status'))}")
        res["_fingerprint"] = fp if offset == 0 else last_fp
        ident = choose(res, **hints)
        if ident is not None:
            return ident, "" if offset == 0 else "matched from the middle of the recording"
    return None, "no AcoustID match"


def acoustid_lookup(key: str, duration: int, fp: str, timeout: float = 20.0) -> dict:
    data = urllib.parse.urlencode({
        "client": key, "duration": duration, "fingerprint": fp,
        "meta": "recordings releasegroups releases tracks compress",
    }).encode()
    req = urllib.request.Request(ACOUSTID_URL, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _artist_names(credits) -> list[str]:
    names = []
    for a in credits or []:
        n = a.get("name") if isinstance(a, dict) else None
        if n:
            names.append(n)
    return names


def _join_artists(credits) -> str:
    names = _artist_names(credits)
    if not names:
        return ""
    joined = ""
    for a in credits:
        joined += a.get("name", "") + (a.get("joinphrase") or "")
    return joined.strip() or ", ".join(names)


def _score_release(rel: dict, rg: dict, hint_album: str, hint_track: int, hint_artist: str) -> float:
    s = 0.0
    if hint_album and norm(rel.get("title", "")) == norm(hint_album):
        s += 5
    elif hint_album and norm(hint_album) in norm(rel.get("title", "")):
        s += 2
    if rg.get("type", "").lower() == "album":
        s += 1
    if "compilation" in [t.lower() for t in rg.get("secondarytypes", [])]:
        s -= 1.5
    for m in rel.get("mediums", []):
        for t in m.get("tracks", []):
            if hint_track and int(t.get("position", 0)) == hint_track:
                s += 1.5
    if rel.get("date", {}).get("year"):
        s += 0.5
    if hint_artist and any(norm(hint_artist) == norm(a) for a in _artist_names(rg.get("artists"))):
        s += 1
    return s


def choose(result: dict, hint_album: str = "", hint_track: int = 0, hint_artist: str = "", hint_title: str = "",
           min_score: float = 0.5) -> Identity | None:
    best: Identity | None = None
    best_rank = -1e9
    for res in result.get("results", []):
        score = float(res.get("score", 0))
        if score < min_score:
            continue
        for rec in res.get("recordings", []) or []:
            rec_title = rec.get("title", "")
            title_bonus = 2.0 if hint_title and norm(rec_title) == norm(hint_title) else 0.0
            for rg in rec.get("releasegroups", []) or []:
                for rel in rg.get("releases", []) or []:
                    rank = score * 10 + title_bonus + _score_release(rel, rg, hint_album, hint_track, hint_artist)
                    if rank <= best_rank:
                        continue
                    ident = Identity(source="acoustid", score=score, acoustid_id=res.get("id", ""),
                                     acoustid_fingerprint=result.get("_fingerprint", ""))
                    ident.title = rec_title
                    ident.artists = _artist_names(rec.get("artists"))
                    ident.artist = _join_artists(rec.get("artists")) or ", ".join(ident.artists)
                    ident.mb_artist_ids = [a.get("id", "") for a in rec.get("artists", []) or [] if a.get("id")]
                    ident.mb_recording_id = rec.get("id", "")
                    ident.album = rel.get("title", "") or rg.get("title", "")
                    ident.album_artist = _join_artists(rg.get("artists")) or ident.artist
                    d = rel.get("date") or {}
                    if d.get("year"):
                        ident.year = int(d["year"])
                        ident.date = "-".join(str(d[k]).zfill(2 if k != "year" else 4)
                                              for k in ("year", "month", "day") if d.get(k))
                    ident.release_type = (rg.get("type") or "").lower()
                    ident.secondary_types = [t for t in rg.get("secondarytypes", []) or []]
                    ident.mb_release_id = rel.get("id", "")
                    ident.mb_release_group_id = rg.get("id", "")
                    ident.disc_total = int(rel.get("medium_count", 0) or 0)
                    for m in rel.get("mediums", []) or []:
                        for t in m.get("tracks", []) or []:
                            if norm(t.get("title", "")) == norm(rec_title) or t.get("id") == rec.get("id"):
                                ident.track_number = int(t.get("position", 0) or 0)
                                ident.track_total = int(m.get("track_count", 0) or 0)
                                ident.disc_number = int(m.get("position", 0) or 0)
                    best, best_rank = ident, rank
    return best


SOUNDTRACK_RE = re.compile(
    r"original (motion picture|movie|film|television|tv|series|game)?\s*(soundtrack|score)|"
    r"\b(ost|soundtrack|score|from the (motion picture|movie|film|series))\b|"
    r"\(from [\"“']|music from the|"
    r"\b(original|motion picture) soundtrack\b", re.I)


def looks_like_soundtrack(album: str, title: str = "") -> bool:
    return bool(SOUNDTRACK_RE.search(album or "")) or bool(re.search(r"\(from [\"“']", title or "", re.I))


INSTRUMENTAL_RE = re.compile(r"\binstrumentals?\b", re.I)


def is_instrumental(title: str, album: str = "") -> bool:
    """True when the title or the album says there are no vocals: 'Kyon Hawa (Instrumental)',
    'Romancing The Legend: Veer-Zaara Instrumental'. Such songs have no lyrics or lyricist to look for."""
    return bool(INSTRUMENTAL_RE.search(title or "") or INSTRUMENTAL_RE.search(album or ""))


def from_tags(meta: dict) -> Identity:
    """Build an identity from the capture's provisional (Spotify) metadata."""
    ident = Identity(source="spotify" if meta.get("source_uri") else "tags")
    ident.title = meta.get("title", "")
    ident.artist = meta.get("artist", "")
    ident.artists = ([a.strip() for a in re.split(r",|;|&| feat\.? | ft\.? ", ident.artist) if a.strip()]
                     or [ident.artist])
    ident.album = "" if looks_like_count(meta.get("album", "")) else meta.get("album", "")
    ident.album_artist = meta.get("album_artist", "") or ident.artist
    ident.track_number = int(meta.get("track_number") or 0)
    ident.disc_number = int(meta.get("disc_number") or 0)
    if looks_like_soundtrack(ident.album, ident.title):
        ident.secondary_types = ["Soundtrack"]
    if not ident.album:
        ident.release_type = ident.release_type or "single"
    apply_spotify(ident, meta)
    return ident


def apply_spotify(ident: Identity, meta: dict) -> None:
    """Add the Spotify-only facts (uris, explicit flag, popularity, label, copyright, release date)."""
    ident.spotify_track_uri = meta.get("source_uri", "") or ""
    ident.spotify_album_uri = meta.get("album_uri", "") or ""
    ident.spotify_artist_uris = list(meta.get("artist_uris") or [])
    extra = meta.get("extra") or {}
    info = extra.get("album_info") or {}
    date = info.get("release_date") or ""
    ident.spotify_release_date = date
    if date[:4].isdigit() and not ident.year:
        ident.year = int(date[:4])
        ident.date = date
    if not ident.track_total:
        ident.track_total = int(info.get("total_tracks") or 0)
    if not ident.release_type:
        ident.release_type = (info.get("album_type") or "").lower()
    ident.spotify_label = info.get("label") or ""
    if not ident.label:
        ident.label = ident.spotify_label
    cr = info.get("copyrights") or []
    if cr and not ident.copyright:
        ident.copyright = cr[0]
    md = extra.get("track_metadata") or {}
    # Spotify's player reports where the track sits on its album even when the web API refuses
    for attr, k in (("track_number", "album_track_number"), ("track_total", "album_track_count"),
                    ("disc_number", "album_disc_number"), ("disc_total", "album_disc_count")):
        if not getattr(ident, attr) and str(md.get(k) or "").isdigit():
            setattr(ident, attr, int(md[k]))
    ti = extra.get("track_info") or {}
    if ti.get("explicit") is not None:
        ident.explicit = bool(ti["explicit"])
    elif md.get("is_explicit") is not None:
        ident.explicit = str(md.get("is_explicit")).lower() == "true"
    for src in (ti.get("popularity"), md.get("popularity")):
        try:
            if src not in (None, ""):
                ident.popularity = int(src)
                break
        except (TypeError, ValueError):
            pass
    if ti.get("isrc") and not ident.isrc:
        ident.isrc = str(ti["isrc"]).upper()
    if not ident.track_total and ti.get("track_total"):
        ident.track_total = int(ti["track_total"])
    if not ident.disc_number and ti.get("disc_number"):
        ident.disc_number = int(ti["disc_number"])
    # Indian film music: the soundtrack's album artist is the music director, i.e. the composer
    if (ident.is_soundtrack and not ident.composers and ident.album_artist
            and ident.album_artist.lower() not in ("various artists", "various")):
        ident.composers = [ident.album_artist]


# Keys that labels such as T-Series, YRF, Sony Music India and Zee Music put in video descriptions.
# "Artist" and "Starring" are the actors and are ignored on purpose.
CREDIT_KEYS = [
    ("title", r"song|song name|track|title|song title"),
    ("film", r"film|movie|album|film name|movie name|from the (?:film|movie)"),
    ("singers", r"singers?|vocals?|vocalists?|sung by|singer\(s\)|voice|rendered by"),
    ("lyricists", r"lyrics|lyricist|lyrics by|lyricists|written by|lyric"),
    ("composers", r"music|music director|composer|composed by|music by|music composer|music directors?|composers"),
    ("label", r"music on|label|music label|music partner"),
    ("year", r"release date|released|released on|year|release year"),
]
CREDIT_LINE_RE = re.compile(r"^\W*(?P<key>[A-Za-z][A-Za-z()/ ]{1,30}?)\s*[-:\u2013\u2014]+\s*(?P<val>.+?)\s*$")
_KEY_WORDS = (r"(?:Song|Film|Movie|Album|Singers?|Vocals?|Lyrics|Lyricist|Music Director|Music On|Music|Composer|"
              r"Label|Release Date|Starring|Director|Producer|Artist)")
TITLE_NOISE_RE = re.compile(
    r"\s*[\(\[]?\b(full (?:video|audio|song|hd)?\s*(?:song|video)?|"
    r"official (?:video|audio|music video|lyric video|song)?|"
    r"lyrical(?: video)?|video song|audio song|hd video|4k|hd|hq|"
    r"lyrics?(?: video)?|with lyrics|remastered|visualizer)\b[\)\]]?\s*",
    re.I)


def parse_video_credits(text: str) -> dict:
    """Pull song, film, singers, lyricist, music director, label and year out of a video description.

    Returns {} when the text has no such lines. Lists are already split on commas and ampersands.
    """
    if not text:
        return {}
    if text.count("\n") < 2:
        # a description that reached us with its line breaks collapsed
        text = re.sub(r"\s+(?=" + _KEY_WORDS + r"\s*[-:\u2013\u2014])", "\n", text)
    out: dict = {}
    for line in text.splitlines():
        m = CREDIT_LINE_RE.match(line)
        if not m:
            continue
        key = re.sub(r"\s+", " ", m.group("key")).strip().lower()
        val = m.group("val").strip(" .;,")
        if not val or val.lower() in ("na", "n/a", "-"):
            continue
        for name, pat in CREDIT_KEYS:
            if re.fullmatch(pat, key, re.I) and name not in out:
                out[name] = val
                break
    if not out or ("title" not in out and "film" not in out):
        return {}
    for name in ("singers", "lyricists", "composers"):
        if name in out:
            raw = re.sub(r"\b(?:backing vocals?|chorus|rap)\s*[:\-]\s*", "", out[name], flags=re.I)
            out[name] = split_names(raw)
    if "year" in out:
        y = re.search(r"\b(19|20)\d{2}\b", out["year"])
        out["year"] = int(y.group(0)) if y else 0
        if not out["year"]:
            del out["year"]
    if "label" in out:
        out["label"] = re.split(r",|\|", out["label"])[0].strip()
    return out


def split_names(raw: str) -> list[str]:
    """'Kishore Kumar, Sumeet Kumar & Vishal Dadlani' -> three names; 'Vishal and Shekhar' stays one.

    Composer duos are written with "and", "&" or a hyphen between two first names (Vishal and
    Shekhar, Salim-Sulaiman, Sachin-Jigar), so a separator only splits two full names.
    """
    parts = []
    for chunk in re.split(r",|\||;", raw or ""):
        chunk = chunk.strip(" .")
        if not chunk:
            continue
        halves = re.split(r"\s+(?:and|&)\s+", chunk, maxsplit=1, flags=re.I)
        if len(halves) == 2 and all(len(h.split()) >= 2 for h in halves):
            parts.extend(h.strip(" .") for h in halves)
        else:
            parts.append(chunk)
    return [x for x in parts if x]


def same_name(a: str, b: str) -> bool:
    """True for the same person spelt two ways (Rekha Bhardwaj, Rekha Bharadwaj)."""
    import difflib
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na or difflib.SequenceMatcher(None, na, nb).ratio() >= 0.82


def clean_video_title(title: str) -> str:
    """'A R Rahman : Genda Phool Full Song | Delhi 6 | Abhishek...' -> 'Genda Phool'."""
    t = (title or "").replace(" - YouTube Music", "").replace(" - YouTube", "")
    t = re.split(r"\s*[|\u2022]\s*", t)[0]
    if re.match(r"^[A-Za-z .]{2,40}:\s+\S", t):
        t = re.sub(r"^[^:]{1,40}:\s+", "", t)
    t = TITLE_NOISE_RE.sub(" ", t)
    t = re.sub(r"[\(\[]\s*[\)\]]", "", t)
    t = re.sub(r"\s+", " ", t).strip(" -:|")
    return t or (title or "").strip()


def fetch_video_description(video_id: str, timeout: float = 15.0) -> str:
    """The full description of a public YouTube video, read from the watch page."""
    if not video_id:
        return ""
    req = urllib.request.Request(
        f"https://www.youtube.com/watch?v={urllib.parse.quote(video_id)}&hl=en",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " + USER_AGENT,
                 "Accept-Language": "en", "Cookie": "CONSENT=YES+1; SOCS=CAI"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        html = r.read().decode("utf-8", "replace")
    m = re.search(r'"shortDescription":"((?:[^"\\]|\\.)*)"', html)
    if not m:
        return ""
    try:
        return json.loads('"' + m.group(1) + '"')
    except Exception:
        return ""


def _pick_catalogue_song(results: list, title: str, film: str, duration_s: float,
                         singers: list | None = None) -> dict | None:
    """The catalogue song that is the same recording as the video, or None.

    A cover with the same title and a similar length is the usual trap, so a film named in the
    credits must appear in the album name, or the credited singers must appear in the artists.
    """
    want = norm(title)
    want_singers = [x for x in (singers or []) if x]
    for r in results or []:
        got = norm(r.get("title", ""))
        got_base = re.sub(r"\s*\(from .*?\)\s*$", "", got).strip()
        if not got or not (got == want or got_base == want or (len(want) > 8 and (want in got or got in want))):
            continue
        alb = (r.get("album") or {}).get("name") or ""
        if not alb:
            continue
        d = r.get("duration_seconds") or 0
        if not d and r.get("duration") and ":" in str(r["duration"]):
            mm, ss = str(r["duration"]).split(":")[-2:]
            d = int(mm) * 60 + int(ss)
        same_length = bool(duration_s and d and abs(d - duration_s) <= 20)
        same_film = bool(film and (norm(film) in norm(alb) or norm(alb) in norm(film)))
        got_artists = [x for a in (r.get("artists") or []) for x in re.split(r"\s*\|\s*", a.get("name", "")) if x]
        same_singers = bool(want_singers and any(same_name(ws, ga) for ws in want_singers for ga in got_artists))
        if film:
            ok = same_film or (same_length and same_singers)
        elif want_singers:
            ok = same_singers and same_length
        else:
            ok = same_length
        if ok:
            return r
    return None


def from_youtube(meta: dict) -> Identity | None:
    """Identity for a capture made in the browser (needs network).

    Sources, best first: the song credits in the video description (song, film, singers, music
    director, lyricist, label), the YouTube Music catalogue (album, year, track number), then the
    YouTube Music player bar. A channel name is never used as the artist.
    """
    info = (meta.get("extra") or {}).get("youtube") or {}
    vid = info.get("video_id")
    if not vid:
        return None
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        song = yt.get_song(vid)
        vd = (song or {}).get("videoDetails") or {}
        official = (vd.get("musicVideoType") or "") in ("MUSIC_VIDEO_TYPE_OMV", "MUSIC_VIDEO_TYPE_ATV")
        duration_s = float(vd.get("lengthSeconds") or info.get("duration_s") or 0)

        desc = info.get("description") or ""
        if not desc:
            try:
                desc = fetch_video_description(vid)
                info["description"] = desc
            except Exception as e:
                log.info("could not read the video description for %s: %s", vid, e)
        credits = parse_video_credits(desc)
        m = info.get("music") or {}

        ident = Identity(source="youtube")
        page_title = vd.get("title") or info.get("page_title") or meta.get("title", "")
        ident.title = credits.get("title") or (m.get("title") or "") or clean_video_title(page_title)
        film = credits.get("film", "")
        singers = list(credits.get("singers") or [])
        ident.composers = list(credits.get("composers") or [])
        ident.lyricists = list(credits.get("lyricists") or [])
        ident.label = credits.get("label", "")
        if credits.get("year"):
            ident.year = int(credits["year"])

        # catalogue: the watch playlist knows the song behind an official video...
        album_id, album_name, cat_artists, cat_title = None, "", [], ""
        try:
            wp = yt.get_watch_playlist(videoId=vid, limit=1)
            for t in wp.get("tracks", []) or []:
                if t.get("videoId") == vid:
                    if t.get("album") and t["album"].get("id"):
                        album_id, album_name = t["album"]["id"], t["album"].get("name") or ""
                    cat_artists = [a.get("name", "") for a in (t.get("artists") or []) if a.get("name")]
                    cat_title = t.get("title") or ""
                    break
        except Exception as e:
            log.debug("ytmusic watch playlist failed: %s", e)
        # ...and a search finds it for a label upload that only carries credits
        if not album_id and ident.title:
            try:
                q = f"{ident.title} {film}".strip()
                hit = _pick_catalogue_song(yt.search(q, filter="songs", limit=8),
                                           ident.title, film, duration_s, singers)
                if hit:
                    album_id, album_name = hit["album"].get("id"), hit["album"].get("name") or ""
                    cat_artists = (cat_artists
                                   or [a.get("name", "") for a in (hit.get("artists") or []) if a.get("name")])
                    cat_title = cat_title or hit.get("title") or ""
            except Exception as e:
                log.debug("ytmusic search failed: %s", e)
        if album_id:
            try:
                alb = yt.get_album(album_id)
                album_name = alb.get("title") or album_name
                ident.album_artist = ", ".join(a.get("name", "") for a in alb.get("artists", []) or [] if a.get("name"))
                if str(alb.get("year", "")).isdigit():
                    ident.year = int(alb["year"])
                ident.release_type = (alb.get("type") or "").lower()
                ident.track_total = int(alb.get("trackCount") or 0)
                for i, t in enumerate(alb.get("tracks", []) or [], start=1):
                    if t.get("videoId") == vid or norm(t.get("title", "")) == norm(ident.title) \
                       or (cat_title and norm(t.get("title", "")) == norm(cat_title)):
                        ident.track_number = int(t.get("trackNumber") or i)
                        break
            except Exception as e:
                log.debug("ytmusic album failed: %s", e)

        # artist: the singers from the credits, else the catalogue, else an artist channel's own video
        if singers:
            ident.artists = singers
        elif cat_artists and not any(looks_like_count(a) for a in cat_artists):
            # some catalogue credits read "Rekha Bharadwaj | Backing Vocal : ..."; keep the lead name
            ident.artists = [re.split(r"\s*\|\s*", a)[0].strip() for a in cat_artists if a.strip()]
        elif m.get("artist") and not looks_like_count(m["artist"]):
            ident.artists = [m["artist"]]
        elif official and vd.get("author"):
            ident.artists = [a.strip() for a in re.split(r",\s*|\s*&\s*", vd["author"].replace(", &", ","))
                             if a.strip()]
        ident.artist = ", ".join(ident.artists)

        # album: the catalogue's release, else the film named in the credits, else the player bar
        ident.album = album_name or film or ("" if looks_like_count(m.get("album") or "") else (m.get("album") or ""))
        if looks_like_count(ident.album):
            ident.album = ""
        if film or looks_like_soundtrack(ident.album, ident.title):
            ident.secondary_types = ["Soundtrack"]
        if ident.is_soundtrack:
            # a film album is filed under its music director
            if ident.composers:
                ident.album_artist = ", ".join(ident.composers)
            elif ident.album_artist:
                ident.composers = [ident.album_artist]
        ident.album_artist = ident.album_artist or ident.artist
        if not ident.year and str(m.get("year") or info.get("year") or "").isdigit():
            ident.year = int(m.get("year") or info.get("year"))
        if ident.year and not ident.date:
            ident.date = str(ident.year)
        if not ident.album:
            ident.release_type = ident.release_type or "single"
        return ident
    except Exception as e:
        log.info("youtube music lookup failed: %s", e)
        return None


def prefer_vocals(ident: Identity) -> None:
    """When a recording is credited to its music director, show the singers as the artist.

    Indian film releases on MusicBrainz often credit the composer on the recording and name the
    singers only as vocal performers. The composer keeps the album-artist and composer tags.
    """
    if not ident.vocals:
        return
    credit = norm(ident.artist)
    composers = {norm(c) for c in ident.composers} | {norm(ident.album_artist)}
    if not credit or credit in composers or all(norm(a) in composers for a in ident.artists):
        if not ident.composers and ident.artist:
            ident.composers = [ident.artist]
        ident.artists = list(ident.vocals)
        ident.artist = ", ".join(ident.vocals)


def enrich_from_musicbrainz(ident: Identity, contact: str = "") -> None:
    """Fill composer/lyricist/singers/ISRC/label/genres/... from MusicBrainz. Best effort."""
    from . import musicbrainz as mb
    mb.set_contact(contact)
    if ident.mb_release_id:
        rel = mb.release(ident.mb_release_id)
        if rel:
            ident.album = rel["title"] or ident.album
            ident.album_artist = rel["artist"] or ident.album_artist
            ident.album_artist_sort = rel["artist_sort"]
            ident.mb_album_artist_ids = rel["artist_ids"]
            ident.date = rel["date"] or ident.date
            if ident.date[:4].isdigit():
                ident.year = int(ident.date[:4])
            ident.country = rel["country"]
            ident.status = rel["status"]
            ident.barcode = rel["barcode"]
            ident.label = rel["label"] or ident.label
            ident.catalog = rel["catalog"]
            ident.original_date = rel["original_date"]
            ident.release_type = rel["rg_type"] or ident.release_type
            if rel["rg_secondary"]:
                ident.secondary_types = list(dict.fromkeys(ident.secondary_types + rel["rg_secondary"]))
            ident.genres = rel["genres"] or ident.genres
            ident.disc_total = rel["disc_total"] or ident.disc_total
            for m in rel["media"]:
                for t in m["tracks"]:
                    if (ident.mb_recording_id and t["recording_id"] == ident.mb_recording_id) or \
                       (not ident.mb_recording_id and norm(t["title"]) == norm(ident.title)):
                        ident.track_number = t["position"] or ident.track_number
                        ident.track_total = m["track_count"] or ident.track_total
                        ident.disc_number = m["position"] or ident.disc_number
                        ident.media_format = m["format"]
                        if t["artist"]:
                            ident.artist = t["artist"]
    if ident.mb_recording_id:
        rec = mb.recording(ident.mb_recording_id)
        if rec:
            ident.artist = rec["artist"] or ident.artist
            ident.artist_sort = rec["artist_sort"]
            ident.mb_artist_ids = rec["artist_ids"] or ident.mb_artist_ids
            ident.isrc = rec["isrcs"][0] if rec["isrcs"] else ident.isrc
            ident.vocals = rec["vocals"]
            ident.performers = rec["performers"]
            prefer_vocals(ident)
            ident.producers = rec["producers"]
            if not ident.genres:
                ident.genres = rec["genres"]
            for wid in rec["works"][:2]:
                w = mb.work(wid)
                if w:
                    ident.composers = list(dict.fromkeys(ident.composers + w["composers"]))
                    ident.lyricists = list(dict.fromkeys(ident.lyricists + w["lyricists"] + w["writers"]))
                    ident.language = w["language"] or ident.language
