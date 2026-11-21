# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""The settings in config.toml, one dataclass for each section of the file.

`Config.load` reads the file, and `Config.save` writes the settings back to it. docs/settings.md explains what each
setting does.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import browsers


@dataclass
class Paths:
    """The `[paths]` section lists the folders and files Mynaphone works with. A relative path counts from the folder
    config.toml is in."""
    inbox_dir: Path
    discard_dir: Path
    library_dir: Path
    db_path: Path
    log_dir: Path


@dataclass
class Capture:
    """The `[capture]` section sets how Mynaphone records audio. Its `mode` is "process" by default, so Mynaphone
    records the source app's audio alone. With "device", it records the whole output device."""
    mode: str = "process"        # process (per-app, nothing else can bleed in) | device (whole output device)
    device: str = "default"
    sample_rate: int = 0
    bit_depth: int = 16
    preroll_seconds: float = 3.0
    lead_margin_seconds: float = 0.5


@dataclass
class Rules:
    """The `[rules]` section decides what Mynaphone records and which takes it keeps. It also has the settings for
    harvest mode and the silence warning."""
    sources: list[str] = field(default_factory=lambda: ["Spotify.exe"])
    duration_tolerance_seconds: float = 1.5
    min_duration_seconds: float = 10.0               # ads are told apart by the Spotify bridge, not by length
    max_duration_seconds: float = 900.0          # longer items (podcasts, mixes) are never recorded
    discard_on_pause: bool = True
    discard_on_seek: bool = True
    ignore_titles: list[str] = field(default_factory=lambda: ["Advertisement", "Spotify"])
    keep_discards_days: int = 3
    discard_on_foreign_audio: bool = True
    foreign_audio_threshold_db: float = -120.0   # <= -100 means any sound at all
    harvest_mode: bool = False                   # skip songs already archived so a queue captures only new ones
    silence_warning_seconds: float = 15.0        # warn when a song plays this long with no sound reaching us; 0 = off

    def is_source(self, app_id: str) -> bool:
        """True when `app_id` is one of `sources`, or ends with one, ignoring case."""
        a = (app_id or "").lower()
        return any(a == s.lower() or a.endswith(s.lower()) for s in self.sources)

    def is_ignored_title(self, title: str) -> bool:
        """True when `title` is empty or matches one of `ignore_titles`. Case and the spaces around `title` don't
        count."""
        t = (title or "").strip().lower()
        return not t or t in {s.lower() for s in self.ignore_titles}


@dataclass
class Bridge:
    """The `[bridge]` section sets up the local WebSocket server the 2 bridges connect to. `enabled` turns it on and
    off, and both bridges look for it on port 8765, the default `port`."""
    enabled: bool = True
    port: int = 8765


@dataclass
class Quality:
    """The `[quality]` setting, `upgrade_on_higher_tier`, is on by default and makes Mynaphone record a song again
    when it plays at a higher tier than your copy."""
    upgrade_on_higher_tier: bool = True


@dataclass
class Library:
    """The `[library]` section sets the format and bitrate of the songs filed in your library. A take from a lossless
    tier stays FLAC whatever `format` says."""
    format: str = "aac"          # aac | mp3 | opus | flac  (lossless-tier captures always stay flac)
    aac_bitrate: int = 256       # kbps for the lossy formats (name kept for compatibility)

    @property
    def bitrate(self) -> int:
        """`aac_bitrate` as a whole number, in kbps, for every lossy format. The setting keeps its old name so
        existing config files still load."""
        return int(self.aac_bitrate)


@dataclass
class Identify:
    """The `[identify]` section gives the song lookups their keys and options. AcoustID needs a key and Last.fm's is
    optional."""
    acoustid_key: str = ""          # application API key from acoustid.org/my-applications
    musicbrainz_contact: str = ""   # email or URL MusicBrainz asks clients to send in User-Agent
    lastfm_api_key: str = ""        # optional, from last.fm/api/account/create; used for genres
    apple_country: str = "US"       # Apple storefront searched for genres (a two-letter country code)
    jiosaavn_credits: bool = False  # fill Indian film songs' lyricist and composer from JioSaavn (unofficial API)


@dataclass
class Albums:
    """The `[albums]` setting, `wanted_min_songs`, puts an album you don't have whole on the Wanted list once you
    have that many of its songs and haven't taken it off. With 0, only the albums you add yourself go on it."""
    wanted_min_songs: int = 3       # an album you don't have whole is wanted once you have this many of its songs


@dataclass
class App:
    """The `[app]` section sets how the window opens and closes and whether recording starts when the app opens. It
    also has the tooltip switch."""
    start_minimized: bool = True        # when Windows starts the app; opened by hand, the window always shows
    close_to_tray: bool = True
    autostart_recording: bool = True
    show_tooltips: bool = True


@dataclass
class Config:
    """Everything in config.toml, one field for each section, plus `source_file`, the file it came from."""
    paths: Paths
    capture: Capture
    rules: Rules
    bridge: Bridge
    quality: Quality
    library: Library
    identify: Identify
    app: App
    source_file: Path
    albums: Albums = field(default_factory=Albums)

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        """Read the config.toml at `path`. A section or setting the file leaves out takes its default, and a relative
        path counts from the file's folder. It also makes any working folder that's missing, though never the library
        folder. And it adds newer browsers to a `sources` list that the YouTube option wrote before Mynaphone
        supported them."""
        path = Path(path).resolve()
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        base = path.parent

        def p(key: str, default: str) -> Path:
            v = raw.get("paths", {}).get(key, default)
            v = Path(v)
            return v if v.is_absolute() else (base / v).resolve()

        paths = Paths(
            inbox_dir=p("inbox_dir", "inbox"),
            discard_dir=p("discard_dir", "discard"),
            library_dir=p("library_dir", "library"),
            db_path=p("db_path", "mynaphone.db"),
            log_dir=p("log_dir", "logs"),
        )
        rules = Rules(**raw.get("rules", {}))
        rules.sources = browsers.with_new_browsers(rules.sources)
        cfg = cls(
            paths=paths,
            capture=Capture(**raw.get("capture", {})),
            rules=rules,
            bridge=Bridge(**raw.get("bridge", {})),
            quality=Quality(**raw.get("quality", {})),
            library=Library(**raw.get("library", {})),
            identify=Identify(**raw.get("identify", {})),
            app=App(**raw.get("app", {})),
            source_file=path,
            albums=Albums(**raw.get("albums", {})),
        )
        for d in (paths.inbox_dir, paths.discard_dir, paths.log_dir, paths.db_path.parent):
            d.mkdir(parents=True, exist_ok=True)
        return cfg

    def save(self, path: str | Path | None = None) -> Path:
        """Write the settings to `path`, or to the file they came from when there's no `path`. It rebuilds the file
        from a template with a comment above most settings, so it drops anything you added by hand."""
        path = Path(path) if path else self.source_file
        path.write_text(TEMPLATE.format(
            inbox_dir=_s(self.paths.inbox_dir), discard_dir=_s(self.paths.discard_dir),
            library_dir=_s(self.paths.library_dir), db_path=_s(self.paths.db_path), log_dir=_s(self.paths.log_dir),
            mode=_s(self.capture.mode), device=_s(self.capture.device),
            sample_rate=self.capture.sample_rate, bit_depth=self.capture.bit_depth,
            preroll=self.capture.preroll_seconds, lead=self.capture.lead_margin_seconds,
            sources=_list(self.rules.sources), tolerance=self.rules.duration_tolerance_seconds,
            min_duration=self.rules.min_duration_seconds, max_duration=self.rules.max_duration_seconds,
            discard_on_pause=_b(self.rules.discard_on_pause),
            discard_on_seek=_b(self.rules.discard_on_seek), ignore_titles=_list(self.rules.ignore_titles),
            keep_discards_days=self.rules.keep_discards_days,
            discard_on_foreign_audio=_b(self.rules.discard_on_foreign_audio),
            foreign_audio_threshold_db=self.rules.foreign_audio_threshold_db,
            harvest_mode=_b(self.rules.harvest_mode), silence_warning=self.rules.silence_warning_seconds,
            bridge_enabled=_b(self.bridge.enabled), bridge_port=self.bridge.port,
            upgrade=_b(self.quality.upgrade_on_higher_tier),
            lib_format=_s(self.library.format), aac_bitrate=self.library.aac_bitrate,
            acoustid_key=_s(self.identify.acoustid_key), musicbrainz_contact=_s(self.identify.musicbrainz_contact),
            lastfm_api_key=_s(self.identify.lastfm_api_key), apple_country=_s(self.identify.apple_country),
            jiosaavn_credits=_b(self.identify.jiosaavn_credits),
            wanted_min_songs=self.albums.wanted_min_songs,
            start_minimized=_b(self.app.start_minimized), close_to_tray=_b(self.app.close_to_tray),
            autostart_recording=_b(self.app.autostart_recording), show_tooltips=_b(self.app.show_tooltips),
        ), encoding="utf-8")
        return path


def _s(v) -> str:
    return '"' + str(v).replace("\\", "/").replace('"', '\\"') + '"'


def _b(v: bool) -> str:
    return "true" if v else "false"


def _list(v: list[str]) -> str:
    return "[" + ", ".join(_s(x) for x in v) + "]"


TEMPLATE = """# mynaphone configuration. Paths may be absolute or relative to this file.

[paths]
inbox_dir = {inbox_dir}       # verified complete takes land here, provisionally tagged
discard_dir = {discard_dir}   # rejected takes (kept for inspection, auto-pruned)
library_dir = {library_dir}   # final organized library (phase 2)
db_path = {db_path}
log_dir = {log_dir}

[capture]
# "process": capture only the source app's own audio (per-app loopback; nothing else can bleed in).
# "device": capture the whole output device (older method; other apps' sounds end up in the mix).
mode = {mode}
# Device mode only. "default" follows the Windows default playback device; "CABLE Output" for VB-CABLE.
device = {device}
# Sample rate. In process mode this is the capture rate (48000 matches Spotify's 48 kHz path on this PC;
# use 44100 for a bit-exact lossless chain). In device mode 0 = whatever the device mixes at.
sample_rate = {sample_rate}
# 16 is right for lossy sources (Spotify Free/Premium, YouTube). Use 24 for Spotify Lossless.
bit_depth = {bit_depth}
# Seconds of audio kept in memory at all times, so a late track-change event loses nothing.
preroll_seconds = {preroll}
# How far before the track-change event the take starts; leading silence is trimmed afterwards.
lead_margin_seconds = {lead}

[rules]
# Which media apps to record. Matched against the Windows media-session app id (case-insensitive).
# The YouTube option in Settings adds the browsers: chrome.exe, msedge.exe, brave.exe, vivaldi.exe, opera.exe.
sources = {sources}
# A take is kept only if its length is within this many seconds of the track's reported duration,
# and only if wall-clock time from start to end also matches (catches buffering stalls).
duration_tolerance_seconds = {tolerance}
# Tracks shorter than this are never recorded (stray clips). The Spotify bridge tells ads apart.
min_duration_seconds = {min_duration}
# Items longer than this are never recorded (podcasts, audiobooks, DJ mixes).
max_duration_seconds = {max_duration}
# Discard a take if playback was paused during it.
discard_on_pause = {discard_on_pause}
# Discard if a seek was observed.
discard_on_seek = {discard_on_seek}
# Titles that mark non-music items (ads on Spotify Free). Case-insensitive exact match.
ignore_titles = {ignore_titles}
# Keep rejected takes on disk for this many days (0 = delete immediately).
keep_discards_days = {keep_discards_days}
# Discard a take if any other app (notifications, browser, games) made any sound during it.
discard_on_foreign_audio = {discard_on_foreign_audio}
# Peak level (dBFS) another app must reach to count. -120 or lower means any sound at all.
foreign_audio_threshold_db = {foreign_audio_threshold_db}
# Harvest mode: when a song that is already archived starts, skip Spotify to the next one.
harvest_mode = {harvest_mode}
# Warn on the Status page, with one notification, when a song plays this many seconds and no sound
# reaches Mynaphone. 0 turns the warning off.
silence_warning_seconds = {silence_warning}

[bridge]
# Local WebSocket the Spicetify extension connects to for exact track ids, quality tier and buffering.
enabled = {bridge_enabled}
port = {bridge_port}

[quality]
# Re-record a track already in the archive if it is now playing at a higher tier than the stored copy.
upgrade_on_higher_tier = {upgrade}

[library]
# Final library format: "aac" (M4A; cars and phones), "mp3" (plays anywhere), "opus" (smallest; phones and
# computers, not cars) or "flac" (lossless). Lossless-tier captures always stay FLAC.
format = {lib_format}
# Bitrate in kbps for the lossy formats. Sensible values: aac 192-320, mp3 256-320, opus 128-192.
aac_bitrate = {aac_bitrate}

[identify]
# Application API key from https://acoustid.org/my-applications (register an application, then copy its key).
acoustid_key = {acoustid_key}
# MusicBrainz asks every client to identify itself with a contact address; an email is fine.
musicbrainz_contact = {musicbrainz_contact}
# Optional. Genres come from Apple's catalog, then MusicBrainz; with this free key from
# https://www.last.fm/api/account/create, Last.fm's tags fill in the songs both lack.
lastfm_api_key = {lastfm_api_key}
# The Apple store searched for genres, as a two-letter country code. US covers Indian film songs too.
apple_country = {apple_country}
# Fill in the lyricist and composer of Indian film songs from JioSaavn when MusicBrainz has none. Its web API isn't
# published and its terms forbid automated use, so it's off unless you turn it on.
jiosaavn_credits = {jiosaavn_credits}

[albums]
# An album you don't have whole goes on the Wanted list once you have this many of its songs. With 0, the list holds
# only the albums you add with Want this album.
wanted_min_songs = {wanted_min_songs}

[app]
# With Start with Windows on, open hidden in the tray at sign-in. Opening it yourself always shows the window.
start_minimized = {start_minimized}
close_to_tray = {close_to_tray}
autostart_recording = {autostart_recording}
# Show a short explanation when the mouse rests on a button or setting.
show_tooltips = {show_tooltips}
"""
