# Record your first song

This walkthrough takes one song from Spotify into your library and shows what Mynaphone displays at
each stage. It takes as long as the song, plus about a minute.

Before you start, finish the [install guide](install.md) up to step 7, so that **Setup check** shows
no Problem lines and the AcoustID key is saved. The Spotify bridge from step 8 is optional for this
walkthrough, but without it the song may arrive without lyrics.

## 1. Start the recorder

1. Open Mynaphone. If it's already in the tray, click the tray icon.
2. In the sidebar, select **Status**.
3. If the pill at the top of the card reads Stopped, select **Start**.

The pill changes to Listening and the card reads "Waiting for a song to start in Spotify." The line
next to the buttons names the capture method and, with the bridge installed, reads "Spotify bridge
connected".

## 2. Play a song from its first second

1. In Spotify, pick a song you don't mind hearing to the end.
2. Play it from the beginning. Double-clicking the song in a list does that; pressing play on a song
   that was paused halfway does not.
3. Leave Spotify alone until the song ends. Don't pause, skip or seek.

While the song plays, the pill reads Recording, the card shows the cover, the title and the artist,
and a progress line fills up with the elapsed time under it. In the tray, the myna's eye turns red.

![The Status page while a song records, with its cover, the Recording pill and the progress line](images/status.png)

> [!TIP]
> You can turn the Windows volume down or mute the speakers while it records. Per-app capture
> doesn't depend on either. Keep Spotify's own volume slider at 100 %.

## 3. Watch the verdict

When the song ends and the next one starts, Mynaphone judges the take. In the sidebar, select
**Activity**.

The song appears at the top of the **Takes** table:

- **Kept**, with a detail such as "3:43 of 3:42, high". That's the recorded length, the song's
  published length and the quality tier.
- **Discarded**, with the reason, such as "paused during the song". Hover over the detail to see
  every reason.

![The Activity page with kept and discarded takes above the live log](images/activity.png)

The **Log** card underneath shows the same events as they happen: `recording`, then `KEPT`, then
`FILED` with the song's place in the library.

If your song was discarded, play it again from the start. [Why a take was discarded](using.md#find-out-why-a-take-was-discarded)
lists every reason and what to do about it.

## 4. Find the song in your library

About a minute after the verdict, Mynaphone has fingerprinted the song, looked it up, added lyrics
and the cover, and encoded it.

1. In the sidebar, select **Library**.
2. Select your song in the **Songs** list. The editor on the right shows its cover, where it's filed
   and what's still missing.

![The Library page with a song selected and its missing details listed in the editor](images/library.png)

The path under the title is relative to your library folder. A film song lands under `Soundtracks`,
for example `Soundtracks\Baadshah (1999)\01 Woh Ladki Jo.m4a`, and anything else under
`Artists\<Artist>\<Album>`.

To open the folder in File Explorer, scroll to the bottom of the editor and select **Folder**.

## 5. Check what's missing

The **Missing** column lists the details no source could supply, such as the lyricist or the ISRC.
That's normal, especially for regional film music, which databases often credit thinly.

You don't need to do anything. Mynaphone retries lyrics every half hour and a full lookup once a
week. If you know a missing detail, type it in and select **Save**. Your edits are never overwritten.
[Fix a song's details by hand](using.md#fix-a-songs-details-by-hand) covers the editor.

## What to do next

- Leave Mynaphone running while you listen. Every song you play through from start to finish ends up
  in the library, and songs you already have are skipped.
- To fill the library while you're away, [use harvest mode](using.md#record-a-playlist-unattended-with-harvest-mode).
- To take the music to the car, [export to a USB stick](using.md#export-the-library-to-a-usb-stick-or-phone).
