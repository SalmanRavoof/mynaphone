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

from . import films, genres, identify, jiosaavn, lyrics as lyr, playlists, tools
from .config import Config
from .library import classify, file_take, resolve_cover, write_lyrics, write_lyrics_sidecar
from .metadata import identity_from_row, missing_fields, refresh_track
from .store import Store, tier_rank

log = logging.getLogger("mynaphone.post")

WORDLESS_MIN_SONGS = 5      # an album's own songs count as evidence once the library holds this many of them
WORDLESS_SHARE = 0.75       # and this share of them show no sign of words


@dataclass
class Pending:
    """An inbox take the post-processor hasn't filed yet. `attempts` counts its failed tries and `last_error` says
    why the last one failed. The post-processor tries it again once `next_try`, a monotonic time, has passed."""
    path: Path
    attempts: int = 0
    next_try: float = 0.0
    last_error: str = ""


class PostProcessor(threading.Thread):
    """The thread that files the inbox's takes in the library, identified and tagged. It runs again 60 seconds after
    each pass, or sooner on `kick`, and a take it can't file yet stays in the inbox for a later try. About every 30
    minutes it runs slower jobs, such as the lyrics backfill and new lookups for songs missing metadata."""
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
        self._playlists_stale = False   # a song was filed or moved, so the playlist files need writing again
        self._film_tags_stale = False   # a song joined its film's folder, which may change its album artist or name

    def stop(self) -> None:
        """Ask the thread to stop, and wake it so it doesn't wait out the rest of its 60 seconds."""
        self._stop.set()
        self._kick.set()

    def kick(self) -> None:
        """Wake the thread to file new inbox takes without waiting out its 60 seconds. The lyrics backfill and the
        other jobs that check for new songs stop early for them."""
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
        """File the inbox's takes and run the slow jobs when they're due, then wait 60 seconds or until `kick`, over
        and over until `stop`."""
        while not self._stop.is_set():
            try:
                if not self.paused:
                    self._scan()
                    self._work()
                    if self._film_tags_stale:
                        self._film_tags_stale = False
                        self.share_film_tags()
                    if self._playlists_stale:
                        self._playlists_stale = False
                        playlists.rewrite_all(self.store, self.cfg.paths.library_dir)
                    if time.monotonic() >= self._next_jobs:
                        self._interrupted = False
                        self.fold_film_folders()
                        self.share_film_tags()
                        self.mark_instrumentals()
                        self.backfill_lyrics()
                        if not self._interrupted:
                            self.retry_incomplete()
                        if not self._interrupted:
                            self.repair_artists()
                        if not self._interrupted and self.cfg.identify.jiosaavn_credits:
                            self.fill_indian_credits()
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
                self._playlists_stale = True
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
                identify.enrich_from_musicbrainz(ident, self.cfg.identify.musicbrainz_contact, meta.get("artist", ""))
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
        """File the inbox take at `path` and return the library copy's path. It sets aside a take of a recording the
        library has, unless `upgrade_on_higher_tier` lets a higher tier replace it."""
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
        into = None
        ident.release_album = ident.release_album or ident.album
        if classify(ident) == "soundtrack":
            rows = films.soundtrack_rows(self.store)
            into = films.folder_for(self.cfg.paths.library_dir, rows, ident.album, ident.title, ident.year)
            if into is not None:
                # it takes the album artist its film's songs share, which its own credit can narrow for all of them,
                # and their album name, which a single joins after the album's songs
                films.take_album_artist(ident, films.album_artist_for(self.cfg.paths.library_dir, rows, into,
                                                                      films.credit_from(ident)))
                films.take_film_tags(ident, films.film_tags_for(self.cfg.paths.library_dir, rows, into,
                                                                films.song_from(ident)))
                self._film_tags_stale = True
        dst = file_take(path, self.cfg.paths.library_dir, ident, self.cfg.library.format,
                        self.cfg.library.aac_bitrate, text, capture, cover, into=into)
        missing = missing_fields(ident, cover is not None, lyr_state)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        if row:
            shown = films.tagged_as(ident)
            self.store.conn.execute(
                "UPDATE tracks SET file_path=?, state='library', title=?, artist=?, album=?, album_artist=?, "
                "track_number=?, lyrics_state=?, lyrics_tries=?, lyrics_tried_at=?, identity_json=?, missing_json=?, "
                "last_lookup=?, lookup_tries=1 WHERE id=?",
                (str(dst), ident.title, ident.artist, shown.album, ident.album_artist, shown.track_number,
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

    # -- one folder per film ----------------------------------------------------------------

    def fold_film_folders(self) -> int:
        """Gather each film's songs in one folder under Soundtracks (films.py). New songs go to their film's folder
        when they're filed; this folds the ones filed apart before, or before their film's album arrived. Every move
        goes into folder-moves.json next to the index, so it can be undone by hand."""
        moves = films.plan(self.cfg.paths.library_dir, films.soundtrack_rows(self.store))
        if not moves:
            return 0
        done = films.apply(self.store, moves, self.cfg.paths.db_path.parent / "folder-moves.json")
        if done:
            log.info("gathered %d songs into their films' folders", done)
            playlists.rewrite_all(self.store, self.cfg.paths.library_dir)
        return done

    def share_film_tags(self) -> int:
        """Give each film's songs one album artist (films.shared_album_artist), with the sort name and MusicBrainz ids
        that go with it, and one album name (films.shared_album), numbering the film's singles after its album's songs.
        Songs matched to 2 MusicBrainz releases of a film carried both credits, and a film's singles kept their own
        album names, so a player that groups by album artist showed Aashiq Banaya Aapne twice, and one that groups by
        album name showed Leo 5 times. A new song takes its film's values when it's filed; this re-tags the songs
        filed before, and a film's other songs when a new one changes them. An album artist, album or track number
        typed in the Library editor never changes. Every change goes into album-artists.json or album-names.json next
        to the index, so it can be undone by hand. Returns how many songs it re-tagged."""
        rows = films.soundtrack_rows(self.store)
        ids = sorted({ch.track_id for ch in films.album_artist_plan(self.cfg.paths.library_dir, rows)}
                     | {ch.track_id for ch in films.album_plan(self.cfg.paths.library_dir, rows)})
        artists, albums = [], []
        for track_id in ids:
            if self._stop.is_set():
                break
            row = self.store.track(track_id)
            if row is None:
                continue
            name = Path(row["file_path"] or "").name
            artist, album = films.tagged(row), films.tagged_album(row)
            try:
                res = refresh_track(self.cfg, self.store, row, lookup=False, move=False)
            except Exception as e:
                log.warning("could not give %s its film's album artist and album: %s", name, e)
                continue
            now = self.store.track(track_id)
            new_artist, new_album = films.tagged(now), films.tagged_album(now)
            if new_artist != artist:
                artists.append({"file": res["path"], "from": artist.name, "to": new_artist.name,
                                "sort": [artist.sort, new_artist.sort],
                                "ids": [list(artist.ids), list(new_artist.ids)]})
                log.info("album artist of %s: %s -> %s", name, artist.name, new_artist.name)
            if new_album != album:
                albums.append({"file": res["path"], "from": album[0], "to": new_album[0],
                               "track": [list(album[1:]), list(new_album[1:])]})
                log.info("album of %s: %s, track %d of %d -> %s, track %d of %d", name, album[0], album[1], album[2],
                         new_album[0], new_album[1], new_album[2])
        folder = self.cfg.paths.db_path.parent
        if artists:
            films.append_record(folder / "album-artists.json", artists)
            log.info("gave %d songs the album artist their film's songs share, with its sort name and ids",
                     len(artists))
        if albums:
            films.append_record(folder / "album-names.json", albums)
            log.info("gave %d songs the album name their film's songs share, with a single's track number after the "
                     "album's", len(albums))
        return len({a["file"] for a in artists} | {a["file"] for a in albums})

    # -- artist credits --------------------------------------------------------------------

    def repair_artists(self, limit: int = 50) -> int:
        """Put back the artist of songs that got their singers instead: Metallica's songs as James Hetfield, Queen's
        as Brian May and Freddie Mercury. Until October 30 the singers replaced any recording credit that matched the
        album artist, which every band's album does. A song qualifies when its artist is its singers and it has no
        stored MusicBrainz credit; it gets the credit read again, the corrected rule applied, and its file re-tagged.
        The credit is stored then, so each song is read once."""
        from . import musicbrainz as mb
        mb.set_contact(self.cfg.identify.musicbrainz_contact)
        fixed = 0
        rows = self.store.conn.execute(
            "SELECT * FROM tracks WHERE state='library' AND identity_json LIKE '%\"vocals\": [\"%'").fetchall()
        for r in rows:
            if fixed >= limit or self._stop.is_set() or self._new_song_waiting():
                break
            ident = identity_from_row(r)
            if (ident.credit or not ident.mb_recording_id or not ident.vocals
                    or ident.artist != ", ".join(ident.vocals)):
                continue
            try:
                rec = mb.recording(ident.mb_recording_id)
            except Exception as e:
                log.info("artist repair paused (%s)", e)
                break
            before = ident.artist
            if rec is None:
                ident.credit = ident.artist     # gone from MusicBrainz: leave the song as it is, and don't ask again
            else:
                ident.credit = rec["artist"] or ident.artist
                ident.artist = ident.credit
                ident.artists = [n for n in rec.get("artist_names") or [] if n] or [ident.credit]
                ident.vocals = list(dict.fromkeys(rec["vocals"]))
                identify.prefer_vocals(ident, self.store.played_artist(r), rec.get("artist_names"))
            self.store.conn.execute("UPDATE tracks SET identity_json=? WHERE id=?",
                                    (json.dumps(ident.to_json(), ensure_ascii=False), int(r["id"])))
            self.store.conn.commit()
            if ident.artist == before:
                continue
            try:
                refresh_track(self.cfg, self.store, self.store.track(int(r["id"])), lookup=False, move=False)
            except Exception as e:
                log.warning("could not re-tag %s: %s", Path(r["file_path"] or "").name, e)
                continue
            fixed += 1
            log.info("artist of %s: %s -> %s", ident.title, before, ident.artist)
        if fixed:
            log.info("put back the artist of %d songs", fixed)
        return fixed

    # -- Indian film credits ---------------------------------------------------------------

    def fill_indian_credits(self, limit: int = 20) -> int:
        """Lyricist and composer from JioSaavn for Indian film songs that have none (jiosaavn.py). Each song is
        asked about once a month at most; JioSaavn being unreachable isn't counted as an answer."""
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat()
        rows = self.store.conn.execute(
            "SELECT * FROM tracks WHERE state='library' AND COALESCE(lyrics_state,'') != 'instrumental' "
            "AND (missing_json LIKE '%lyricists%' OR missing_json LIKE '%composers%') "
            "AND (credits_tried_at IS NULL OR credits_tried_at < ?) ORDER BY credits_tried_at IS NOT NULL, id",
            (cutoff,)).fetchall()
        filled = asked = 0
        for r in rows:
            if asked >= limit or self._stop.is_set() or self._new_song_waiting():
                break
            ident = identity_from_row(r)
            played = self.store.played_artist(r)
            indian = (classify(ident) == "soundtrack"
                      or jiosaavn.language_hint(ident.title, ident.album, ident.language))
            if not indian:
                continue
            artists = list(dict.fromkeys([*(ident.artists or []), *identify._names_list(ident.artist),
                                          *identify._names_list(played)]))
            asked += 1
            try:
                found = jiosaavn.credits_for(ident.title, artists, ident.album, (r["duration_ms"] or 0) / 1000.0,
                                             ident.language)
            except jiosaavn.Unavailable as e:
                log.info("Indian film credits paused: %s", e)
                break
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            self.store.conn.execute("UPDATE tracks SET credits_tried_at=? WHERE id=?", (now, int(r["id"])))
            self.store.conn.commit()
            if found is None:
                continue
            gained = []
            if found.lyricists and not ident.lyricists:
                ident.lyricists = list(found.lyricists)
                gained.append("lyricist")
            if found.composers and not ident.composers:
                ident.composers = list(found.composers)
                gained.append("composer")
            if not gained:
                continue
            ident.credits_from = f"JioSaavn {found.song_id} ({found.copies} copies, vcode {found.vcode})"
            self.store.conn.execute("UPDATE tracks SET identity_json=? WHERE id=?",
                                    (json.dumps(ident.to_json(), ensure_ascii=False), int(r["id"])))
            self.store.conn.commit()
            try:
                refresh_track(self.cfg, self.store, self.store.track(int(r["id"])), lookup=False, move=False)
            except Exception as e:
                log.warning("could not re-tag %s: %s", Path(r["file_path"] or "").name, e)
                continue
            filled += 1
            log.info("%s for %s - %s from JioSaavn: %s", " and ".join(gained), r["artist"], r["title"],
                     "; ".join(ident.lyricists + ident.composers))
        return filled

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
            album = ident.mb_release_id or f"{ident.album.casefold()}|{(r['album_artist'] or '').casefold()}"
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
            ident = identity_from_row(full)     # its own album, which a single's lyrics are filed under
            if identify.has_no_words(ident, self.store.played_title(full)):
                got = lyr.Lyrics(instrumental=True)     # it says so itself; no lookup needed
            else:
                try:
                    got = lyr.fetch(r["title"], r["artist"], ident.album, (r["duration_ms"] or 0) / 1000.0)
                except lyr.Unavailable as e:
                    self._lyrics_tried(int(r["id"]), now)
                    if e.retry_after <= lyr.SHORT_WAIT_SECONDS:
                        # busy with this song's searches only (its first live run stopped at one): try the next
                        time.sleep(e.retry_after)
                        continue
                    log.info("lyrics backfill paused: %s; trying again in %.0f min", e, e.retry_after / 60)
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
