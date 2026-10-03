# Using Mynaphone

Each section below is one task, in numbered steps. For what every page, button and column means,
see [The window and the tray](window.md). If you haven't recorded anything yet,
[Record your first song](first-song.md) is the place to start.

## Record from Spotify

1. On the **Status** page, select **Start**. The state changes to Listening.
2. In Spotify, play a song from its beginning.
3. Let it play to the end without pausing or seeking. The Status page shows the cover, the song and
   a progress line while it records, and the myna's eye in the tray icon turns red.
4. When the next song starts, the previous one is judged. It appears on the **Activity** page as
   Kept or Discarded, with the reason when discarded.
5. About a minute later the song shows as Filed, with its library path, and on the **Library** page
   with any metadata still missing.

Identification needs the AcoustID key from the Set up page. Without it the song is filed with the
tags Spotify reported.

A song that is already in the library is skipped, so replaying favorites is safe. Anything longer
than 15 minutes is skipped too, which keeps podcasts out.

## Record YouTube Music in a browser

This needs the browser extension from [step 9 of the install guide](install.md#step-9-optional-load-the-browser-extension-for-youtube).

1. In **Settings**, make sure **Also record YouTube and YouTube Music playing in Chrome or Edge** is
   ticked, and select **Save settings**.
2. On the **Status** page, select **Stop** and then **Start**. A change of sources takes effect the
   next time the recorder starts.
3. In Chrome or Edge, open music.youtube.com and play a track from the beginning.

Ordinary YouTube videos are ignored; only tracks YouTube itself marks as music are recorded. A change
of playback speed, a seek or a pause discards the take, the same as for Spotify.

## Record a playlist unattended with harvest mode

Harvest mode tells Spotify to skip any song that is already archived, so a long playlist captures
only what is new.

1. On the **Status** page, tick **Skip songs already in the library, so an unattended playlist
   records only new ones**. The same switch is in the tray menu and in Settings.
2. Start a playlist or album in Spotify and leave the PC alone.
3. Come back later and check the **Activity** page.

You can turn the Windows master volume down or mute the speakers while it runs, because per-app
capture ignores both. Leave Spotify's own volume slider and its slider in the Windows Volume Mixer at
100 %, since those are applied before the audio reaches the recorder. A take started with either
below 100 % is rejected, and the reason says so.

> [!WARNING]
> Keep the PC awake while harvesting. If Windows goes to sleep, playback stops and the song in
> progress is discarded. In **Settings** > **System** > **Power & sleep**, set **Sleep** to Never
> while plugged in.

The skipping stops at 30 songs a minute, so a playlist that is entirely archived doesn't loop
forever. Turn the switch off when you're listening yourself, otherwise songs you already own jump away.

## Pause the recorder without stopping it

1. Select **Pause** on the Status page, or **Pause recording** in the tray menu. The recorder keeps
   listening and the bridges stay connected, but no new take starts.
2. Select **Resume** to continue.

Pausing the recorder doesn't affect a song already in progress. Spotify's own pause button does,
and discards the take.

## Keep it in the tray

Closing the window hides it, and recording continues. Click the tray icon to bring it back.

- To stop completely, right-click the tray icon and select **Quit**.
- To open hidden on start, tick **Open minimized to the tray** in Settings.
- To launch with Windows, tick **Start with Windows** in Settings.

Only one copy runs at a time. Starting Mynaphone again while it's in the tray brings its window back
instead of opening a second recorder.

## Find out why a take was discarded

1. Open the **Activity** page.
2. Find the song. The **Detail** column names the first cause, and "and 2 more" means other checks
   failed as a result. Rest the mouse on the detail to see the full list.
3. Look the reason up in [every discard reason](troubleshooting.md#every-discard-reason), which says
   what each one means and what to do.

The rejected recording stays in the discard folder for 3 days, adjustable in Settings, with a `.json`
file next to it holding the full measurements.

Most discards mean the song wasn't played cleanly end to end. Play it again from the start.

## Fix a song's details by hand

1. Open the **Library** page. Tick **Needs attention** to list only songs with something missing.
2. Select a song. The right side shows its cover, its file path, what is missing and every field.
3. Edit any field. Lists such as composers or genres take several names separated by semicolons.
4. To add lyrics, paste them into the **Lyrics** box. Lines that start with timestamps like
   `[01:23.45]` count as synced.
5. To replace the cover, select **Cover image** and choose a picture file.
6. To choose the folder layout yourself, change **Filed as** to Soundtrack, Album, Single or Compilation.
7. If the song has no vocals, set **Instrumental** to **Yes, no vocals**. Lyrics and lyricist then
   stop showing as missing, and the app stops looking for them. Choose **No, it has vocals** when the
   app guessed wrong from a title or album that says "Instrumental".
8. Select **Save**. The file is re-tagged, and moved if its folder name changed.

![The bottom of the Library editor, with Filed as, Instrumental, the Lyrics box and the Save button](images/library-editor.png)

Fields you edit get a blue border, and automatic lookups never overwrite them.

### Songs in the Unsorted folder

A song lands in `Unsorted` when the app couldn't tell who performs it. That happens with a YouTube
upload that has no credits in its description and no match in any database.

1. On the **Library** page, tick **Needs attention** and select the song.
2. Type the artist and album, and choose **Filed as**.
3. Select **Save**. The app moves the file to its proper folder.

## Look a song up again

1. On the **Library** page, select the song.
2. Select **Look up again**.

Mynaphone fingerprints the file once more, queries AcoustID, MusicBrainz and the lyrics sources,
keeps your manual edits, and reports what is still missing.

It also does this on its own: lyrics every half hour, and a full lookup for incomplete songs once a
week. To look up the whole library at once, run the [`refresh` command](command-line.md#refresh).

## Export the library to a USB stick or phone

1. Plug in the drive. For a car it should be formatted FAT32, which most sticks are.
2. On the **Library** page, select **Export to USB**.
3. Choose the drive, or select **Folder...** for any other folder.
4. Tick **Include lyrics files (.lrc)** only for phone apps, since cars ignore them.
5. Tick **Remove songs from the drive that are no longer in the library** to keep the drive an
   exact mirror.
6. Select **Check what would be copied**, then **Export**.
7. When it reports Done, eject the drive safely.

![The Export to USB dialog](images/export-dialog.png)

Only new or changed files are written, so repeat exports are quick.

## Change where files go

1. In **Settings** > **Folders**, set the **Inbox** for temporary working files and the **Library**
   for the collection.
2. Select **Save settings**.

Existing library files stay where they are, and new songs go to the new folder. To move the whole
collection, quit Mynaphone, move the folder in File Explorer, then point **Library** at its new place.

## Choose the quality and format

In **Settings** > **Capture**:

- **Bit depth**: keep 16-bit for Spotify Free, Premium and YouTube. Choose 24-bit only for Spotify's
  lossless tier.
- **Library format**: AAC 256 kbps, the default, plays in cars and on phones at about 9 MB a song.
  AAC 320 and 192, MP3 320 and 256, and Opus 160 and 128 are also offered. Opus is the smallest, but
  most cars can't play it. FLAC is lossless and about 3 times larger. Songs captured at the lossless
  tier always stay FLAC.

The space estimate under the Library folder updates as you choose. Capture settings take effect the
next time you select **Start**, and the format applies to new songs.

## Run without the window

For a console recorder, for example on a PC without a monitor:

```powershell
.\.venv\Scripts\python -m mynaphone run
```

Press <kbd>Ctrl</kbd>+<kbd>C</kbd> to stop it. The [command line reference](command-line.md) lists
this and every other command.
