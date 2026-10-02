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

Only during identification, and only to these 6 services:

| Service | What is sent | What comes back |
|---|---|---|
| AcoustID | An acoustic fingerprint of the first 2 minutes and the duration, with your application key | Candidate recording and release ids |
| MusicBrainz | Release, recording and work ids | Titles, credits, dates, labels, ISRCs |
| LRCLIB | Title, artist, album and duration | Lyrics |
| Cover Art Archive | A release id | A cover image |
| Apple's iTunes Search API | Artist and title | A genre |
| Last.fm, only with your key | Artist, title and your API key | Listener tags, used for the genre |

No audio, no file names, no listening history and no account details ever leave the PC. The two
bridges, the Spicetify extension and the browser extension, connect only to the recorder at
127.0.0.1 and never to the internet. When the network is down nothing is sent and nothing is lost.

## Credentials

The app keeps at most 2 credentials in `config.toml`: your AcoustID application key and, if you
added one, your Last.fm API key. `.gitignore` keeps that file out of any fork you push. The app never asks for your Spotify, Google or any other
password, and the bridges use the sessions already signed in to Spotify and Chrome.

## Code you can read

- Everything is open source under the GPL, including the per-app capture helper, which is 300 lines
  of C# in `helper/ProcessLoopback.cs` and is compiled on your own PC by `setup-tools`.
- Every dependency is listed with its license in the third-party notices. `setup-tools` downloads
  ffmpeg from gyan.dev and Chromaprint from the AcoustID GitHub releases, both over HTTPS.
- The test suite runs without network access and without Spotify.

## Reporting a vulnerability

If you find a security problem, please do not post it as a public issue. Use GitHub's private
vulnerability reporting on the repository, or contact the maintainer through
[salmanravoof.com](https://salmanravoof.com).
You will get an acknowledgement within a week.
