# Security and privacy

This page lists what Mynaphone can reach on your PC, what leaves it, and how to report a problem.

## What it can reach

- It runs as your user, never as administrator, and asks for no elevation at any point.
- It reads the audio of the apps you list as sources, through Windows' per-app capture, and nothing
  else that plays on the PC.
- It reads the "now playing" information that media apps publish to Windows, which is the same data
  the media keys and the volume flyout use.
- It writes only inside the folders you choose in Settings, plus its own log folder.
- With "Start with Windows" ticked, it adds one value under your user's Run key in the registry and
  nothing elsewhere.

## Data that leaves your PC

Only while a kept take is identified and filed, and only to these services:

| Service | What is sent | What comes back |
|---|---|---|
| [AcoustID](https://acoustid.org/webservice) | An acoustic fingerprint of the first 2 minutes and the duration, with your application key | Candidate recording and release ids |
| [MusicBrainz](https://musicbrainz.org/doc/MusicBrainz_API) | Release, recording and work ids | Titles, credits, dates, labels, ISRCs |
| [LRCLIB](https://lrclib.net/docs) | Title, artist, album and duration | Lyrics |
| [Cover Art Archive](https://musicbrainz.org/doc/Cover_Art_Archive/API) | A release id | A cover image |
| Spotify's or YouTube's image server | The cover address the player reported | The full-size cover |
| [Apple's iTunes Search API](https://performance-partners.apple.com/search-api) | Artist and title | A genre |
| [Last.fm](https://www.last.fm/api), only with your key | Artist, title and your API key | Listener tags, used for the genre |
| YouTube Music, for YouTube captures | A search for the song or film | Album, year and track number |
| youtube.com, for YouTube captures without the extension's description | The video id | The public watch page, for the song credits |

No audio, no file names and no account details ever leave the PC. Each service sees only the
songs it's asked about, one lookup at a time, with your IP address and, for AcoustID and Last.fm,
your key.

The Spicetify extension asks Spotify's own servers for a track's details, the same requests the
Spotify app makes, and passes them only to the recorder at 127.0.0.1. The browser extension talks
only to the recorder. When the network is down nothing is sent and nothing is lost.

## Credentials

The app keeps at most 2 credentials in `config.toml`: your AcoustID application key and, if you
added one, your Last.fm API key. `.gitignore` keeps that file out of any fork you push. The app never asks for your Spotify, Google or any other
password, and the bridges use the sessions already signed in to Spotify and Chrome.

## Code you can read

- Everything is open source under the GPL, including the per-app capture helper, which is 300 lines
  of C# in `helper/ProcessLoopback.cs` and is compiled on your own PC by `setup-tools`.
- Every dependency is listed with its license in the [third-party notices](../THIRD_PARTY_NOTICES.md).
  `setup-tools` downloads ffmpeg from the [gyan.dev builds](https://www.gyan.dev/ffmpeg/builds/) and
  Chromaprint from the [Chromaprint releases on GitHub](https://github.com/acoustid/chromaprint/releases),
  both over HTTPS.
- The test suite runs without network access and without Spotify.

## Reporting a vulnerability

If you find a security problem, please don't post it as a public issue. Use
[GitHub's private vulnerability reporting](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately)
from the repository's **Security** tab, or contact the maintainer through
[salmanravoof.com](https://salmanravoof.com).
You will get an acknowledgement within a week.
