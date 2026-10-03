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
- An **Instrumental** choice in the Library editor. Marking a song as instrumental stops lyrics and
  lyricist showing as missing; marking it as having vocals overrides a title that says Instrumental.
- Years follow the album's first release. When the fingerprint matches a reissue (the 2025 Wish You
  Were Here), the year tag and folder use the original year, 1975 there.
- Volume checks: a take started with the app below 100 % in the Volume Mixer or in its own slider
  is rejected; the Windows master volume and mute are ignored (they do not affect per-app capture).
- A stop reported at a song's expected end counts as a normal finish (YouTube Music between tracks).
- Items longer than 15 minutes (podcasts, mixes) are skipped; the limit is a setting.
- Tooltips on every control, with a switch in Settings to turn them off.
- Security page and security policy; system requirements and a "what it works with" table in the README.
- Test suite (123 tests).
- GitHub Actions runs the tests on Windows with Python 3.11 and 3.13 and checks the code with Ruff.
- Issue and pull request templates.
- A code of conduct based on the Contributor Covenant 2.1.
- Icons for the browser extension at 16, 32, 48 and 128 px, drawn from the myna mark.
- A page on where the name comes from.
- Genres for every song, from Apple's catalog first, then MusicBrainz, then Last.fm's tags with an
  optional free API key, and Soundtrack for any soundtrack still without one. Your own edit wins.
- Songs whose title or album says Instrumental aren't looked up for lyrics, and lyrics and
  lyricist no longer count as missing for them.
- An updated logo brief for a designer, with what the current mark still gets wrong.

### Changed
- License: GNU GPL v3 or later.
- The Mynaphone name, mark and wordmark are reserved by their owner and aren't covered by the GPL
  or CC BY 4.0.
- The package reads its version number from `mynaphone/__init__.py`.
- The designed mark, a myna in profile whose eye turns red while a song records, replaces the
  placeholder drawn in code. The window, the tray and the browser extension use the designer's
  exports, and the README opens with the wordmark.
- The mark on the Status card, shown when a song has no cover art, is bigger. The bird now spans
  about three-quarters of its tile.
- Documentation: new pages for a first recording, the window and tray, and the command line, and a
  documentation index. Fresh screenshots of every page, the export dialog and the tray menu. The
  settings reference names each setting as the window shows it. Every service, library and source
  the docs mention is linked. Bug reports and feature requests use GitHub issue forms, and
  `SUPPORT.md` says where to get help.

### Fixed
- Installing the package now pulls in everything the app imports. PySide6, ytmusicapi, psutil,
  pycaw and comtypes were missing from its dependencies.
- Past takes in the Activity and Status tables and in the `status` command show the PC's local
  time. They used to show UTC.
- The window no longer stops responding for 10 to 20 seconds each time the recorder starts. Finding
  each source app's process through psutil kept every other part of the app waiting; it now reads
  one Windows process snapshot in about 10 ms.
- Songs after a long one were discarded as "started mid-song". The next take waited until the
  previous song had been written out, which took up to 8 seconds, and the 3-second buffer
  couldn't reach back to its start. The next take now starts first.
- Complete songs were discarded for "buffering" when Spotify loaded the next track during their
  last seconds. Those reports are ignored; a stall still shows as extra playing time.
- On the Status page the song title was squeezed while recording, and the mark shown in place of
  missing cover art kept a dark eye. Long titles now end in an ellipsis.
- A MusicBrainz release with a catalog number but no label stopped a song from being filed, and
  the app retried it forever. Errors in a MusicBrainz reply no longer hold a song back.
- The album's track and disc counts from Spotify's player are used when its web API answers with
  an error.
- The window sometimes came back from the tray as a blank white frame until you minimized and
  restored it. It now looks for its sidebar on screen after it opens, and minimizes and restores
  itself once when the sidebar isn't there. The log gets a line each time, along with Qt's own
  warnings and every screen that is added or removed.
- Songs were discarded for "playback stalled" when the recording was complete. Spotify sends no
  sound while it loads, so a stall usually leaves no gap in the capture. A stall now discards a
  take only when the music has a silent hole of 0.3 seconds or more.
- Pressing play on a new song after a pause left a "Discarded" row for the song before it, because
  Spotify names that song for a moment first. A take that the next song replaces within 2 seconds
  is dropped.
- Some skip reasons, such as `capture_not_ready`, showed as raw codes in the Takes table. They read
  in words now, and a test checks that every reason the recorder gives has a label.
- Every song was flagged "playback stalled" a few seconds in, because Spotify's position starts
  1.5 to 3.7 seconds behind the clock while the track loads. That first lag is now the starting
  point, and only falling further behind it counts as a stall.
- The red eye was too small to see in the tray and on the taskbar. Up to 48 px the mark is drawn
  from the designer's SVG with a bigger eye, and at 150 % scaling the taskbar now gets a sharp
  48 px icon where it used to get a stretched 24 px one.
- Songs that followed a long one were often discarded as "seek detected", about 6 seconds in.
  While the long song was written out, the new song's first position reading waited in the queue.
  Read seconds late, it looked like a 5-second start-up delay, and the next fresh reading then
  looked like a jump ahead. Each reading is now brought up to the current time before it's
  compared. A first reading up to 2.5 seconds ahead also counts as the song's start, and the log
  records each reading in a song's first 20 seconds.
- Spotify's track details (ISRC, explicit flag, popularity) were missing for most songs. Asked
  through the client's CosmosAsync, the metadata service mostly answered in protobuf, which the
  bridge couldn't read. The bridge now fetches it with the client's token and reads either JSON or
  protobuf. The web API fallback reports its HTTP status when it fails.
- A song that started on the previous song's quiet tail kept that tail, and the cut to its
  published length then clipped its ending (Toxicity). The trim now starts the song after the
  last stretch of 0.2 seconds or more of digital silence in the lead window.
- Capture of Chrome restarted every few seconds. Chrome briefly starts lone chrome.exe processes
  with lower pids, and the capture took the lowest one each time. It now stays on the process it
  has while that one is still a top process, and otherwise picks the one with the most children.
- A complete song was discarded as "paused" when Spotify's queue ran out after it, because Spotify
  reports a pause at that moment. A pause in a song's last 10 seconds now ends the take, and the
  length check still rejects a song paused before its end.
- Spotify bridge failures are reported in the log: errors inside the extension, the first state of
  each connection, and the extension seeing no track while Spotify plays one.
- The end of a song was cut by about 1.5 to 2 seconds. Spotify's sound trails its clock, so it names
  the next track while the last one is still playing, and the take stopped there. A slow fade-out
  then failed the length check (Divinity: Original Sin 2 main theme, 216.9 of 219.0 s). An ended
  take now keeps recording for 3 seconds alongside the next one, and the trim cuts it at the song's
  published length.
- A take with no sound in it no longer leaves an empty FLAC file and a "tagging failed" warning
  in the discard folder. Spotify can show a song as playing while it waits for data and send no
  audio at all; stopped, or closed after the song's length, such a take has nothing left once the
  leading silence is trimmed. It now gets no files, and the Activity page still lists it with the
  reason it was discarded.
