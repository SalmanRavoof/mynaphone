# Using Mynaphone

Each section below is one task. The window has 6 pages in the left column: **Status**, **Activity**,
**Library**, **Settings**, **Setup check** and **Set up**, which holds the first-run steps for later.

## Recording from Spotify

1. On the **Status** page, select **Start**. The state changes to Listening.
2. In Spotify, play a song from its beginning.
3. Let it play to the end without pausing or seeking. The Status page shows the cover, the song and
   a progress line while it records, and the tray icon's dot turns red.
4. When the next song starts, the previous one is judged. It appears on the **Activity** page as
   Kept or Discarded, with the reason when discarded.
5. About a minute later the song shows as Filed, with its library path, and on the **Library** page
   with any metadata still missing. Identification needs the AcoustID key from the Set up page;
   without it the song is filed with the tags Spotify reported.

A song that is already in the library is skipped, so replaying favorites is safe. Anything longer
than 15 minutes is skipped too, which keeps podcasts out.

## Capturing YouTube Music in a browser

This needs the browser extension from the [install guide](install.md).

1. In **Settings**, make sure **Also record YouTube and YouTube Music** is ticked and saved.
2. Select **Start** on the Status page if the recorder is stopped. A change of sources takes effect
   the next time you start.
3. In Chrome or Edge, open music.youtube.com and play a track from the beginning.

Ordinary YouTube videos are ignored; only tracks YouTube itself marks as music are recorded. A change
of playback speed, a seek or a pause discards the take, the same as for Spotify.

## Leaving it running unattended with harvest mode

Harvest mode tells Spotify to skip any song that is already archived, so a long playlist captures
only what is new.

1. On the **Status** page, tick **Skip songs already in the library**. The same switch is in the
   tray menu and in Settings.
2. Start a playlist or album in Spotify and leave the PC alone. You can turn the Windows master
   volume down or mute the speakers; per-app capture ignores both. Leave Spotify's own volume slider
   and its slider in the Windows Volume Mixer at 100 %, since those are applied before the audio
   reaches the recorder. A take started with either below 100 % is rejected and the reason says so.
3. Come back later and check the **Activity** page.

The skipping stops at 30 songs a minute, so a playlist that is entirely archived doesn't loop
forever. Turn the switch off when you are listening yourself, otherwise songs you already own jump away.

## Pausing the recorder without stopping it

Select **Pause** on the Status page or in the tray menu. The recorder keeps listening and the bridges
stay connected, but no new take starts. Select **Resume** to continue. Pausing the recorder doesn't
affect a song already in progress; Spotify's own pause button does, and discards the take.

## Keeping it in the tray

Closing the window hides it; recording continues. Click the tray icon to bring it back. To stop
completely, use the tray menu's **Quit**. To open hidden on start, tick **Open minimized to the tray**
in Settings.

## Finding out why a take was discarded

1. Open the **Activity** page.
2. Find the song. The Detail column names the cause: paused during the song, seeked, playback
   stalled, started mid-song, length did not match, another app made sound, and so on.
3. The rejected recording stays in the discard folder for 3 days, adjustable in Settings, with a
   `.json` file next to it holding the full measurements.

Most discards mean the song was not played cleanly end to end. Play it again from the start.

## Fixing a song's details by hand

1. Open the **Library** page. Tick **Needs attention** to list only songs with something missing.
2. Select a song. The right side shows its cover, its file path, what is missing and every field.
3. Edit any field. Lists such as composers or genres take several names separated by semicolons.
   Paste lyrics into the **Lyrics** box; lines that start with timestamps like `[01:23.45]` count
   as synced.
4. To replace the cover, select **Cover image** and choose a picture file.
5. To force the song under Soundtracks, Artists or Singles, change **Filed as**.
6. Select **Save**. The file is re-tagged, and moved if its folder name changed.

Fields you edit get a blue border and automatic lookups never overwrite them.

### Songs in the Unsorted folder

A song lands in `Unsorted` when the app could not tell who performs it. That happens with a
YouTube upload that has no credits in its description and no match in any database. Open it on
the Library page, type the artist and album, pick the kind, and the app moves the file to its
proper folder.

## Looking a song up again

On the **Library** page, select the song and then **Look up again**. Mynaphone fingerprints the file
once more, queries AcoustID, MusicBrainz and the lyrics sources, keeps your manual edits, and reports
what is still missing. It also does this on its own: lyrics every half hour, and a full lookup for
incomplete songs once a week.

## Exporting the library to a USB stick or phone

1. Plug in the drive. For a car it should be formatted FAT32, which most sticks are.
2. On the **Library** page, select **Export to USB**.
3. Choose the drive. Tick **Include lyrics files** only for phone apps, since cars ignore them.
4. Tick **Remove songs from the drive that are no longer in the library** to keep the drive an
   exact mirror.
5. Select **Check what would be copied**, then **Export**.
6. When it reports Done, eject the drive safely.

Only new or changed files are written, so repeat exports are quick.

## Moving where files go

In **Settings** > **Folders**, set the inbox for temporary working files and the library for the
collection. Select **Save settings**. Existing library files stay where they are; new songs go to the
new folder.

## Choosing the quality and format

In **Settings** > **Capture**:

- **Bit depth**: keep 16-bit for Spotify Free, Premium and YouTube. Choose 24-bit only for Spotify's
  lossless tier.
- **Library format**: AAC 256 kbps, the default, plays in cars and on phones at about 9 MB a song.
  AAC 320 and 192, MP3 320 and 256, and Opus 160 and 128 are also offered; Opus is the smallest but
  most cars can't play it. FLAC is lossless and about 3 times larger. Songs captured at the lossless
  tier always stay FLAC. The space estimate under the Library folder updates as you choose.

Capture settings take effect the next time you select **Start**, and the format applies to new songs.

## Starting it twice

Only one copy runs at a time. Starting Mynaphone again while it is in the tray brings its window
back instead of opening a second recorder.

## Running without the window

For a console recorder, for example on a headless PC:

```powershell
.\.venv\Scripts\python -m mynaphone run
```

Other commands: `status` for counts and recent takes, `devices` for audio devices, `refresh` to
re-tag the library, `export <drive>`, and `setup-tools`.
