# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Playing but silent: a source app says it's playing a song, and no sound reaches the capture.

The causes, in the order they're checked: Spotify Connect playing the song on another device, the per-app capture
not attached to the app, the app muted or at 0 in the Windows Volume Mixer, the player's own volume at 0, no audio
at all from the app, and audio that is only silence. No audio at all is what exclusive mode should look like, since
Windows' loopback only sees shared-mode streams; that is inferred from Microsoft's documents and untested.

The watch counts the song's own time, from its position, so a stall (the position stands still), a pause and an ad
never count. It starts over with every song and every time playback resumes, and any sound since then means the
song is fine, so a quiet stretch later in a song, such as the silence before a hidden track, never sets it off.
Spotify names a song 1.5 to 3.7 s before its sound starts (measured October 2, 2026), so the wait is 15 s of song.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from . import browsers

TAIL_SECONDS = 3.0          # sound this soon after a track change is the last song's (daemon.END_TAIL_SECONDS)
RECHECK_SECONDS = 10.0      # while a warning stands, its cause is looked at again this often

QUIET, SOUND = "quiet", "sound"

CONNECT = "connect"             # Spotify Connect plays the song on another device
CAPTURE = "capture"             # the per-app capture isn't attached to the app
MUTED = "muted"                 # muted, or at 0, in the Windows Volume Mixer
APP_VOLUME = "app_volume"       # the player's own volume is at 0
NO_AUDIO = "no_audio"           # the app sends Windows no audio at all: exclusive mode, most likely
SILENT_AUDIO = "silent_audio"   # the app sends audio, and all of it is silence


@dataclass
class _Song:
    key: tuple
    t0: float               # monotonic time the count began: the song's start, a resume, or the first look
    pos0: int               # the song's position then, in ms
    heard_after: float      # sound from this moment on is the song's
    playing: bool = True
    heard: bool = False


@dataclass
class Quiet:
    """A standing warning: an app has played a song this long and no sound has reached Mynaphone."""
    app: str
    since: float            # monotonic time from which no sound arrived
    noticed: float          # when the watch raised it
    title: str = ""         # the song playing then
    cause: str = ""
    device: str = ""        # the Spotify Connect device, for CONNECT
    checked: float = 0.0    # when the cause was last looked at


class SilenceWatch:
    """Raises one warning per quiet stretch, however many songs it lasts, and ends it when sound comes back."""

    def __init__(self, seconds: float):
        self.seconds = float(seconds)
        self._songs: dict[str, _Song] = {}
        self.quiet: dict[str, Quiet] = {}

    def step(self, app: str, key: tuple, playing: bool, position_ms: int, capture) -> str | None:
        """Look at one source app, about once a second: whether it's playing a song now, the song's position, and
        the capture that records the app. QUIET means its warning starts, SOUND that a standing one ends."""
        now = time.monotonic()
        heard_at = getattr(capture, "last_sound_at", None)
        song = self._songs.get(app)
        q = self.quiet.get(app)
        if q is not None and heard_at is not None and heard_at > q.noticed:
            del self.quiet[app]
            if song is not None:
                song.heard = True
            return SOUND
        if not playing:
            if song is not None:
                song.playing = False
            return None
        if song is None or song.key != key:
            # a new song: the last one's sound still arrives for a moment, and it isn't this song's
            tail = TAIL_SECONDS if song is not None else 0.0
            self._songs[app] = _Song(key, now, position_ms, now + tail)
            return None
        if not song.playing:            # playing again after a pause, a stall or an ad
            self._songs[app] = _Song(key, now, position_ms, now)
            return None
        if song.heard:
            return None
        if heard_at is not None and heard_at >= song.heard_after:
            song.heard = True
            return None
        song.pos0 = min(song.pos0, position_ms)     # played again from earlier in the song
        # the song's own time, and never more than the clock's: a seek forward moves the position with nothing played
        played_ms = min(position_ms - song.pos0, (now - song.t0) * 1000.0)
        if q is None and played_ms >= self.seconds * 1000.0:
            self.quiet[app] = Quiet(app=app, since=song.heard_after, noticed=now)
            return QUIET
        return None

    def forget(self, app: str) -> bool:
        """The app's media session went away. True when that ends a standing warning."""
        self._songs.pop(app, None)
        return self.quiet.pop(app, None) is not None


# -- words ---------------------------------------------------------------------------------------

_NAMES = {"spotify.exe": "Spotify", "firefox.exe": "Firefox"}


def app_name(app: str) -> str:
    """The name you know an app by: Spotify for Spotify.exe, Brave for brave.exe."""
    found = browsers.find(app)
    if found is not None:
        return found.name
    base = (app or "").replace("/", "\\").rsplit("\\", 1)[-1]
    low = base.lower()
    if low in _NAMES:
        return _NAMES[low]
    return base[:-4] if low.endswith(".exe") else (base or "the app")


def headline(app: str) -> str:
    """The Status card's heading, the notification's title and the tray icon's tooltip."""
    return f"Mynaphone can't hear {app_name(app)}"


def tray_tip(app: str) -> str:
    """The tray icon's tooltip while a no-sound warning about `app` stands. It's the same as `headline`."""
    return headline(app)


def explain(cause: str, app: str, device: str = "") -> str:
    """What's wrong and what to do about it, for the Status page, the notification and the log. The words for
    Spotify's own controls are Spotify's: its devices button lists this PC as This computer."""
    name = app_name(app)
    if cause == CONNECT:
        return (f"{name} is playing on {device or 'another device'}, so the song never reaches this PC. To play it "
                f"here, click the devices button at the bottom right of {name} and pick This computer.")
    if cause == CAPTURE:
        return f"Mynaphone couldn't hook into {name}'s audio. Press Stop, then Start, on the Status page."
    if cause == MUTED:
        return (f"{name} is muted or all the way down in the Windows Volume Mixer. Right-click the speaker icon by "
                f"the clock, open the Volume Mixer, and turn {name} up to 100%.")
    if cause == APP_VOLUME:
        if browsers.is_browser(app):
            return f"The YouTube player in {name} is muted or all the way down. Turn it up to 100%."
        return f"{name}'s own volume is all the way down. Turn it up to 100% at the bottom right of {name}."
    if cause == NO_AUDIO:
        if browsers.is_browser(app):
            return f"{name} isn't sending any audio to Windows. Check that the song's tab isn't muted."
        return f"{name} isn't sending any audio to Windows. If exclusive mode is on in {name}'s settings, turn it off."
    if browsers.is_browser(app):
        return f"{name} is sending only silence. Check that the song's tab isn't muted."
    return f"{name} is sending only silence. If the song starts quietly, the warning goes away when the music begins."


REASONS = {          # the Activity page's words for a take that got no sound, by cause
    CONNECT: "played on another device", CAPTURE: "couldn't hook into the app's audio",
    MUTED: "muted in the Windows Volume Mixer", APP_VOLUME: "app's own volume at 0%",
    NO_AUDIO: "app sent no audio", SILENT_AUDIO: "recording came out silent",
}


def reason_words(cause: str) -> str:
    """The Activity page's words for a take that got no sound because of `cause`, or "no sound reached Mynaphone" for
    a cause not in `REASONS`."""
    return REASONS.get(cause) or "no sound reached Mynaphone"
