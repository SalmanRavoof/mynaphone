# Settings reference

Settings live in `config.toml` in the Mynaphone folder. The **Settings** page edits the common ones;
the rest are edited in the file. Comments in the file explain each line. Changes in the Capture and
Rules groups apply the next time the recorder starts.

## Folders (`[paths]`)

| Setting | Default | What it does |
|---|---|---|
| `inbox_dir` | `D:/Music/mynaphone/inbox` | Verified recordings wait here as FLAC until they are identified and filed. |
| `discard_dir` | `D:/Music/mynaphone/discard` | Rejected recordings, each with a `.json` explaining why. Pruned after `keep_discards_days`. |
| `library_dir` | `D:/Music/Library` | The finished collection. |
| `db_path` | `D:/Music/mynaphone/mynaphone.db` | The index of songs, takes and missing metadata (SQLite). |
| `log_dir` | `D:/Music/mynaphone/logs` | Rotating log files. |

Relative paths are resolved from the folder that contains `config.toml`.

## Capture (`[capture]`)

| Setting | Default | What it does |
|---|---|---|
| `mode` | `process` | `process` records only the source app's own audio through the capture helper. `device` records the whole output device (older method; other apps' sounds end up in the mix). |
| `device` | `default` | Device mode only. `default` follows the Windows default output. Any part of a device name selects that device, for example `CABLE Output` for VB-CABLE. |
| `sample_rate` | `48000` | Capture rate in process mode. In device mode, `0` means the device's own rate. |
| `bit_depth` | `16` | Bit depth of the recorded FLAC. `24` only pays off for a lossless source. |
| `preroll_seconds` | `3.0` | Seconds of audio always kept in memory so a late track-change notice loses nothing. |
| `lead_margin_seconds` | `0.5` | How far before the notice a take starts; leading silence is trimmed afterwards. |

## Rules (`[rules]`)

| Setting | Default | What it does |
|---|---|---|
| `sources` | `["Spotify.exe"]` | Apps to record, by process name. The Settings page adds `chrome.exe` and `msedge.exe` for YouTube. |
| `duration_tolerance_seconds` | `1.5` | A take is kept only if its length, and the wall-clock time it took, are within this many seconds of the song's reported duration. |
| `min_duration_seconds` | `45` | Shorter items are never recorded (ads, jingles). |
| `max_duration_seconds` | `900` | Longer items are never recorded (podcasts, audiobooks, DJ mixes). |
| `discard_on_pause` | `true` | Discard if playback was paused during the song. |
| `discard_on_seek` | `true` | Discard if a seek was detected. |
| `discard_on_foreign_audio` | `true` | Device mode only: discard if any other app made any sound during the take. In process mode other apps cannot be recorded, so this is informational. |
| `foreign_audio_threshold_db` | `-120` | Level another app must reach to count. `-120` or lower means any sound at all. |
| `ignore_titles` | `["Advertisement", "Spotify"]` | Media titles treated as not music (Spotify Free ads). |
| `keep_discards_days` | `3` | Days to keep rejected recordings. `0` deletes them at once. |
| `harvest_mode` | `false` | Skip songs that are already archived. Also toggled from the Status page and tray. |

## Spotify bridge (`[bridge]`)

| Setting | Default | What it does |
|---|---|---|
| `enabled` | `true` | Listen for the Spicetify and browser extensions. |
| `port` | `8765` | Local port the extensions connect to on 127.0.0.1. Change both here and in the extensions if it clashes. |

## Re-recording (`[quality]`)

| Setting | Default | What it does |
|---|---|---|
| `upgrade_on_higher_tier` | `true` | Re-record an archived song when it plays at a higher quality tier (for example after a Spotify Premium upgrade) and replace the older copy. |

## Library (`[library]`)

| Setting | Default | What it does |
|---|---|---|
| `format` | `aac` | `aac` (M4A; cars, iPhones, Android), `mp3` (plays anywhere, larger), `opus` (smallest; phones and computers, most cars can't play it) or `flac` (lossless). Lossless-tier captures are always FLAC. Changing it affects new songs only. |
| `aac_bitrate` | `256` | Bitrate in kbps for the lossy formats (the name is historical). The Settings page offers AAC 192/256/320, MP3 256/320 and Opus 128/160. |

The Settings page shows, under the Library folder, how many songs fit on that drive with the chosen
format: free space minus 2 GB spare and the working space for takes waiting in the inbox and
rejected takes kept for inspection, divided by the size of an average 4.5-minute song.

## Identification (`[identify]`)

| Setting | Default | What it does |
|---|---|---|
| `acoustid_key` | empty | Your AcoustID application key. Required for fingerprint identification. |
| `musicbrainz_contact` | empty | Contact MusicBrainz asks clients to send (an email or URL). Left empty, the project URL is sent. |
| `lastfm_api_key` | empty | Optional Last.fm API key. With it, Last.fm's tags give a genre to songs that Apple and MusicBrainz have none for. |
| `apple_country` | `US` | The Apple store searched for genres, as a two-letter country code. The US store covers Indian film songs too. |

## Application (`[app]`)

| Setting | Default | What it does |
|---|---|---|
| `start_minimized` | `false` | Open hidden in the tray. |
| `close_to_tray` | `true` | Closing the window keeps the recorder running in the tray. |
| `autostart_recording` | `true` | Start listening as soon as the app opens. |
| `show_tooltips` | `true` | Show a short explanation when the mouse rests on a button or setting. |

**Start with Windows** on the Settings page is not stored in the file; it adds or removes a value
named `Mynaphone` in your user's Run key in the registry.

## How tiers are ranked

The recorder uses tiers to decide whether a replay is worth re-recording, from lowest to highest:
`low`, `youtube`, `normal`, `high` (Spotify Free, 160 kbps), `very_high` (Spotify Premium,
320 kbps), `hifi` and `hifi24` (Spotify lossless). The tier comes from the Spotify bridge; without
it, Spotify captures are stored as `unknown`.
