# Settings reference

Settings live in `config.toml` in the Mynaphone folder. The **Settings** page edits the common ones,
and the rest are edited in the file. Each table below gives the setting's name on the Settings page,
where it has one, next to its line in the file.

- Changes in the Capture and Rules groups apply the next time the recorder starts. Select **Stop**
  and then **Start** on the Status page to apply them at once.
- To edit the file by hand, quit Mynaphone first. Selecting **Save settings** rewrites the whole
  file from what the window shows, so edits made while it runs are lost.
- Relative paths are resolved from the folder that contains `config.toml`.

![The Folders and Capture cards of the Settings page](images/settings-folders.png)

## Folders (`[paths]`)

| On the Settings page | In `config.toml` | Default | What it does |
|---|---|---|---|
| **Inbox** | `inbox_dir` | `D:/Music/mynaphone/inbox` | Verified recordings wait here as FLAC until they are identified and filed. |
| None | `discard_dir` | `D:/Music/mynaphone/discard` | Rejected recordings, each with a `.json` explaining why. Pruned after `keep_discards_days`. |
| **Library** | `library_dir` | `D:/Music/Library` | The finished collection. |
| None | `db_path` | `D:/Music/mynaphone/mynaphone.db` | The index of songs, takes and missing metadata, a [SQLite](https://sqlite.org/) database. |
| None | `log_dir` | `D:/Music/mynaphone/logs` | Rotating log files, 5 MB each. |

Under the Library folder, the Settings page shows how many songs fit on that drive with the chosen
format. It takes the free space, keeps 2 GB spare and room for takes waiting in the inbox and
rejected takes kept for inspection, and divides the rest by the size of an average 4.5-minute song.

## Capture (`[capture]`)

| On the Settings page | In `config.toml` | Default | What it does |
|---|---|---|---|
| **Capture method** | `mode` | `process` | `process`, shown as Per app, records only the source app's own audio through the capture helper. `device`, shown as Whole output device, records everything the output device plays, so other apps' sounds end up in the mix. |
| **Capture device** | `device` | `default` | Device mode only. `default` follows the Windows default output. Any part of a device name selects that device, for example `CABLE Output` for [VB-CABLE](https://vb-audio.com/Cable/). |
| None | `sample_rate` | `48000` | Capture rate in process mode. In device mode, `0` means the device's own rate. |
| **Bit depth** | `bit_depth` | `16` | Bit depth of the recorded FLAC. `24` only pays off for a lossless source. |
| None | `preroll_seconds` | `3.0` | Seconds of audio always kept in memory, so a late track-change notice loses nothing. |
| None | `lead_margin_seconds` | `0.5` | How far before the notice a take starts. Leading silence is trimmed afterwards. |

## Rules (`[rules]`)

![The What counts as a complete song card of the Settings page](images/settings-rules.png)

| On the Settings page | In `config.toml` | Default | What it does |
|---|---|---|---|
| **Also record YouTube and YouTube Music playing in Chrome or Edge** | `sources` | `["Spotify.exe"]` | Apps to record, by process name. Ticking the YouTube option adds `chrome.exe` and `msedge.exe`. |
| None | `duration_tolerance_seconds` | `1.5` | A take is kept only if its length, and the wall-clock time it took, are within this many seconds of the song's reported duration. |
| **Minimum length** | `min_duration_seconds` | `45` | Shorter items are never recorded, such as ads and jingles. |
| None | `max_duration_seconds` | `900` | Longer items are never recorded, such as podcasts, audiobooks and DJ mixes. |
| **Discard a take if playback was paused** | `discard_on_pause` | `true` | Discard if playback was paused during the song. |
| **Discard a take if you seeked within the song** | `discard_on_seek` | `true` | Discard if a seek was detected. |
| **Discard a take if any other app made any sound** | `discard_on_foreign_audio` | `true` | Device mode only. Discard if any other app made any sound during the take. In process mode other apps can't be recorded, so it's only logged. |
| None | `foreign_audio_threshold_db` | `-120` | Level another app must reach to count. `-120` or lower means any sound at all. |
| None | `ignore_titles` | `["Advertisement", "Spotify"]` | Media titles treated as not music, such as Spotify Free's ads. |
| **Keep rejected takes** | `keep_discards_days` | `3` | Days to keep rejected recordings. `0` deletes them at once. |
| **Skip songs already in the library (harvest mode)** | `harvest_mode` | `false` | Skip songs that are already archived. Also on the Status page and in the tray menu. |

## Re-recording (`[quality]`)

| On the Settings page | In `config.toml` | Default | What it does |
|---|---|---|---|
| **Re-record archived songs when they play at a higher quality tier** | `upgrade_on_higher_tier` | `true` | Re-record an archived song when it plays at a higher quality tier, for example after a Spotify Premium upgrade, and replace the older copy. |

## Library (`[library]`)

| On the Settings page | In `config.toml` | Default | What it does |
|---|---|---|---|
| **Library format** | `format` | `aac` | `aac` (M4A, for cars, iPhones and Android), `mp3` (plays anywhere, larger), `opus` (smallest, for phones and computers; most cars can't play it) or `flac` (lossless). Lossless-tier captures are always FLAC. Changing it affects new songs only. |
| **Library format** | `aac_bitrate` | `256` | Bitrate in kbps for the lossy formats. The name is historical and applies to MP3 and Opus too. |

The **Library format** menu offers these combinations:

| Menu choice | `format` | `aac_bitrate` |
|---|---|---|
| AAC 256 kbps (M4A), recommended | `aac` | `256` |
| AAC 320 kbps (M4A) | `aac` | `320` |
| AAC 192 kbps (M4A) | `aac` | `192` |
| MP3 320 kbps | `mp3` | `320` |
| MP3 256 kbps | `mp3` | `256` |
| Opus 160 kbps | `opus` | `160` |
| Opus 128 kbps | `opus` | `128` |
| FLAC | `flac` | Ignored |

## Identification (`[identify]`)

These are set on the **Set up** page or in the file.

| On the Set up page | In `config.toml` | Default | What it does |
|---|---|---|---|
| **AcoustID application key** | `acoustid_key` | Empty | Your AcoustID application key. Required for fingerprint identification. |
| Last.fm API key | `lastfm_api_key` | Empty | Optional. With it, Last.fm's tags give a genre to songs that Apple and MusicBrainz have none for. |
| None | `musicbrainz_contact` | Empty | The contact [MusicBrainz asks API clients to send](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting), an email address or URL. Left empty, the project URL is sent. |
| None | `apple_country` | `US` | The Apple store searched for genres, as a 2-letter country code. The US store covers Indian film songs too. |

## Spotify bridge (`[bridge]`)

| On the Settings page | In `config.toml` | Default | What it does |
|---|---|---|---|
| None | `enabled` | `true` | Listen for the Spicetify and browser extensions. |
| None | `port` | `8765` | Local port the extensions connect to on 127.0.0.1. If it clashes, change it here, at the top of `spicetify/mynaphone.js` and in `browser-extension/background.js`, then reinstall both. |

## Application (`[app]`)

![The Application card of the Settings page](images/settings-application.png)

| On the Settings page | In `config.toml` | Default | What it does |
|---|---|---|---|
| **Start recording when the app opens** | `autostart_recording` | `true` | Start listening as soon as the app opens. |
| **Closing the window keeps it running in the tray** | `close_to_tray` | `true` | Closing the window keeps the recorder running in the tray. |
| **Open minimized to the tray** | `start_minimized` | `false` | Open hidden in the tray. |
| **Start with Windows** | None | Off | Adds or removes a value named `Mynaphone` under your user's `Run` key in the registry. It isn't stored in the file. |
| **Show tooltips when the mouse rests on a control** | `show_tooltips` | `true` | Show a short explanation when the mouse rests on a button or setting. |

## How tiers are ranked

The recorder uses tiers to decide whether a replay is worth re-recording. From lowest to highest:

| Tier | Source |
|---|---|
| `unknown` | A Spotify capture made without the bridge |
| `low` | Spotify at Low, about 24 kbit/s |
| `youtube` | YouTube and YouTube Music |
| `normal` | Spotify at Normal, about 96 kbit/s |
| `high` | Spotify at High, about 160 kbit/s, the best Spotify Free offers |
| `very_high` | Spotify Premium at Very high, about 320 kbit/s |
| `hifi`, `hifi24` | Spotify's lossless tier, 16-bit and 24-bit |

The tier for Spotify comes from the Spotify bridge.
Spotify's [audio quality page](https://support.spotify.com/us/article/audio-quality/) lists the
bitrate behind each quality setting.
