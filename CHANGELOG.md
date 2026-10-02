# Changelog

All notable changes to Mynaphone are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses semantic versioning.

## [Unreleased]

### Added
- Per-app audio capture through a native helper using Windows' process-loopback API; whole-device
  capture kept as an option.
- Keep-or-discard verdict: start position, pause, seek, stall, dropout, device change, length and
  wall-clock checks; rejected takes kept for inspection with a JSON record.
- Spotify bridge (Spicetify extension): exact track and album ids, quality tier, buffering, album
  facts, ISRC and explicit flag, Spotify's own synced lyrics.
- Browser extension for YouTube and YouTube Music.
- A look drawn from the common myna: ink sidebar with icons, warm paper canvas, one ochre
  highlight, and a myna-head mark whose eye turns red only while recording.
- Identification: Chromaprint fingerprint, AcoustID, MusicBrainz release/recording/work enrichment,
  YouTube Music fallback, soundtrack heuristics.
- YouTube captures that the fingerprint does not know: a second fingerprint from the middle of the
  recording, song credits read from the video description, and a catalog search by film. Channel
  names and view counts are never used as artist or album; unidentified songs go to `Unsorted`.
- Singers stay in the artist tag when MusicBrainz credits a film recording to its music director.
- Offscreen tests for the window: theme, mark, tooltips, page headers, state pill, tables and the
  single-instance guard.
- Lyrics from Spotify and LRCLIB, embedded and as sidecar files; cover art from the capture, Spotify
  and the Cover Art Archive.
- AAC 256 kbps library encoding (FLAC for lossless captures) and placement under Soundtracks,
  Artists and Singles.
- Completeness tracking per song, automatic retries, manual editing with protected fields.
- Harvest mode, USB export, duplicate detection with quality-tier upgrades.
- Desktop window with Status, Activity, Library, Settings and Setup check pages; tray icon; start
  with Windows.
- `setup-tools`, `run`, `status`, `devices`, `refresh`, `export`, `install-spicetify` commands.
- Library formats: AAC (default), MP3, Opus and FLAC with selectable bitrates; full tags, cover and
  lyrics in each.
- Free-space estimate for the chosen library drive, in Settings, Set up and the Setup check.
- In-app Set up page for first run: tools download, AcoustID key, library folder, bridges.
- Volume checks: a take started with the app below 100 % in the Volume Mixer or in its own slider
  is rejected; the Windows master volume and mute are ignored (they do not affect per-app capture).
- A stop reported at a song's expected end counts as a normal finish (YouTube Music between tracks).
- Items longer than 15 minutes (podcasts, mixes) are skipped; the limit is a setting.
- Tooltips on every control, with a switch in Settings to turn them off.
- Security page and security policy; system requirements and a "what it works with" table in the README.
- Test suite (84 tests).
- GitHub Actions runs the tests on Windows with Python 3.11 and 3.13 and checks the code with Ruff.
- Issue and pull request templates.
- A code of conduct based on the Contributor Covenant 2.1.
- Icons for the browser extension at 16, 32, 48 and 128 px, drawn from the myna mark.
- A page on where the name comes from.

### Changed
- License: GNU GPL v3 or later.
- The package reads its version number from `mynaphone/__init__.py`.

### Fixed
- Installing the package now pulls in everything the app imports. PySide6, ytmusicapi, psutil,
  pycaw and comtypes were missing from its dependencies.
- Past takes in the Activity and Status tables and in the `status` command show the PC's local
  time. They used to show UTC.
- The window no longer stops responding for 10 to 20 seconds each time the recorder starts. Finding
  each source app's process through psutil kept every other part of the app waiting; it now reads
  one Windows process snapshot in about 10 ms.
