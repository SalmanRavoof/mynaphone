# How Mynaphone works

This page explains the design so that the behavior you see makes sense. You don't need any of it to
use the app.

## From a playing song to a filed one

```
Spotify / browser ──audio──▶ per-app capture helper ──PCM──▶ ring buffer ──▶ take
      │                                                                      │
      └──"now playing" (Windows media session + bridges)──▶ state machine ──▶ verdict
                                                                             │ keep
                                                     inbox FLAC + sidecar ◀──┘
                                                             │
     fingerprint ─▶ AcoustID ─▶ MusicBrainz ─▶ lyrics ─▶ cover ─▶ encode ─▶ tag ─▶ file into library
```

## Capturing one app's audio

Windows can hand an application the audio stream of one other process. That facility, called process
loopback, arrived with Windows 10 version 2004.

Mynaphone's helper, a 300-line C# program, asks Windows for Spotify's stream, or Chrome's, and
passes it to the app as raw audio. Because only that process's audio is in the stream, a
notification chime, a video in another window or a game cannot get into a recording.

The older "device" mode records the whole output device instead. In that mode a monitor watches every
app's audio session and rejects a take if anything else made a sound while it ran.

The app keeps the last 3 seconds of audio in memory at all times. Windows reports a track change 1
to 3 seconds after the audio has switched, so when the notice arrives the recorder reaches back into
that buffer to the moment the song began. Leading silence is trimmed afterwards.

## Knowing what is playing

The recorder has 3 sources of information, each more detailed than the last.

The Windows media session comes first. Every modern media app tells Windows its title, artist, album,
cover, playback state and position, which is the same data the media keys and the volume flyout use.
It works for Spotify, browsers and most players, and it is the recorder's clock for starts, ends,
pauses and seeks.

The Spotify bridge adds what Windows doesn't know. It is optional and needs Spicetify installed. A
Spicetify extension inside Spotify reports the
exact track id and album id, the track and disc numbers, and the quality tier the song played at.
It also passes on buffering, Spotify's own synced lyrics, and album facts such as the release date
and label, all over a local WebSocket.

YouTube gets the same treatment from the browser extension, which comes in the repository and is
loaded into Chrome or Edge by hand. On a YouTube page it reports the video id,
whether YouTube marks the video as music, and every play, pause, seek and speed change. On YouTube
Music it also reads the artist, album and year from the player bar.

## Deciding whether a take is kept

A take is kept only if all of these are true:

- The recorder saw the song within about 1.5 seconds of its start.
- Playback was never paused or seeked, and never ran faster or slower than normal speed.
- No buffering stall was reported, and the wall-clock time from start to end matches the song's
  reported duration within 1.5 seconds. A stall on a weak connection makes the take run long.
- The capture reported no dropouts and the output device did not change.
- The recorded length matches the reported duration within 1.5 seconds.
- The app's slider in the Windows Volume Mixer and the app's own volume control were at 100 % when
  the take started. The Windows master volume and mute don't affect per-app capture, so they're ignored.
- In device mode, no other app made a sound.

Every take, kept or not, is logged with its measurements, so you can see why a verdict went the way
it did and the rules can be revisited later.

## Identifying the song

Identification runs in 5 steps.

1. Chromaprint computes an acoustic fingerprint of the first 2 minutes of the recording.
2. AcoustID matches the fingerprint against its database and returns MusicBrainz recording and
   release ids with a confidence score. This step needs the free application key entered on the
   Set up page; without it the recorder goes straight to step 5. Among candidate releases, the one whose album title matches
   what Spotify reported wins. Failing that, an ordinary album beats a compilation.
3. MusicBrainz supplies the release (label, catalog number, barcode, country, date, type, genres,
   track and disc numbers), the recording (ISRC, singers and performers) and the linked work
   (composer, lyricist, language).
4. Spotify's own facts fill in whatever is still missing, among them the release date, explicit
   flag, popularity, copyright line and ISRC.
5. When nothing matched, the recorder falls back on the capture's own tags. A text rule recognizes
   soundtrack albums from phrases such as "Original Motion Picture Soundtrack" and "From ...", and
   treats the album artist of a soundtrack as its composer. For YouTube captures, the YouTube Music
   catalog supplies album, year and track number.

## Lyrics and cover art

Spotify's own lyrics come first when the bridge supplied them, because they match the exact
recording and cover languages that LRCLIB often lacks. Otherwise the app asks LRCLIB by title,
artist, album and duration. Synced lyrics go into the file's lyrics tag and into a `.lrc` file next
to it, because some players read one and some read the other. Cover art comes from the capture,
which includes Spotify's 640 px image, and failing that from the Cover Art Archive.

## A song from YouTube that the fingerprint does not know

A video from a label channel such as T-Series or YRF is usually a different edit from the album
recording, so AcoustID can draw a blank. The app then fingerprints again from 45 seconds in, past
any dialogue at the start.

When that fails too, it reads the credits that labels put in the video description. Those lines
name the song, the film, the singers, the lyricist, the music director, the label and the release
date. The YouTube Music catalog then supplies the album, year and track number, and the song is
filed under the film as a soundtrack.

A channel such as YRF is never used as the artist, and a view count is never used as an album.
The browser extension sends that text with each video. Without it, the app reads the public
watch page itself.

## Encoding and filing

The inbox FLAC is a lossless copy of what the app decoded. The recorder encodes it once, to AAC
256 kbps by default, which plays in cars and on phones at about 9 MB a song. Lossless-tier captures
stay FLAC. The file is then placed by type:

- `Soundtracks/<Album (Year)>/<NN Title>` when MusicBrainz marks the release as a soundtrack or the
  text rule does.
- `Artists/<Album artist>/<Album (Year)>/<NN Title>` for albums.
- `Artists/<Artist>/Singles/<Title>` for singles and EPs.
- `Artists/Various Artists/<Album (Year)>/...` for compilations.
- `Unsorted/<Title>` when nothing told the app who performs the song. The Library page lists these
  under **Needs attention**, and a later lookup or a manual edit moves them.

A film song keeps its singers in the artist tag and its music director in the album-artist and
composer tags, so an A. R. Rahman album remains one folder while each track still names Sonu
Nigam or Shreya Ghoshal. When MusicBrainz credits the recording to the composer and lists the singers only
as vocal performers, the app swaps the singers into the artist tag itself.

Tags follow the MusicBrainz Picard conventions, so other players and taggers understand them.

## Tracking what is still missing

Each library song keeps 3 records: the identity that was found, the fields a person typed, which are
never overwritten, and the list of fields still missing. The app retries lyrics every half hour and
full lookups weekly, each with a limit on attempts, so a song that MusicBrainz learns about later
fills itself in.

## Where the network is used

Only during identification, and only for these requests:

- AcoustID receives the fingerprint and the duration.
- MusicBrainz receives release, recording and work ids.
- LRCLIB receives the title, artist, album and duration.
- The Cover Art Archive receives a release id.
- The Spotify bridge and the browser extension talk only to the app, on 127.0.0.1.

No audio ever leaves the PC. When the network is down nothing is sent; lookups queue and retry.

## Words used on these pages

- A take is one attempt to record one song.
- Loopback means recording the sound a PC is already playing.
- A fingerprint is a compact description of how a recording sounds, used to look it up.
- A tier is the quality level a service played a song at, such as Spotify Free, Premium or lossless.
- The inbox is the folder of verified takes waiting to be identified and filed.
