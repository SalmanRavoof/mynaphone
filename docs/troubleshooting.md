# Troubleshooting

Start with **Setup check** > **Run checks** in the app. It finds most setup problems on its own.
Then find your symptom below.

- [Nothing is recorded](#nothing-is-recorded)
- [Every take is discarded](#every-take-is-discarded), and [every discard reason](#every-discard-reason)
- [Songs are kept but not filed](#songs-are-kept-but-not-filed)
- [Wrong song or wrong album](#wrong-song-or-wrong-album)
- [No lyrics or no cover](#no-lyrics-or-no-cover)
- ["Spotify bridge not connected"](#spotify-bridge-not-connected)
- [Browser extension problems](#the-browser-extension-connects-and-disconnects)
- [The capture helper won't build](#the-capture-helper-wont-build)
- [Where the logs are](#where-the-logs-are) and [reporting a bug](#reporting-a-bug)

## Nothing is recorded

| Cause | Fix |
|---|---|
| The recorder is stopped or paused. | On the Status page the state should read Listening. Select **Start** or **Resume**. |
| The song started mid-way, or you pressed play on a paused song. | Only songs played from their first second are kept. Play the next song from the beginning. |
| Spotify is not reporting to Windows. | Restart Spotify. The Spotify line in Setup check should show the current song. |
| The app is not in the sources list. | For YouTube, tick the YouTube option in Settings, save, then select **Stop** and **Start** on the Status page. |
| Per-app capture could not attach. | The log shows "no live capture". Stop and start the recorder. If it repeats, run `setup-tools --force` to rebuild the helper, or switch **Capture method** to Whole output device in Settings. |
| The song is shorter than 45 seconds or longer than 15 minutes. | Those are treated as ads or podcasts. Change **Minimum length** in Settings, or `max_duration_seconds` in `config.toml`. |

## Every take is discarded

| Reason shown | Meaning | Fix |
|---|---|---|
| playback stalled | The connection couldn't keep up and Spotify rebuffered. | Set Spotify's streaming quality to a fixed value and switch **Auto adjust quality** off. Try again when the connection is steadier. |
| length did not match | The recording is shorter or longer than the song, usually after a stall or a seek. | As above. If it happens on every song in device mode, check that the output device's sample rate matches the setting. |
| another app made sound | Device mode only. A notification or another app played during the take. | Switch **Capture method** to Per app in Settings, or silence other apps. |
| paused during the song, seeked within the song | You interacted with playback. | Let songs play through. |
| started mid-song | The recorder noticed the song more than 1.5 s late, beyond the ring buffer. | Rare. If it's frequent, raise `preroll_seconds` in `config.toml`. |
| output device changed | Headphones were plugged in or out mid-song, in device mode. | Per-app capture isn't affected by device changes. |
| app at N% in the Windows Volume Mixer | The app's slider in the Volume Mixer was below 100 %, so the recording would be quiet. | Right-click the speaker icon, open the Volume Mixer and set the app to 100 %. The Windows master volume can stay anywhere. |
| app's own volume at N% | Spotify's slider or the YouTube player's volume was below 100 %. | Set it to 100 % and use the Windows master volume for listening level. |

### Every discard reason

The Activity page names the first cause and counts the rest, for example "paused during the song,
and 3 more". The others usually follow from the first, so fix that one. Rest the mouse on the detail
to see them all.

| Shown as | What happened |
|---|---|
| paused during the song | Playback was paused while the take ran |
| seeked within the song | Playback jumped forward or back |
| playback stalled | The player reported buffering |
| took longer than the song | The take ran longer, by the clock, than the song's length, usually because of a stall |
| started mid-song | The song was already playing when the take began |
| length did not match | The recorded length differs from the song's length by more than 1.5 s |
| ended early | The take stopped before the song's end |
| too short to be a song | Shorter than the minimum length |
| longer than a song (podcast or mix?) | Longer than the maximum length |
| no duration reported | The player didn't say how long the song is, so completeness can't be checked |
| audio dropout | The capture lost audio, for example while the PC was heavily loaded |
| output device changed | The output device changed during the take, in device mode |
| another app made sound | Another app played sound during the take, in device mode |
| app at N% in the Windows Volume Mixer | The source app's mixer slider was below 100 % |
| app's own volume at N% | The player's own volume was below 100 % |
| playback stopped | The player stopped before the song's end |
| player closed | The player quit during the song |
| recorder stopped | Mynaphone was stopped or closed during the song |
| no track change seen | The song ran past its end and no next song was reported |
| recording paused | The recorder was paused when the song started |
| audio capture not running yet | The song started before capture was ready, for example just after Mynaphone started |
| already in the archive | The song is already in the library at the same or a higher tier |
| already in the archive, skipped | As above, and harvest mode skipped it in Spotify |
| not a music video | A YouTube video that YouTube doesn't mark as music |
| couldn't confirm the browser tab's song | The browser extension didn't report, so the app couldn't be sure which tab played |

## Songs are kept but not filed

| Cause | Fix |
|---|---|
| No internet. | Filing waits and retries with increasing gaps up to an hour. The Activity log shows "waiting to file". |
| No AcoustID key. | Add the key on the **Set up** page. Without it, songs are filed with Spotify's tags only. |
| ffmpeg or fpcalc missing. | Run `.\.venv\Scripts\python -m mynaphone setup-tools`. Setup check reports both. |
| AcoustID or MusicBrainz is down or rate-limiting. | Mynaphone retries on its own. The [MusicBrainz rate limits](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting) allow about one request a second. |

## Wrong song or wrong album

The fingerprint matched a different release, such as a reissue or a compilation. For a reissue the
year already follows the album's first release on MusicBrainz, so Wish You Were Here files under
1975, not 2025.

1. On the **Library** page, select the song.
2. Correct the fields and select **Save**. Manual fields are kept on later lookups.
3. If the identification itself is wrong, fix the title and artist, then select **Look up again**.

## No lyrics or no cover

Lyrics are retried every half hour for 10 attempts. Many regional-language songs have lyrics in
Spotify but not in LRCLIB, and the Spotify bridge supplies those, so install it.

Covers fall back to the Cover Art Archive. If none exists, choose a picture with **Cover image** on
the Library page.

## "Spotify bridge not connected"

| Cause | Fix |
|---|---|
| Spotify updated and undid Spicetify. | Run `spicetify apply`, or `spicetify backup apply` if it complains. |
| Spicetify is not installed, or the extension is not enabled. | Run `.\.venv\Scripts\python -m mynaphone install-spicetify --apply`. |
| The bridge connected, but the log says Spicetify.Player has had no track for a minute. | Quit Spotify from its tray icon and start it again. If that doesn't help, run `spicetify apply`. |
| Port 8765 is used by another program. | Change `port` under `[bridge]`, and the port at the top of `spicetify/mynaphone.js` and in `browser-extension/background.js`, then reinstall both. |

Spicetify's own [getting-started guide](https://spicetify.app/docs/getting-started) covers problems
with Spicetify itself.

## The browser extension connects and disconnects

Chrome suspends an extension's background part after 30 seconds without activity and wakes it when a
YouTube tab reports. The log shows connect and disconnect pairs while nothing is playing. This is normal.

## Chrome shows an Errors button on the extension

Open it. An entry that says the WebSocket connection to port 8765 failed with
"ERR_CONNECTION_REFUSED" means the extension tried to reach the recorder while Mynaphone wasn't
running, or was restarting. Chrome records every refused attempt.

Nothing is broken, and the extension tries less often the longer the recorder stays off. Select
**Clear all** once Mynaphone is running again. Any other entry is worth reporting.

## The window keeps appearing in front

Mynaphone's window has no stay-on-top setting; it comes to the front only when launched. Tick **Open
minimized to the tray** in Settings if you never want to see it on start.

## The capture helper won't build

`setup-tools` uses the C# compiler at `C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe`,
which is part of the .NET Framework 4 included with every 64-bit Windows 10 and 11.

If it's missing or blocked by policy, switch **Capture method** to **Whole output device** in
Settings. Recording works, but other apps' sounds will then reject takes, so silence notifications
while you record.

## Where the logs are

| What | Where |
|---|---|
| The log | `D:\Music\mynaphone\logs\mynaphone.log` by default, or the `log_dir` in `config.toml`. It rotates at 5 MB |
| The live log | The **Log** card on the Activity page, for the current session |
| A discarded take's measurements | The `.json` file next to the recording in the discard folder |
| A kept take's measurements | The `.json` file next to the recording in the inbox, until it's filed |

For more detail in the log, start Mynaphone with `-v`, for example
`.\.venv\Scripts\python -m mynaphone -v gui`.

## Reporting a bug

[Open a bug report](https://github.com/SalmanRavoof/mynaphone/issues/new/choose). The form asks for:

- the Windows version, from `winver`
- the Mynaphone version, shown at the bottom of the sidebar
- the capture method and the source app
- whether the Spotify bridge or the browser extension was connected
- the relevant lines from the log
- the `.json` of an affected take, if there is one

Remove anything personal from file names before posting.
