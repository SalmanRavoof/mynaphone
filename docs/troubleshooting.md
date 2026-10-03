# Troubleshooting

Start with **Setup check** > **Run checks** in the app. Then find your symptom here.

## Nothing is recorded

| Cause | Fix |
|---|---|
| The recorder is stopped or paused. | On the Status page the state should read Listening. Select **Start** or **Resume**. |
| The song started mid-way or you pressed play on a paused song. | Only songs played from their first second are kept. Play the next song from the beginning. |
| Spotify is not reporting to Windows. | Restart Spotify. Setup check should show a media session with the current song. |
| The app is not in the sources list. | For YouTube, tick the YouTube option in Settings, save and restart the recorder. |
| Per-app capture could not attach. | The log shows "no live capture". Restart the recorder; if it repeats, run `setup-tools --force` to rebuild the helper, or switch to device mode in Settings. |

## Every take is discarded

| Reason shown | Meaning | Fix |
|---|---|---|
| playback stalled | The connection could not keep up and Spotify rebuffered. | Set Spotify's streaming quality to a fixed value and switch **Auto adjust quality** off; try again when the connection is steadier. |
| length did not match | The recording is shorter or longer than the song. Usually a stall or a seek. | As above. If it happens on every song in device mode, check the output device's sample rate matches the setting. |
| another app made sound | Device mode only: a notification or another app played during the take. | Use per-app capture (Settings > Capture method), or silence other apps. |
| paused during the song / seeked | You interacted with playback. | Let songs play through. |
| started mid-song | The recorder noticed the song late by more than 1.5 s, beyond the ring buffer. | Rare; if frequent, raise `preroll_seconds` in `config.toml`. |
| output device changed | Headphones were plugged or unplugged mid-song (device mode). | Per-app capture is not affected by device changes. |
| app at N% in the Windows Volume Mixer | The app's slider in the Volume Mixer was below 100 %, so the recording would be quiet. | Open the Volume Mixer (right-click the speaker icon) and set the app to 100 %. The Windows master volume can stay anywhere. |
| app's own volume at N% | Spotify's slider or the YouTube player's volume was below 100 %. | Set it to 100 % and use the Windows master volume for listening level. |

## Songs are kept but not filed

| Cause | Fix |
|---|---|
| No internet. | Filing waits and retries with increasing gaps up to an hour. The Activity log shows "waiting to file". |
| No AcoustID key. | Add the key to `config.toml` under `[identify]`. Without it, songs are filed with Spotify's tags only. |
| ffmpeg or fpcalc missing. | Run `.\.venv\Scripts\python -m mynaphone setup-tools`. Setup check reports both. |
| AcoustID or MusicBrainz is down or rate-limiting. | Retried automatically. |

## Wrong song or wrong album

The fingerprint matched a different release (a reissue, a compilation). For a reissue the year
already follows the album's first release on MusicBrainz, so Wish You Were Here files under 1975,
not 2025. For anything else, on the Library page select
the song, correct the fields and select **Save**. Manual fields are kept on later lookups. If the
identification itself is wrong, fix the title and artist, then select **Look up again**.

## No lyrics or no cover

Lyrics are retried every half hour for ten attempts. Many regional-language songs have lyrics in
Spotify but not in LRCLIB; the Spotify bridge supplies those, so install it. Covers fall back to the
Cover Art Archive; if none exists, choose a picture with **Cover image** on the Library page.

## "Spotify bridge not connected"

| Cause | Fix |
|---|---|
| Spotify updated and undid Spicetify. | Run `spicetify apply`, or `spicetify backup apply` if it complains. |
| Spicetify is not installed or the extension is not enabled. | Run `.\.venv\Scripts\python -m mynaphone install-spicetify --apply`. |
| Port 8765 is used by another program. | Change `port` under `[bridge]` and the port at the top of `spicetify/mynaphone.js` and `browser-extension/background.js`, then reapply. |

## Browser extension connects and disconnects

Chrome suspends an extension's background part after 30 seconds without activity and wakes it when a
YouTube tab reports. The log shows connect and disconnect pairs while nothing is playing. This is normal.

## Chrome shows an Errors button on the extension

Open it. An entry that says the WebSocket connection to port 8765 failed with
"ERR_CONNECTION_REFUSED" means the extension tried to reach the recorder while Mynaphone was not
running, or was restarting. Chrome records every refused attempt. Nothing is broken, and the
extension tries less often the longer the recorder stays off. Select **Clear all** once Mynaphone
is running again. Any other entry is worth reporting.

## Window keeps appearing in front

Mynaphone's window has no stay-on-top setting; it comes to the front only when launched. Tick **Open
minimized to the tray** in Settings if you never want to see it on start.

## Capture helper will not build

`setup-tools` uses the C# compiler at `C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe`,
present on every 64-bit Windows 10 and 11. If it is missing or blocked by policy, switch **Capture
method** to **Whole output device** in Settings. Recording works; other apps' sounds will then reject takes.

## Where the logs are

`D:\Music\mynaphone\logs\mynaphone.log` by default (`log_dir` in `config.toml`), rotated at 5 MB.
The Activity page shows the live log. Each discarded take also has a `.json` file next to it in the
discard folder with every measurement.

## Reporting a bug

Open an issue with: the Windows version (`winver`), the Mynaphone version (`pip show mynaphone`),
the relevant lines from the log, the `.json` of an affected take if there is one, and whether the
Spotify bridge was connected. Remove anything personal from file names before posting.
