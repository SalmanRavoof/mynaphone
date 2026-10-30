# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Post-processor: turns verified inbox takes into fully tagged library files.

Runs on its own thread, scans the inbox periodically and on demand, and never loses a take: when
the network is down the identification is retried later with backoff, and the file stays in the
inbox until it has been filed. A second job backfills lyrics for library songs that have none.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import genres, identify, lyrics as lyr, tools
from .config import Config
from .library import file_take, resolve_cover, write_lyrics, write_lyrics_sidecar
from .metadata import identity_from_row, missing_fields, refresh_track
from .store import Store, tier_rank

log = logging.getLogger("mynaphone.post")

WORDLESS_MIN_SONGS = 5      # an album's own songs count as evidence once the library holds this many of them
WORDLESS_SHARE = 0.75       # and this share of them show no sign of words


@dataclass
class Pending:
    path: Path
    attempts: int = 0
    next_try: float = 0.0
    last_error: str = ""


class PostProcessor(threading.Thread):
    def __init__(self, cfg: Config, store: Store, on_event=None):
        super().__init__(name="postprocessor", daemon=True)
        self.cfg = cfg
        self.store = store
        self.on_event = on_event
        self._stop = threading.Event()
        self._kick = threading.Event()
        self.pending: dict[str, Pending] = {}
        self.paused = False
        self._next_jobs = 0.0           # when the lyrics backfill and the retry of incomplete songs run next
        self._interrupted = False       # a job stopped early so a new song could be filed

    def stop(self) -> None:
        self._stop.set()
        self._kick.set()

    def kick(self) -> None:
        self._kick.set()

    def _new_song_waiting(self) -> bool:
        """The recorder kept a song: the slow jobs stop so it's filed without waiting for them."""
        if self._kick.is_set():
            self._interrupted = True
            return True
        return False

    def _emit(self, kind: str, **data) -> None:
        if self.on_event:
            try:
                self.on_event({"kind": kind, **data})
            except Exception:
                log.exception("post event listener failed")

    # -- main loop -------------------------------------------------------------------------

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                if not self.paused:
                    self._scan()
                    self._work()
                    if time.monotonic() >= self._next_jobs:
                        self._interrupted = False
                        self.mark_instrumentals()
                        self.backfill_lyrics()
                        if not self._interrupted:
                            self.retry_incomplete()
                        # a run cut short for a new song picks up again soon; otherwise every half hour
                        self._next_jobs = time.monotonic() + (120 if self._interrupted else 1800)
            except Exception:
                log.exception("post-processor loop failed")
            self._kick.wait(60.0)
            self._kick.clear()

    def _scan(self) -> None:
        inbox = self.cfg.paths.inbox_dir
        for flac in sorted(inbox.glob("*.flac")):
            key = str(flac)
            if key not in self.pending and flac.with_suffix(".json").exists():
                self.pending[key] = Pending(flac)

    def _work(self) -> None:
        now = time.monotonic()
        for key, p in list(self.pending.items()):
            if self._stop.is_set():
                return
            if p.next_try > now or not p.path.exists():
                if not p.path.exists():
                    self.pending.pop(key, None)
                continue
            try:
                self.process(p.path)
                self.pending.pop(key, None)
            except (identify.ToolMissing, OSError) as e:
                p.attempts += 1
                p.last_error = str(e)
                p.next_try = time.monotonic() + min(3600, 60 * 2 ** min(p.attempts, 6))
                log.warning("deferred %s: %s (retry in %.0f s)", p.path.name, e, p.next_try - time.monotonic())
                self._emit("deferred", path=str(p.path), error=str(e))
            except Exception as e:
                p.attempts += 1
                p.last_error = str(e)
                p.next_try = time.monotonic() + min(3600, 120 * 2 ** min(p.attempts, 5))
                log.exception("failed to file %s", p.path.name)
                self._emit("deferred", path=str(p.path), error=str(e))

    # -- one take --------------------------------------------------------------------------

    def identify_take(self, path: Path, meta: dict) -> tuple[identify.Identity, str]:
        """Fingerprint -> AcoustID -> MusicBrainz enrichment, else Spotify/tag fallback."""
        note = ""
        ident = None
        key = self.cfg.identify.acoustid_key.strip()
        if key and tools.fpcalc():
            try:
                hints = dict(hint_album=meta.get("album", ""), hint_track=int(meta.get("track_number") or 0),
                             hint_artist=meta.get("artist", ""), hint_title=meta.get("title", ""))
                ident, note = identify.lookup_with_retry(key, str(path), hints)
            except identify.ToolMissing:
                raise
            except Exception as e:
                raise OSError(f"identification unavailable: {e}") from e
        elif not key:
            note = "no AcoustID key configured"
        else:
            raise identify.ToolMissing("fpcalc not found")

        if ident is None:
            yt = identify.from_youtube(meta) if (meta.get("extra") or {}).get("youtube") else None
            ident = yt or identify.from_tags(meta)
            if yt:
                note = (note + "; " if note else "") + "YouTube Music catalogue"
        else:
            try:
                identify.enrich_from_musicbrainz(ident, self.cfg.identify.musicbrainz_contact)
            except OSError as e:
                # the network or MusicBrainz is down: the song stays in the inbox for another try
                raise OSError(f"musicbrainz unavailable: {e}") from e
            except Exception:
                # a reply this code can't read mustn't hold the song back forever; file it without those details
                log.exception("could not read MusicBrainz's details for %s; filing without them", path.name)
            if not ident.track_number and meta.get("track_number"):
                ident.track_number = int(meta["track_number"])
            if not ident.is_soundtrack and identify.looks_like_soundtrack(meta.get("album", ""),
                                                                          meta.get("title", "")):
                ident.secondary_types.append("Soundtrack")
            identify.apply_spotify(ident, meta)
        genres.resolve(ident, meta.get("artist", ""), (meta.get("expected_ms") or 0) / 1000.0, self.cfg)
        return ident, note

    def process(self, path: Path) -> Path:
        side = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        meta = side.get("meta", {})
        duration_s = (meta.get("expected_ms") or 0) / 1000.0
        capture = {
            "source_app": meta.get("app", ""), "source_uri": meta.get("source_uri", ""),
            "quality_tier": meta.get("quality_tier", ""), "captured_at": meta.get("started_at", ""),
            "capture_format": f"{side.get('capture', {}).get('rate', '')}Hz/"
                              f"{side.get('capture', {}).get('bit_depth', '')}bit loopback",
        }
        ident, note = self.identify_take(path, meta)
        row = self.store.conn.execute("SELECT id FROM tracks WHERE file_path=?", (str(path),)).fetchone()
        twin = self.store.find_recording(ident.mb_recording_id, ident.isrc, int(row["id"]) if row else None)
        if twin is not None and not (self.cfg.quality.upgrade_on_higher_tier
                                     and tier_rank(capture["quality_tier"]) > tier_rank(twin["quality_tier"])):
            return self._set_aside(path, meta, row, twin)

        text, lyr_state = "", "none"
        sp = (meta.get("extra") or {}).get("spotify_lyrics") or {}
        if sp.get("lrc"):
            # Spotify's own lyrics match the exact recording and cover languages LRCLIB often lacks
            text = sp["lrc"]
            lyr_state = "synced" if sp.get("synced") else "plain"
            if sp.get("language") and not ident.language:
                ident.language = sp["language"]
        if not text and identify.has_no_words(ident, meta.get("title", "")):
            lyr_state = "instrumental"      # nothing to look up
        tried = False
        if lyr_state not in ("synced", "instrumental"):
            try:
                got = lyr.fetch(ident.title, ident.artist or meta.get("artist", ""), ident.album, duration_s)
                tried = True
                if got and got.instrumental and not text:
                    lyr_state = "instrumental"
                elif got and got.synced:
                    text, lyr_state = got.synced, "synced"
                elif got and got.plain and not text:
                    text, lyr_state = got.plain, "plain"
            except Exception as e:
                log.info("lyrics lookup failed for %s: %s (will retry later)", ident.title, e)

        cover = resolve_cover(path, ident, meta.get("cover_url", ""))
        dst = file_take(path, self.cfg.paths.library_dir, ident, self.cfg.library.format,
                        self.cfg.library.aac_bitrate, text, capture, cover)
        missing = missing_fields(ident, cover is not None, lyr_state)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        if row:
            self.store.conn.execute(
                "UPDATE tracks SET file_path=?, state='library', title=?, artist=?, album=?, album_artist=?, "
                "track_number=?, lyrics_state=?, lyrics_tries=?, lyrics_tried_at=?, identity_json=?, missing_json=?, "
                "last_lookup=?, lookup_tries=1 WHERE id=?",
                (str(dst), ident.title, ident.artist, ident.album, ident.album_artist, ident.track_number,
                 lyr_state, 1 if tried else 0, now if tried else None, json.dumps(ident.to_json(), ensure_ascii=False),
                 json.dumps(missing), now, int(row["id"])))
            self.store.conn.commit()
        if twin is not None:
            self._retire(twin, dst, row)
        try:
            path.unlink()
            path.with_suffix(".json").unlink()
        except OSError:
            pass
        log.info("FILED %s -> %s (%s%s)", path.name, dst.relative_to(self.cfg.paths.library_dir), ident.source,
                 f", {note}" if note else "")
        self._emit("filed", title=ident.title, artist=ident.artist, album=ident.album, path=str(dst),
                   identified_by=ident.source, lyrics=bool(text), synced=lyr_state == "synced", note=note,
                   missing=missing)
        return dst

    def _set_aside(self, path: Path, meta: dict, row, twin) -> Path:
        """The take is a song already in the library, recorded again from its single or its album. Keep the filed
        copy, remember this player id for it so the next play is skipped, and move the take to the discard folder
        like any rejected take."""
        self.store.add_alias(meta.get("source_uri", ""), int(twin["id"]))
        if row is not None:
            self.store.conn.execute("DELETE FROM tracks WHERE id=?", (int(row["id"]),))
            self.store.conn.commit()
        keep = self.cfg.rules.keep_discards_days > 0
        target = self.cfg.paths.discard_dir / path.name
        for p in (path, path.with_suffix(".json")):
            try:
                if keep:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    p.replace(target.parent / p.name)
                else:
                    p.unlink()
            except OSError as e:
                log.warning("could not set %s aside: %s", p.name, e)
        self.store.conn.execute("UPDATE takes SET file_path=? WHERE file_path=?",
                                (str(target) if keep else None, str(path)))
        self.store.conn.commit()
        log.info("DUPLICATE %s is the same recording as %s; set aside", path.name, twin["file_path"])
        self._emit("duplicate", title=meta.get("title", ""), artist=meta.get("artist", ""), path=twin["file_path"])
        return Path(twin["file_path"])

    def _retire(self, twin, dst: Path, row) -> None:
        """A better copy of a song already filed takes its place and its player ids."""
        old = Path(twin["file_path"]) if twin["file_path"] else None
        if old is not None and old != dst:
            for p in (old, old.with_suffix(".lrc")):
                try:
                    p.unlink(missing_ok=True)
                except OSError as e:
                    log.warning("could not remove the older copy %s: %s", p.name, e)
        if row is not None:
            self.store.conn.execute("UPDATE aliases SET track_id=? WHERE track_id=?", (int(row["id"]), int(twin["id"])))
            self.store.add_alias(twin["source_uri"] or "", int(row["id"]))
        self.store.conn.execute("DELETE FROM tracks WHERE id=?", (int(twin["id"]),))
        self.store.conn.commit()
        log.info("replaced the %s copy of %s - %s with this one", twin["quality_tier"], twin["artist"], twin["title"])

    # -- retry incomplete songs ------------------------------------------------------------

    def retry_incomplete(self, limit: int = 10) -> int:
        """Look up again songs that still have gaps, at most once a week each. Manual edits are kept."""
        done = 0
        for row in self.store.incomplete_for_retry(limit=limit):
            if self._stop.is_set() or self._new_song_waiting():
                break
            try:
                before = json.loads(row["missing_json"] or "[]")
                res = refresh_track(self.cfg, self.store, row, lookup=True, move=False)
                gained = [m for m in before if m not in res["missing"]]
                if gained:
                    done += 1
                    log.info("filled %s for %s - %s", ", ".join(gained), row["artist"], row["title"])
                    self._emit("refreshed", title=row["title"], artist=row["artist"],
                               gained=gained, missing=res["missing"])
            except Exception as e:
                log.info("retry failed for %s: %s", row["title"], e)
                break
        return done

    # -- instrumentals ---------------------------------------------------------------------

    def mark_instrumentals(self) -> int:
        """Mark library songs without lyrics as instrumental where something says they have no words.

        A song counts when MusicBrainz gives it the "no lyrics" language, when its title (the player's too) or album
        says Instrumental, when the album is a film's or a game's score, or when it has no lyricist or singer
        credited and sits on an album with at least 5 songs here, 3 in 4 of them without words. On October 30 that
        covered 170 of the 217 library songs without lyrics, from Guild Wars 2, Divinity, Baldur's Gate 3, Casino
        Royale and the Karuppu score. Marking them ends lyrics lookups that can't succeed and takes lyrics and
        lyricist off their missing lists. A song set to having vocals in the Library editor is left alone."""
        rows = self.store.conn.execute("SELECT * FROM tracks WHERE state='library'").fetchall()
        albums = collections.defaultdict(list)
        songs = []
        for r in rows:
            ident = identity_from_row(r)
            credited = bool(ident.lyricists or ident.vocals)
            wordless = (r["lyrics_state"] == "instrumental" or (ident.language or "").lower() == "zxx"
                        or (r["lyrics_state"] in (None, "none") and not credited))
            album = ident.mb_release_id or f"{(r['album'] or '').casefold()}|{(r['album_artist'] or '').casefold()}"
            albums[album].append(wordless)
            if r["lyrics_state"] in (None, "none"):
                songs.append((r, ident, credited, album))
        scores = {a for a, w in albums.items() if len(w) >= WORDLESS_MIN_SONGS and sum(w) >= WORDLESS_SHARE * len(w)}
        marked = 0
        for r, ident, credited, album in songs:
            try:
                if json.loads(r["manual_json"] or "{}").get("instrumental") is False:
                    continue
            except (TypeError, ValueError):
                pass
            if identify.has_no_words(ident, self.store.played_title(r)) or (album in scores and not credited):
                miss = [m for m in json.loads(r["missing_json"] or "[]")
                        if m not in ("lyrics", "synced_lyrics", "lyricists")]
                self.store.conn.execute("UPDATE tracks SET lyrics_state='instrumental', missing_json=? WHERE id=?",
                                        (json.dumps(miss), int(r["id"])))
                marked += 1
        if marked:
            self.store.conn.commit()
            log.info("marked %d songs as instrumental", marked)
        return marked

    # -- lyrics backfill -------------------------------------------------------------------

    def backfill_lyrics(self, limit: int = 20) -> int:
        """Look again for lyrics for library songs that have none, up to 10 tries each, at most `limit` songs a run.

        A song whose last try failed goes to the back of the line, so it can't hold up the rest. The run stops when
        LRCLIB asks for a pause (it answered 503 to every run for weeks while each run sent dozens of requests back
        to back) or when a new song is waiting to be filed."""
        if lyr.paused_for():
            return 0
        rows = self.store.conn.execute(
            "SELECT id, file_path, title, artist, album, duration_ms, lyrics_tries FROM tracks "
            "WHERE state='library' AND (lyrics_state IS NULL OR lyrics_state='none') AND COALESCE(lyrics_tries,0) < 10 "
            "ORDER BY lyrics_tried_at IS NOT NULL, lyrics_tried_at, id LIMIT ?", (limit,)).fetchall()
        done = checked = 0
        for r in rows:
            if self._stop.is_set() or self._new_song_waiting():
                break
            path = Path(r["file_path"] or "")
            if not path.exists():
                continue
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            full = self.store.track(int(r["id"]))
            if identify.has_no_words(identity_from_row(full), self.store.played_title(full)):
                got = lyr.Lyrics(instrumental=True)     # it says so itself; no lookup needed
            else:
                try:
                    got = lyr.fetch(r["title"], r["artist"], r["album"] or "", (r["duration_ms"] or 0) / 1000.0)
                except lyr.Unavailable as e:
                    log.info("lyrics backfill paused: %s; trying again in %.0f min", e, e.retry_after / 60)
                    self._lyrics_tried(int(r["id"]), now)
                    break
                except Exception as e:
                    log.info("lyrics backfill paused (%s)", e)
                    self._lyrics_tried(int(r["id"]), now)
                    break
            checked += 1
            state = "none"
            if got and got.instrumental:
                state = "instrumental"
            elif got and got.best:
                state = "synced" if got.synced else "plain"
                try:
                    write_lyrics(path, got.best)
                    write_lyrics_sidecar(path, got.best)
                    done += 1
                    log.info("lyrics added (%s): %s - %s", state, r["artist"], r["title"])
                    self._emit("lyrics", title=r["title"], artist=r["artist"], synced=state == "synced")
                except Exception as e:
                    log.warning("could not write lyrics to %s: %s", path.name, e)
                    state = "none"
            miss = json.loads(self.store.track(int(r["id"]))["missing_json"] or "[]")
            if state in ("plain", "synced", "instrumental"):
                miss = [m for m in miss if m != "lyrics" and (m != "synced_lyrics" or state == "plain")]
            if state == "instrumental":
                miss = [m for m in miss if m != "lyricists"]
            self.store.conn.execute(
                "UPDATE tracks SET lyrics_state=?, lyrics_tries=COALESCE(lyrics_tries,0)+1, lyrics_tried_at=?, "
                "missing_json=? WHERE id=?", (state, now, json.dumps(miss), int(r["id"])))
            self.store.conn.commit()
        if checked:
            log.info("lyrics backfill: %d songs checked, %d got lyrics", checked, done)
        return done

    def _lyrics_tried(self, track_id: int, when: str) -> None:
        """A try that got no answer doesn't count against the song, but sends it to the back of the line."""
        self.store.conn.execute("UPDATE tracks SET lyrics_tried_at=? WHERE id=?", (when, track_id))
        self.store.conn.commit()
