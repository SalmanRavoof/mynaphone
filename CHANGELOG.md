# Changelog

All notable changes to Mynaphone are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses semantic versioning.

## [Unreleased]

### Added
- A [docs site](https://salmanravoof.github.io/mynaphone/) built from `docs/` with Zensical.
  GitHub Actions checks its links on every push and pull request and publishes it from main. Its
  **Code reference** section comes from the code's docstrings.
- Keyboard shortcuts in the window. Ctrl+1 to Ctrl+6 open the pages in the sidebar's order, Ctrl+R
  starts or stops the recorder, Ctrl+P pauses or resumes it, and Ctrl+H turns harvest mode on or off.
  Ctrl+F finds a song in the Library, Ctrl+S saves the Library editor or Settings, and F5 runs the
  Setup check. Each control's tooltip shows its key, and the keys work while you type in a field.
- A search box in the Library's Songs view. It lists only the songs with every word you type in their
  title, artist, album, or album artist, accents or not.
- Album counts. The Library page has an **Albums** view that lists the albums your songs come from,
  with how many of each album's songs you have, such as 5 of 7. **Incomplete** lists only the albums
  you don't have whole. Mynaphone counts each album against the edition you played, and the extra
  songs of a bigger edition never count as missing.
- A Wanted list, opened from the Status page. It holds the albums you have 3 or more songs from, and
  any you add with **Want this album**, nearest to whole first. Pick one to see its missing songs,
  which Mynaphone reads from Spotify through the bridge. **Record the missing songs** then plays them
  in Spotify and records them. You can change how many songs it takes in Settings.
- The Spotify bridge gives the ISRCs of an album's songs, so a song you have from its single or
  another edition counts toward the album. Install the extension again to get it.
- A warning when Spotify says it's playing and no sound reaches Mynaphone. Once a song has played for
  15 seconds in silence, Mynaphone tells you why and what to do in a card at the top of the Status
  page, and Windows shows one notification. It tells apart Spotify Connect playing on another device,
  Mynaphone's capture failing to attach, Spotify muted in the Volume Mixer, Spotify's own volume at
  zero, no audio at all (most likely exclusive mode), and audio that is only silence. A song that
  plays meanwhile is discarded with that cause as its reason. To name the device, the Spotify bridge
  now says which one Spotify Connect plays on, so run `install-spicetify` again to update the
  extension.
- YouTube and YouTube Music in Brave, Vivaldi, and Opera, through the same browser extension as Chrome
  and Edge. The YouTube option in Settings now records in all 5 browsers, and a `config.toml` that
  had it ticked before gets the 3 new ones when Mynaphone reads it. They haven't been tested end to
  end yet.
- A **Browser extension** row on the Setup check page names the browsers the extension connected
  from since the recorder started.
- A `quit` command asks the running Mynaphone to quit, the way **Quit** in its tray menu does, and
  waits for it to close. Ending the process left a dead icon in the tray until the mouse passed over
  it, so a script that restarts Mynaphone can quit it this way now.
- Indian film credits from JioSaavn, off unless you turn it on in Settings. When MusicBrainz has
  no lyricist or composer for a film song, Mynaphone asks JioSaavn, reads its copies of the
  recording together, and takes a name only when 2 copies agree or the film's own album names it.
  JioSaavn's web API isn't published and its terms forbid automated use.
- Record a playlist. On the Status page, pick one of your Spotify playlists, Liked Songs, or a link to
  any playlist or album. Mynaphone says how much of it your library has, then plays it in Spotify from
  the first missing song, in order, and jumps past the songs you already have. A song that doesn't
  record gets one more try, and at the end Spotify pauses and gets its shuffle setting back.
- Playlist files: a recorded or saved playlist becomes an M3U8 in the library's `Playlists` folder,
  with paths relative to that folder, so it plays wherever the library goes. Songs you don't have yet
  are note lines, and the files are written again whenever songs are filed or moved.
- Spotify's track details (ISRC, track and disc numbers) are fetched once for older songs that
  missed them while the bridge's token kept expiring.
- One folder per film. A film's singles, such as `Ratata (From "Leo")`, a second spelling of its
  album name, and a single released the year before its album now join the folder of the film's
  album. Dubbed albums, background scores and films of the same name years apart keep their own
  folders. Songs filed apart before are moved in, and each move is written to
  `folder-moves.json` next to the index.
- Songs to play again: a button on the Status page opens the songs that didn't record all the way
  through and that your library still doesn't have, with why each one failed and when it last
  tried. Open one in Spotify to play it again, or hide a song you skipped on purpose.
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
- Offscreen tests for the window: theme, mark, tooltips, page headers, state pill, tables, keyboard
  shortcuts and the single-instance guard.
- Lyrics from Spotify and LRCLIB, embedded and as sidecar files; cover art from the capture, Spotify
  and the Cover Art Archive.
- AAC 256 kbps library encoding (FLAC for lossless captures) and placement under Soundtracks,
  Artists and Singles.
- Completeness tracking per song, automatic retries, manual editing with protected fields.
- Harvest mode, USB export, duplicate detection with quality-tier upgrades.
- Desktop window with Status, Activity, Library, Settings and Setup check pages; tray icon; start
  with Windows.
- The log says how the app ended: **Quit** in the tray menu, closing the window, or Windows signing
  out or shutting down.
- A Start menu shortcut, and one on the desktop if you like, from Settings or the `shortcut` command.
  Type Mynaphone in Start to open it, or pin it to the taskbar; the running window shares the pinned
  button. Opening Mynaphone while it runs brings its window to the front.
- `setup-tools`, `run`, `status`, `devices`, `refresh`, `export`, `install-spicetify`, `shortcut` commands.
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
- Test suite (311 tests).
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
- Per-app capture looks at Windows' process list once a second for all the source apps together.
  One look took 17 ms with 553 processes running, and each app looked every 2 or 3 seconds on its
  own, so 3 more browsers would have doubled the cost.
- The shortest song recorded is now 10 seconds, down from 45, so film themes and interludes record.
  The Spotify bridge reports ads, which are never recorded. On Spotify 1.2.93 the bridge reads track
  and album details with the client's own token and headers; its older route always failed.
- The Status page scrolls, like Settings, so its cards keep their size at the window's default size.
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
  `SUPPORT.md` says where to get help. `docs/research.md` now explains why Mynaphone doesn't use
  Deezer's API.

### Fixed
- The USB export never copied the playlist files, and the docs said it did. It now copies the M3U8
  files in the library's `Playlists` folder too. With **Remove songs from the drive that are no longer
  in the library** ticked, it also removes the playlists the library no longer has.
- A cancelled export said "Done" like one that finished. It now says "Cancelled", with how many files
  it copied before it stopped.
- When the post-processor filed or updated a song while you were editing one on the Library page, the
  editor read your song back from the index and lost your unsaved changes and any cover you'd picked.
  It now keeps them until you save or open another song.
- The Library editor never showed "Saved" after a save, since it read the song back and cleared that
  line straight away. The line stays now.
- Picking a cover in the Library editor showed a note that said to press Save changes. The button is
  **Save**, and the note says so now.
- After **Download and build** on the Set up page, the page went on saying ffmpeg and fpcalc were
  missing until you restarted Mynaphone. Mynaphone kept its first answer for each tool, so a tool it
  missed once stayed missing. It now looks again until it finds the tool.
- With its box empty, **Use this folder** on the Set up page saved `.` as the library folder, so new
  songs would have gone to whatever folder Mynaphone ran from. It now does nothing until the box has a
  folder.
- With the Spotify bridge off, asking for your playlists or an album's songs said it was turned off
  in Settings. The Settings page has no switch for it, so the message now names `config.toml`.
- Recording a playlist played its last missing song again, for one more try, while Mynaphone was
  still saving its first take, and then paused Spotify a few seconds in. On November 20, 2026 that
  happened to Sicko at the end of Monsoon Season, and the first take was fine. A song now gets one
  more try only once its verdict says it needs one, and the playlist ends when the last verdicts are
  in. A take that can't be saved counts as one that didn't record, so that wait always ends.
- Recording a playlist recorded a song again when your library had it from another release. Holiday,
  on Monsoon Season, was in the library from its COLORS single, under another Spotify id, with a
  longer title and 4 seconds less, so the playlist counted it as missing and spent 3 minutes on it.
  Spotify gives a song's ISRC a moment after it starts, and when your library has that ISRC,
  Mynaphone now drops the take and the playlist moves on. That covers a playlist, whose songs come
  without ISRCs, and an album whose ISRCs the bridge couldn't give before the run.
- A playlist song that starts before the Spotify bridge names it is now known by its title and
  length, so the playlist still jumps past it when you have it. Since the log began on October 3,
  2026, 22 of 1,009 songs got their Spotify id only after they started.
- When an album ended on a song it was recording, Spotify's autoplay played on afterwards and
  Mynaphone recorded those songs too. Spotify now pauses there, or the playlist goes back for a song
  that needs one more try.
- A playlist could stop the moment it started, when Spotify named the song it had been paused on. It
  never finished when it listed a song twice. A song too long to record played to its end before the
  playlist moved on, and a YouTube song you have, played during a playlist, ended it.
- When Spotify wouldn't play a playlist, the Status page showed a Python error in place of the
  reason.
- Stopping the recorder during a playlist left the button on **Stop the playlist** and the
  playlist's shuffle off. The playlist now stops with the recorder, gets its shuffle back and writes
  its file, and the log says what its shuffle was and when it comes back.
- An album or playlist pasted as a link was named after its Spotify id, so Monsoon Season's file
  was `Playlist 0AVJyPXZ.m3u8`. The Spotify bridge now sends each one's name with its songs, and a
  playlist saved again under a new name leaves no file under the old one.
- Re-tagging an M4A song swapped its cover's type between JPEG and PNG, since Mynaphone read the
  type the wrong way round. By November 20, 2026, 230 songs had a JPEG cover marked as PNG. A re-tag
  now reads the type from the picture itself, so each of those covers gets its right type back the
  next time its song is re-tagged.
- Re-tagging a song lost its recording time, its recording format (such as
  `48000Hz/16bit loopback`), and its AcoustID fingerprint. A re-tag writes every tag again from the
  index, and the index never kept them. So a re-tag moved the recording time to when the song went
  into the index, just after its recording ended. It also dropped the format and fingerprint tags.
  Mynaphone re-tags a song when you select **Save** or **Look up again** on the Library page or run
  the `refresh` command, and when a background job updates it. By November 20, 2026, 622 of the 960
  songs in the library had the later time and no recording format, and 557 of those songs had lost
  their fingerprint too. A re-tag now keeps what the file has. Songs that never had these tags get
  the time they went into the index, and a fingerprint once a lookup matches them.
- One browser's extension could vouch for a video in another browser. With YouTube open in Chrome
  and Edge, a music report from Chrome could let a video in Edge record as a song when the 2 videos
  were about the same length. The bridge now asks Windows which browser owns each connection and
  keeps each browser's reports apart, and the log names the browser when its extension connects or
  leaves.
- A film whose songs matched 2 of its MusicBrainz releases showed up twice in a player that groups
  by album artist, since each song kept its own release's credit. On November 20, 2026, 9 films did,
  among them Aashiq Banaya Aapne under "Himesh Reshammiya & Sameer" and "Himesh Reshammiya". A
  film's songs now share the names all their credits have, usually the music director, so all of
  Aashiq Banaya Aapne's songs say "Himesh Reshammiya". The sort name and MusicBrainz ids that go
  with that name come along, so a player that sorts by the sort name keeps the film together too.
  "Various Artists" counts only when no song names people, and an album artist you type on the
  Library page goes on the film's other songs too.
  New songs take their film's album artist when they're filed. Songs filed earlier are re-tagged,
  and each change is written to `album-artists.json` next to the index.
- A film's singles, and a second spelling of its album's name, showed up as albums of their own in a
  player that groups by album name. On November 20, 2026, 11 films did, among them Leo, whose 4
  singles each kept a name such as "Ratata (From “Leo”)". A film's songs now share the album's own
  name, spelled the way most of its songs spell it, and a film with only singles takes the film's
  name. Mynaphone numbers the singles after the album's songs, in the order they came out, so Leo's
  are tracks 8 to 11, and their file names stay as they are. An album or track number you type on
  the Library page stays, and a typed album goes on the film's other songs too. New songs take their
  film's album name when they're filed. Mynaphone re-tags the songs filed earlier and writes each
  change to `album-names.json` next to the index.
- Record a playlist no longer goes back at the end to a song the recorder already has from another
  release. It also knows such a song when several artists sing it, since Spotify's media session
  gives the recorder only the first artist's name, so it jumps past the song before it plays.
- Opening Mynaphone while it was quitting brought back the window of the copy that was quitting,
  which then closed with it, so nothing kept recording. The new launch now waits for that copy to
  close and then opens.
- The window could still turn into a blank white frame, and the check that repairs it only ran
  when the window opened from the tray. It now also runs when you switch to the window, every 30
  seconds while it's in front, and when the window comes back from the taskbar, moves to another
  screen, or the PC wakes up or changes its screens. When it can't tell, the log says why, and
  waking up and screen changes leave a line too. The log line for a blank window also says how much
  of Windows' memory was in use. When the window stops answering for 5 seconds, the log says where
  Mynaphone's code was stuck, and when it answers again.
- Mynaphone set aside nearly 500 MB of Windows' memory that it never used. numpy's maths library
  reserves memory for every CPU thread as it loads, and Mynaphone's audio arithmetic never uses
  those threads, so it now gets one.
- Another app's sound took a line in the log every 5 seconds, a third of the whole log by October 31,
  2026, and only whole-device recording cares about it. The log now says once when an app starts
  making sound after a quiet minute, and the rest shows with `-v`.
- The Spotify bridge could send nothing while songs played. Spicetify copies the player's state
  from an object it finds in Spotify's code, and after some starts it finds one that never changes,
  so its copy stays empty. On October 30, 2026 the bridge sent nothing for 40 minutes, and Mynaphone
  knew only what Windows reports about each song. The extension now reads Spotify's own player, and
  the log says when Spicetify's copy is empty.
- Band songs were tagged with their singers as the artist: Metallica's as James Hetfield, Queen's
  as Brian May and Freddie Mercury, and Bowie's "“Heroes”" as David Bowie and Tony Visconti, who
  sang backing vocals. The rule meant for film songs, where MusicBrainz credits the music director
  and the player names the singers, also caught every recording credited to its album artist. The
  singers now stand in only when the player names one of them and none of the credited artists,
  backing and choir singers are left out, and each name appears once. Songs filed before the fix
  get their MusicBrainz credit read again and their files re-tagged, a few dozen per run.
- Game and film scores counted as songs missing their lyrics and lyricist. A song is now taken as
  instrumental when MusicBrainz gives it its "no lyrics" language, when its title (the one the
  player showed too) or its album says Instrumental, when its album is a film's or a game's score,
  or when it has no lyricist or singer credited and sits on an album with at least 5 songs in the
  library, 3 in 4 of them without words. Choosing vocals in the Library editor still wins.
- Lyrics from LRCLIB had stopped arriving since mid-October. For a song LRCLIB doesn't have, its
  exact lookup also asks other sites, and that part answered "The server is busy" (503), which
  stopped every lyrics run at its first song. Mynaphone now asks LRCLIB's own database and its
  search, and when a long artist credit makes the search busy, it searches under the first name in
  the credit. Requests go out at least a second apart, a pause LRCLIB asks for is kept, a lookup
  that got no answer doesn't count as one of a song's 10 tries, and a song whose lookup failed moves
  to the back of the line. The lyrics run also stops when a new song is waiting to be filed.
- While a finished song was written out, the recorder read nothing from the player for 5 to 9
  seconds, so the next song's first updates arrived late. Songs are now saved in the background, one
  at a time on their own thread and database connection.
- Quitting could crash Mynaphone after it had closed, inside Windows' media-session module. A
  change Windows reported during shutdown could hook the media sessions again after the recorder
  had let go of them. The listener now ignores changes once it has stopped, and its Windows objects
  are freed before Python shuts down.
- Opening Mynaphone from its shortcut could show nothing. With **Open minimized to the tray** ticked
  it started hidden in the tray, where Windows had tucked its icon under the ^ arrow by the clock.
  Opening it yourself now always shows the window; the setting, renamed **When Windows starts it,
  open in the tray**, applies only to Start with Windows. When the window first closes to the tray,
  the message says the icon may be under the ^ arrow.
- Songs of 45 to 65 seconds that AcoustID didn't know stayed in the inbox for good. The second
  fingerprint started 45 seconds in, where such a song has almost nothing left, and the error was
  taken as identification being unavailable. A short song's second fingerprint now starts a third of
  the way in, and if a second try still fails, the song is filed with Spotify's tags.
- A song recorded from both its album and its single was filed twice: the second copy overwrote the
  first file, and the library listed the song twice. A take that's the same recording as a library song
  (the same MusicBrainz recording, or the same ISRC) is now set aside in the discard folder unless it's
  at a higher tier, and its Spotify id is remembered so that version is skipped from then on. Songs
  already listed twice are merged when the app starts. When Spotify reports a song's ISRC before it
  starts, a song already in the library is recognized by it too.
- Mynaphone kept every song it recorded in memory until it quit, about 80 MB a song: after a day of
  listening it held 16 GB. The volume check at the start of each song set up Windows' COM on the
  recorder's thread in a way that stopped Spotify's cover thumbnail from ever arriving, and each stuck
  request held on to its song. The check now runs on a thread of its own, which can't hold up quitting
  if it hangs, a cover request gives up after 5 seconds, and a song's audio is let go as soon as it's
  saved.
- **Start with Windows** now starts the app. Its startup entry put `--config` after `gui`, which the
  command line refused, so the app quit at sign-in without a word. Entries already saved that way
  work too.
- Spotify's track details (ISRC, track and disc numbers, duration) stopped arriving about an hour
  after Spotify started: the bridge used the access token from start-up, which expires. It now uses
  the token Spotify keeps refreshed and tries the other one on a 401.
- A song paused mid-way could be taken as ended once the clock passed its last 10 seconds, though
  the song stood still. The end-of-queue check now counts only the time the song played.
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
