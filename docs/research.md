# Offline music archive via the analog hole: research findings

Date: 2026-10-01. Target machine: Windows 10 Pro 22H2 (build 19045), Spotify desktop 1.2.93,
Chrome/Edge/Firefox, OBS 32.2.1, Python 3.13, Nahimic audio APO installed, no ffmpeg/fpcalc yet.

## 1. Verdict in short

- **No existing tool does all of what you asked.** Nothing open-source verifies that a song was
  captured start-to-finish against its known duration, and nothing open-source adds synced lyrics.
  The only product that claims all six features (split, verify, tag, lyrics, dedup, organize) is
  the closed, subscription-priced Audials One.
- **Every building block exists and is maintained**, and I verified the key one live on this PC:
  the Windows media-session API (SMTC) reports title, artist, album, album artist, track number,
  cover thumbnail, playback state, position and duration for Spotify, and title/channel/position for
  YouTube in Chrome. That is the app-agnostic "clock" that makes clean per-song splitting and
  completeness checks possible.
- **Recommendation: build a small Python daemon on top of SpytoRec's design (or fork it), and use
  beets as the library/tagging/lyrics/organization layer.** Roughly 1,500 lines of new code; the
  hard parts (capture, fingerprinting, tagging, lyrics, folder routing) are all off-the-shelf.
- **Loopback recording is the only route to Spotify Lossless in 2026** (librespot-based rippers were
  told by Spotify to stop in Feb 2026 and only get 320 kbps Vorbis), and it is the lowest-risk method
  for your main account because 1x playback from the official app looks like listening.

## 2. Existing tools, ranked

| Tool | Type | Alive? | Split by | Verify complete | Tags | Lyrics | Dedup | Organize | Format | Fit |
|---|---|---|---|---|---|---|---|---|---|---|
| **SpytoRec** (Danidukiyu/SpytoRec) | OSS Python, MIT | Yes, v8.1.0 Sep 2026 | SMTC events + Spotify API | No (no duration check) | Spotify API via mutagen | No | Spotify track ID + filename | Artist/Album | FLAC native | **Best base**. Spotify-only, uses the dead `winsdk` package (no Py 3.13 wheels) |
| **Offstream** (revtex/offstream) | OSS .NET 10, MIT | New, Aug-Sep 2026, 1 author | SMTC + window title + silence | <30 s discard only | Spotify / Last.fm | No | 4 policies | Templates | FLAC/MP3/Opus via ffmpeg | Good design, **Windows 11 only** (blocker) |
| **Spytify / Spytify+** (jwallet) | OSS C#, MIT | Last release Jan 2023; fork Spytify+ Sep 2026 | Window title poll 70 ms | <30 s discard | Last.fm / Spotify API | No | Skip-if-exists, auto-skip in Spotify | Artist/Album | MP3/WAV (FLAC in fork) | Battle-tested logic to borrow; legacy stack |
| **Audials One 2026** | Commercial, ~$35-60/yr | Yes | Metadata + fingerprint | Unknown | Yes | Yes, synced | Undocumented | Yes | FLAC/MP3/M4A | Does it all, closed, not extensible |
| **Replay Music** (Applian) | Commercial $30 | Yes, Aug 2026 | Silence gaps | No | Fingerprint DB | Unsynced | No | Basic | MP3/FLAC | Silence split fails on gapless streams |
| Sidify / TuneFab / NoteBurner / AudFree | Commercial | Yes | n/a | n/a | Spotify catalog | No | n/a | n/a | MP3 etc | DRM stripping, not analog hole; excluded |
| Audacity / OBS | OSS | Yes | Manual / none | No | Manual | No | No | No | WAV / MKV | Capture only |
| Audio Hijack / Piezo | Commercial, macOS | Yes | Silence / timer | No | Manual | No | No | No | Many | Wrong OS |
| Streamripper / streamWriter | OSS | Dead / radio-only | ICY titles | No | ICY | No | No | Basic | MP3 | Internet radio only |

Useful building blocks found: masonasons/AudioCapture and CingZeoi/AudioLoopbackRecorder
(per-process WASAPI loopback in C++), DubyaDude/WindowsMediaController (.NET SMTC wrapper),
lux032/MusicAutoTagger (watch folder, AcoustID, MusicBrainz tags, LRCLIB synced lyrics,
Artist/Album sort), tranxuanthang/lrcget (bulk LRC fetch), omenmn/detify (Linux: watch
now-playing then fetch with spotDL).

## 3. How each requirement will be met

### 3.1 Capture ("highest quality output of whatever is playing")

Facts that drive the design:
- WASAPI loopback delivers the endpoint's shared-mode mix as 32-bit float at the rate set in
  Sound > Advanced > Default Format. Every app stream is resampled to that rate first, so set it
  to **44,100 Hz** for Spotify (Vorbis and FLAC are 44.1 kHz). YouTube's Opus is 48 kHz; one
  resample is unavoidable for one of the two sources and is inaudible.
- Windows master volume and the per-app mixer slider scale the captured signal on most drivers.
  Keep endpoint, app-mixer and Spotify's own slider at 100 %.
- Audio enhancements run before the loopback tap. **Nahimic is installed on this PC** and must be
  disabled or uninstalled; also tick "Disable all enhancements" on the playback device.
- Exclusive-mode playback never reaches loopback. Spotify desktop added an **Exclusive Mode**
  switch in March 2026; it must stay OFF.
- Per-process loopback (`AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK`) is documented as build
  20348+, but OBS, NAudio 3 and a Microsoft-samples issue confirm it works on Windows 10 2004+
  (build 19041+). OBS 32.2.1 on this PC ships that source, which supports the claim for 19045. It
  needs native code (no Python lib exposes it): a small C#/NAudio 3 or Rust `wasapi` crate helper.
- Dropout detection: every `IAudioCaptureClient::GetBuffer` returns `DATA_DISCONTINUITY` and
  `TIMESTAMP_ERROR` flags; PortAudio-based libs expose `paInputOverflow`. Any mid-track glitch
  marks the take bad.
- ffmpeg still has no native WASAPI input (ticket #9408 open). Use it only as the FLAC encoder,
  not the capture engine. python-sounddevice has no loopback either.

Three capture options, in order of recommendation:
1. **Phase 1: endpoint loopback with PyAudioWPatch** (PortAudio fork, Py 3.13 wheels, Jan 2026).
   Zero native code. Risk: notification sounds from other apps land in the recording. Mitigate by
   silencing Windows notification sounds and recording only while SMTC says the music app is
   Playing. This is what SpytoRec, Spytify and Offstream do by default.
2. **Phase 2: per-process loopback via a tiny native helper** (NAudio 3 `WithProcessLoopback` or
   Rust `wasapi` crate) that pipes float32 PCM to the Python daemon. Clean isolation of Spotify.exe
   or the browser process tree, no virtual cable, nothing else in the mix. Verified viable on this
   build via OBS.
3. **Fallback: VB-CABLE** (free). Set Spotify's own Output Device to "CABLE Input", record "CABLE
   Output" as an ordinary input, monitor through Voicemeeter or "Listen to this device". Proven
   (Spytify ships this), but adds latency to what you hear and an extra device to keep at 44.1 kHz.

Output: 44.1 kHz FLAC. 16-bit for lossy sources (Spotify Very High 320 kbps Vorbis, YouTube
Opus ~130 kbps), 24-bit only if you subscribe to Spotify Lossless. FLAC of a lossy source gains no
fidelity but avoids a second lossy generation and stays splittable and taggable. Expect ~25-30 MB
per 4-minute track.

Spotify quality in India (2025-26): Very High 320 kbps on Premium Standard (Rs 199); Lossless up to
24-bit/44.1 kHz only on **Premium Platinum (Rs 299/mo)**, desktop app 1.2.67+. Spotify Free is capped
at 160 kbps and inserts ads. YouTube browser audio is Opus ~128-160 kbps or AAC 128; the 256 kbps
Premium tier is not served to downloaders since Aug 2025 and never applies to in-browser playback.

Spotify settings that break clean captures: Normalize volume OFF, Crossfade OFF, Automix OFF,
Exclusive Mode OFF, in-app EQ off, volume 100 %. Gapless can stay on because splitting is driven by
metadata, not silence. (Your prefs file holds no overrides, so normalization is currently ON by
Spotify default and must be switched off.)

### 3.2 Song boundaries and "captured from beginning to end"

Primary signal: **SMTC** (`Windows.Media.Control`), installed and probed on this PC with the
maintained `winrt-Windows.Media.Control` 3.2.1 package (the older `winsdk` package is dead, last
release 2023, no Python 3.13 wheels). Live result from the probe:

```
Spotify.exe   title=Pookkalae Sattru Oyivedungal  artist=A.R. Rahman
              album=I (Original Motion Picture Soundtrack)  album_artist=A.R. Rahman  track#=4
              thumb=yes  status=Paused  position=0:00:19.83  end=0:05:08.16
chrome.exe    title=New Focus Deck!  artist=Baalorlord  album=(none)  position=0:29:47  end=1:17:11
```

Events: `MediaPropertiesChanged`, `PlaybackInfoChanged`, `TimelinePropertiesChanged`,
`SessionsChanged`. Not exposed: year, disc number, ISRC, catalog IDs, YouTube video ID, Spotify URI.

Completeness rule (a take is kept only if all hold):
1. First `Playing` after a title change was observed with position < ~1.5 s.
2. No `Paused`/`Stopped` and no position jump > 1.5 s unexplained by wall-clock (seek) during the take.
3. Take ended on the next title change (or Stopped) with expected position close to `EndTime` (±1.5 s).
4. Recorded sample count matches `EndTime` (±1.5 s), no capture discontinuity flags, no abnormal mid-file silence.
5. Post-capture fingerprint (AcoustID) agrees with the claimed artist/title when a match exists.

Known quirks: Spotify fires `MediaPropertiesChanged` 2-3 times per track (thumbnail arrives late),
so debounce; Spotify's SMTC position has occasionally stuck at 0:00 after updates, so cross-check
against wall-clock; Firefox's timeline reporting to SMTC is a long-open bug, so prefer Chrome/Edge
for YouTube. Keep a 5 s pre-roll ring buffer (SpytoRec's trick) so the file starts on the real first
sample even when the change event arrives late.

Secondary signals:
- **Spotify Web API** `/me/player` (poll 1-2 s): track id, `progress_ms`, `duration_ms`, album
  release date, 640 px cover, track/disc numbers, `currently_playing_type` (drops ads). Still
  works in 2026 for a personal dev-mode app, but since Feb/Mar 2026 the app owner must be
  Premium, redirect must be `http://127.0.0.1:port`, and **ISRC/popularity/label are stripped**, so
  ISRC must come from MusicBrainz. Spotify window title ("Artist - Song" / "Advertisement") is a
  tertiary fallback.
- **YouTube**: SMTC never gives the video ID. Get it from a 20-line MV3 browser extension that
  posts `location.href` and `<video>` events to the daemon (also gives true seek/pause telemetry),
  or Chrome DevTools Protocol on a dedicated profile. Then `ytmusicapi` (v1.12.3, Sep 2026)
  `get_song`/`get_watch_playlist`/`get_album` for album, track number, year, square cover; and
  `yt-dlp --dump-json` for "Topic"/auto-generated tracks. Only record when the source is
  music.youtube.com, or the video is typed as a music video, or the fingerprint identifies it; the
  Chrome session above was a gaming stream and must be ignored.

### 3.2b Spicetify (installed: 2.44.0, patched against Spotify 1.2.93, Marketplace only, no extensions yet)

Spicetify injects JavaScript into Spotify's Chromium UI. It cannot touch audio (the audio pipeline
is native and unchanged, so capture still goes through loopback), but a ~60-line extension can
stream exact player state to the daemon over a local WebSocket, which beats SMTC for Spotify:

- `Spicetify.Player.data` (PlayerState): `item.uri` (exact track id), `item.name`, `item.artists[]`,
  `item.album.{uri,name,images}`, `item.metadata` (50+ keys: album_title, artist_uri, duration,
  popularity, image_xlarge_url ...), `duration`, `positionAsOfTimestamp`, `timestamp`, `isPaused`,
  **`isBuffering`**, **`playbackQuality`**, `playbackId`, `context.uri`, `nextItems[]`.
- Events: `songchange`, `onplaypause` (PlayerState), `onprogress` (ms).
- `Spicetify.CosmosAsync.get("https://api.spotify.com/v1/tracks/<id>")` and `/albums/<id>` use the
  logged-in client's own token: no developer app, no Premium-dev-mode rules, no redirect URI.
  Whether `external_ids.isrc` survives on client tokens after the Feb 2026 stripping is untested.
- `Spicetify.GraphQL` for album/artist details; `Spicetify.getAudioData(uri)` for beat/section
  analysis; the internal lyrics endpoint that the bundled `lyrics-plus` app reads (Spotify's
  Musixmatch-sourced line-synced lyrics, plus NetEase/Musixmatch/Genius providers) is reachable
  the same way and often covers Indian film songs that LRCLIB lacks.

Why it matters for a flaky connection: `isBuffering` exposes rebuffer stalls (audible gaps that
SMTC cannot see), and `playbackQuality` reveals when Spotify silently drops to a lower bitrate.
Both become discard rules. `nextItems` lets the daemon pre-check the dedup index before a track
starts. Caveat: Spicetify breaks on every Spotify update until `spicetify apply` (or `spicetify
upgrade`) is re-run; SMTC stays as the fallback signal, and the only signal for YouTube and other apps.

### 3.3 Identification, tags, cover art

- **AcoustID + Chromaprint (`fpcalc`) then MusicBrainz**: free key, max 3 req/s; MusicBrainz 1 req/s.
  Confirms identity of the whole recording (score 0.9+ and duration within ±2 s), returns
  MBIDs, ISRC, release group type (soundtrack/single/EP/compilation), date, disc/track numbers,
  composer credits. This is also the dedup key.
- Fallback identifier: `shazamio` 0.8.1 (unofficial, bursty 429s) or SongRec; returns ISRC and
  album/year, then re-query MusicBrainz by ISRC.
- Cover art: Cover Art Archive by release MBID, else Spotify 640 px / YouTube Music square art.
  Never the SMTC thumbnail (~300 px).
- **Indian film music caveat**: MusicBrainz coverage of Bollywood/Tollywood/Kollywood is thin, so
  expect frequent "no match". Fallbacks: Spotify's own fields (album title regex such as
  "Original Motion Picture Soundtrack", "OST", "From the Motion Picture", "(From ...)"), Deezer's
  keyless API (`record_type`, contributors, label), Discogs (best for composer / music-director
  credits). The track playing during the probe was tagged by Spotify as "I (Original Motion Picture
  Soundtrack)", which is exactly the heuristic case.
- Tag writer: `mutagen` (FLAC Vorbis comments + `METADATA_BLOCK_PICTURE`), or let beets'
  mediafile do it.

### 3.4 Synced lyrics

- **LRCLIB** (lrclib.net): free, keyless, `GET /api/get?track_name&artist_name&album_name&duration`
  with ±2 s tolerance returns `syncedLyrics` (LRC) and `plainLyrics`; full DB dumps available for
  offline use. `syncedlyrics` PyPI package adds Musixmatch/NetEase scrapers as fallbacks (break
  periodically). Musixmatch's official API only gives 30 % previews on the free plan.
- beets `lyrics` plugin: `sources: [lrclib, ...]`, `synced: yes`; writes LRC into the FLAC `LYRICS`
  Vorbis comment (and SYLT/USLT for MP3); millisecond timestamps accepted since 2.14.1 (Sep 2026).
- Store **both** embedded `LYRICS` and a sidecar `.lrc`: foobar2000 (OpenLyrics), MusicBee,
  Poweramp 948+, Navidrome/Symfonium, Jellyfin 10.9+/Finamp read the embedded tag; Plex/Plexamp
  reads only sidecars.

### 3.5 Don't re-record what's already archived

Three-tier check, run the moment a new track starts (before committing a take):
1. Own SQLite index: normalized `artist|title` + duration ±2 s (offline, instant).
2. beets DB: `acoustid_id` / `mb_trackid` equality (catches re-titled duplicates).
3. Local `pyacoustid.compare_fingerprints` for near-misses (no network).

If hit: don't record. Optionally skip the track in the player via SMTC's `try_skip_next_async`
when running in a "harvest" mode. beets' `duplicate_action: skip` is the final gate at import.

### 3.6 Organization

**beets 2.14.1** (Sep 2026, Python 3.10+, Windows supported) is the only candidate that runs
unattended (`beet import -q -s --set ...` or an `ImportSession` subclass), keeps a queryable SQLite
library, fingerprints via `chroma`, fetches synced lyrics, embeds art, and routes files by
MusicBrainz release-group type with query-based `paths:`. Picard needs its GUI; Mp3tag,
TagScanner and OneTagger cannot be scripted. Path rules (first match wins; note 2.x stores
secondary types in `albumtypes`, so query that, not `albumtype`):

```yaml
paths:
  albumtypes:soundtrack: Soundtracks/$album%aunique{}/%if{$disctotal>1,$disc-}$track $title
  singleton:             Artists/%the{$artist}/Singles/$title
  albumtypes:single:     Artists/%the{$albumartist}/Singles/$title
  albumtypes:ep:         Artists/%the{$albumartist}/$album%aunique{} [EP]/$track $title
  comp:                  Artists/Various Artists/$album%aunique{}/$track $title
  default:               Artists/%the{$albumartist}/$album%aunique{}/%if{$disctotal>1,$disc-}$track $title
```

For tracks MusicBrainz can't match, the daemon imports with `--set albumtypes=soundtrack` from its
own title heuristic so the same rule still routes them under `Soundtracks/`. Plugins to enable:
musicbrainz, chroma, discogs, deezer, lyrics, fetchart, embedart, lastgenre, ftintitle, the, scrub,
duplicates, albumtypes, inline.

Starter config:

```yaml
directory: D:\Music\Library
library:   D:\Music\beets.db
import:
  write: yes
  copy: yes
  autotag: yes
  quiet_fallback: skip
  duplicate_action: skip
  duplicate_keys:
    item: mb_trackid acoustid_id
    album: mb_albumid
plugins: musicbrainz chroma discogs deezer lyrics fetchart embedart lastgenre ftintitle the scrub duplicates albumtypes inline
chroma:
  auto: yes
lyrics:
  auto: yes
  synced: yes
  sources: [lrclib, genius]
fetchart:
  auto: yes
embedart:
  auto: yes
lastgenre:
  auto: yes
  count: 1
the:
  the: yes
  a: no
albumtypes:
  types: [[ep, EP], [single, Single], [soundtrack, OST], [live, Live], [compilation, Anthology], [remix, Remix]]
  ignore_va: compilation
  bracket: "[]"
item_fields:
  is_ost: "'soundtrack' in (albumtypes or [])"
replace:
  '[\\/]': _
  '^\.': _
  '[\x00-\x1f]': _
  '[<>:"\?\*\|]': _
  '\.$': _
  '\s+$': ''
  '^\s+': ''
  '^-': _
```

## 4. Proposed architecture

```
[Spotify.exe] [chrome.exe: music.youtube.com] [any SMTC app]
       |                 |                          |
       v                 v                          v
  SMTC listener (winrt-Windows.Media.Control)   single clock: title/artist/album, status, position, duration
       |         + Spotify Web API poll (optional)  + browser mini-extension (YouTube video id)
       v
  Session state machine: track start / clean-play / end  ->  verdict KEEP or DISCARD
       |
  Capture engine: PyAudioWPatch endpoint loopback (phase 1) | native per-process loopback helper (phase 2)
       |   5 s pre-roll ring buffer, float32 44.1 kHz, discontinuity flags
       v
  Writer: FLAC (ffmpeg or soundfile) into D:\Music\inbox\<uuid>.flac + <uuid>.json (all events)
       |
  Post-processor (queue, retries, works offline and catches up when the link returns):
     fpcalc -> AcoustID -> MusicBrainz  (identity, MBIDs, ISRC, release type, year)
     fallback: shazamio / Spotify fields / Deezer / Discogs / title heuristics
     LRCLIB synced lyrics  ->  LYRICS tag + .lrc sidecar
     dedup check (SQLite + beets)  ->  beet import -q -s  ->  Soundtracks/ or Artists/<Artist>/<Album|Singles>/
```

Design notes for your low-connectivity situation: capture and the completeness verdict need no
internet at all. Everything that needs the network (AcoustID, MusicBrainz, LRCLIB, cover art) sits
in a retry queue, so a disconnection never loses a take; it just delays tagging. Spotify's own SMTC
fields are enough to write provisional tags offline.

## 5. Alternatives and how they compare (for completeness)

| Path | What you get | Speed | Risk | Note |
|---|---|---|---|---|
| Loopback of Spotify Very High | 320 kbps Vorbis decoded to FLAC | 1x | Lowest to account; ToS breach like all others | Only way to get **Spotify Lossless** |
| Zotify (Googolplexed0 fork, Sep 2026) | The original 320 kbps Vorbis file + perfect tags | 10x | 2 confirmed suspensions after days of nonstop use; README says use a burner Premium account | Same bits as loopback of Very High, 1/3 the size; cannot get Lossless |
| spotDL / yt-dlp 251 | Opus ~130 kbps from YouTube Music, Spotify tags | fast | YouTube bot checks: needs Deno + cookies, breaks every few weeks | Wrong-version matches happen |
| JioSaavn downloaders | 320 kbps AAC, good Indian masters | fast | Streams unprotected; ToS breach | Thin for Western catalog |
| Apple Music via gamdl | AAC 256 / ALAC | fast | Widevine circumvention, cookies expire | Available in India |
| Deezer/Qobuz/Tidal FLAC | True lossless | fast | Not available in India without foreign account | - |

Legal framing (factual, not advice): loopback recording touches no protection measure, which is
why it is called the analog hole, but it is still a reproduction and a Spotify/YouTube ToS breach.
India's Copyright Act s.52(1)(a) private-use fair dealing is the usual argument for personal
archiving; s.65A anti-circumvention targets DRM-stripping tools (Zotify, gamdl, Sidify), not
loopback. Everything here is for your personal, non-distributed archive.

## 6. Build plan

| Phase | Deliverable | Effort |
|---|---|---|
| 0 | System prep: default format 24-bit/44.1 kHz, enhancements + Nahimic off, Spotify normalize/crossfade/automix/exclusive off, install ffmpeg + fpcalc + beets | 1 hour |
| 1 | SMTC listener + state machine + endpoint-loopback capture + FLAC writer + completeness verdict; JSONL event log per take | 2-3 days |
| 2 | Post-processor: AcoustID/MusicBrainz, fallbacks, LRCLIB, mutagen provisional tags, beets import with Soundtracks/Artists routing, SQLite dedup gate | 2-3 days |
| 3 | Spotify Web API enrichment (needs a Premium dev-mode app) and YouTube mini-extension + ytmusicapi | 1-2 days |
| 4 | Per-process loopback helper (NAudio 3 or Rust) replacing endpoint loopback; Task Scheduler autostart; tray status | 2 days |

Open decisions: (a) Python daemon from scratch vs forking SpytoRec (from scratch is favoured, borrowing
its ideas, since it is Spotify-only and tied to the dead `winsdk` package); (b) whether to subscribe
to Spotify Platinum for Lossless, which changes the 16-bit vs 24-bit choice; (c) whether a
"harvest mode" that auto-skips already-archived tracks is wanted.

## 7. Key sources

Capture: MS loopback docs https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording ;
process loopback enum https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ne-audioclientactivationparams-audioclient_activation_type ;
Win10 2004 confirmation https://github.com/microsoft/Windows-classic-samples/issues/343 and https://obsproject.com/kb/application-audio-capture-guide ;
NAudio 3 https://github.com/naudio/NAudio/blob/main/Docs/WasapiRecorder.md ; Rust wasapi https://docs.rs/wasapi ;
PyAudioWPatch https://github.com/s0d3s/PyAudioWPatch ; ffmpeg WASAPI ticket https://ffmpeg.org/pipermail/ffmpeg-trac/2025-May/073534.html ;
Spotify Exclusive Mode https://community.spotify.com/t5/Community-Blog/Desktop-Exclusive-Mode-now-available/ba-p/7371590 ;
Spotify quality https://support.spotify.com/us/article/audio-quality/ ; Platinum India https://www.spotify.com/in-en/platinum/ ; VB-CABLE https://vb-audio.com/Cable/

Now-playing: SMTC docs https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssession ;
app support table https://github.com/ModernFlyouts-Community/ModernFlyouts/blob/main/docs/GSMTC-Support-And-Popular-Apps.md ;
PyWinRT https://github.com/pywinrt/pywinrt ; Spotify Feb-2026 API changes https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide ;
ytmusicapi https://ytmusicapi.readthedocs.io ; AcoustID https://acoustid.org/webservice ; MusicBrainz limits https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting ;
shazamio https://github.com/shazamio/ShazamIO ; LRCLIB https://lrclib.net/docs ; syncedlyrics https://github.com/moehmeni/syncedlyrics

Library: beets changelog https://beets.readthedocs.io/en/stable/changelog.html ; path formats https://beets.readthedocs.io/en/stable/reference/pathformat.html ;
chroma https://beets.readthedocs.io/en/stable/plugins/chroma.html ; lyrics https://beets.readthedocs.io/en/stable/plugins/lyrics.html ;
albumtypes https://beets.readthedocs.io/en/stable/plugins/albumtypes.html ; importing from Python https://discourse.beets.io/t/importing-from-python/251 ;
MB coverage of Indian music https://community.metabrainz.org/t/is-there-any-kind-of-project-to-improve-holes-in-musicbrainz-coverage/367186 ;
Plex sidecar-only lyrics https://support.plex.tv/articles/215916117-adding-local-lyrics/

Existing tools: SpytoRec https://github.com/Danidukiyu/SpytoRec ; Offstream https://github.com/revtex/offstream ; Spytify https://github.com/jwallet/spy-spotify ;
Spytify+ https://github.com/PetraJThomas/spytify-plus ; Audials https://audials.com/en/one ; Replay Music https://applian.com/replay-music/ ;
AudioCapture (per-process) https://github.com/masonasons/AudioCapture ; MusicAutoTagger https://github.com/lux032/MusicAutoTagger ; lrcget https://github.com/tranxuanthang/lrcget

Alternatives: Zotify fork https://github.com/Googolplexed0/zotify ; ban report https://github.com/zotify-dev/zotify/issues/316 ;
librespot lossless closed https://github.com/librespot-org/librespot/issues/1580 ; yt-dlp https://github.com/yt-dlp/yt-dlp/releases ;
yt-dlp premium formats gone https://github.com/yt-dlp/yt-dlp/issues/14208 ; spotDL https://github.com/spotDL/spotify-downloader ;
Spotify User Guidelines https://www.spotify.com/us/legal/user-guidelines/plain/ ; India s.65A https://lawgist.in/copyright-act/65A
