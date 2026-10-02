# Questions and answers

Grouped by theme. Legal questions are answered on the [legal notice](legal.md) page and are only
summarized here.

## What it is

### Is this a downloader?

No. Mynaphone records the sound an app is playing on your PC as it plays, the way a screen
recorder does. A 4-minute song takes 4 minutes to capture. The service's servers see one ordinary
playback and nothing else.

### Any DRM or copy protection involved?

No. It never touches a service's protected stream, cache or app internals. Windows hands it the
already-decoded audio on its way to the speakers, through the same mechanism screen recorders use.

### Recording takes hours; why not a download tool?

Three reasons. Recording is the only way to get Spotify's lossless tier out of the app, since the
download tools are stuck at 320 kbps. Playing songs at normal speed through the official app looks
like listening, which keeps your main account safe. And recording breaks no protection measure,
which the download tools do. The cost is time, since an hour of music takes an hour to capture. The
[design research](research.md) compares the options in detail.

### Compared with Audacity or OBS?

Those record whatever you point them at and leave you with one long file. Mynaphone knows which song
is playing, records only that app, splits at song boundaries, throws away anything that wasn't a
clean complete play, identifies the song, tags it, adds lyrics and art, and files it. You never touch
a waveform.

### Intended for whom?

One person keeping a private copy of music they listen to, on their own machine, for their own
listening. It is not built for sharing collections, and it has no feature that could.

## Sound quality

### Sound quality to expect

The same as the stream, never better. Spotify Free plays at 160 kbps, Spotify Premium at 320 kbps,
Spotify's lossless tier up to 24-bit at 44.1 kHz, YouTube at roughly 130 kbps. The capture itself is
lossless, so that step loses nothing, and the one encode to AAC 256 kbps is inaudible for lossy
sources. If you move to a lossless plan, switch the bit depth to 24 in Settings; lossless captures
stay FLAC automatically.

### FLAC from a 160 kbps stream, any gain?

No. A lossless file of a lossy stream is an exact copy of the lossy stream, at 3 times the size.
That's why the library defaults to AAC and keeps FLAC only for captures that were lossless to begin with.

### AAC as the default, and the alternatives

AAC at 256 kbps is the best-supported efficient format: car head units, iPhones and Android phones
all play it, at about 9 MB a song. MP3 plays anywhere but needs 320 kbps for the same quality. Opus
is the smallest but most cars can't play it. All four are offered in Settings, and every one gets
the same tags, cover and lyrics.

### Quiet or distorted recordings

Not if the two volume controls that matter stay at 100 %: the app's own slider, and the app's slider
in the Windows Volume Mixer. The Windows master volume and mute have no effect on per-app capture,
so set those however you like. If either of the two that matter is below 100 % when a song starts,
the take is rejected and the reason names the control.

### Resampling by Windows

Only in device mode, where the whole output device is recorded at the device's rate. In per-app
mode the helper asks for 48 kHz, which matches YouTube's audio, and Spotify's 44.1 kHz stream is
converted once by Windows. For a bit-exact lossless chain, set the capture rate to 44100 in
`config.toml`.

## Accounts and safety

### Account safety with Spotify and YouTube

Mynaphone plays songs at normal speed through the official app, so the service sees ordinary
listening. Harvest mode skips songs rather than playing them faster. The services' terms may still
prohibit recording, and that agreement is between you and them; the [legal notice](legal.md) says more.

### Passwords are never asked for

No. It never asks for a password. The Spotify bridge runs inside the Spotify app you're already
signed in to, and the browser extension runs inside your signed-in browser.

### Data sent off the PC

A fingerprint, titles, ids and durations, sent to AcoustID, MusicBrainz, LRCLIB and the Cover Art
Archive during identification, and the artist and title to Apple and, with your key, Last.fm, for
the genre. No audio, no file names, no listening history. The
[security page](security.md) lists each request.

### Spicetify's effect on Spotify

Spicetify changes Spotify's interface files; it doesn't touch playback or your account. Spotify
updates undo it, and `spicetify apply` puts it back. `spicetify restore` removes it entirely.

## Devices and platforms

### Windows versions that work

Windows 10 version 2004 (build 19041) and later, and Windows 11, 64-bit. Per-app capture arrived
with that version. On older builds the app falls back to whole-device capture.

### Mac and Linux

No. Per-app capture, the media-session information and the tray app are Windows features. The
library it produces plays anywhere.

### Phones

No, the recorder is a desktop app. The library can be copied to a phone, and the lyrics and art
come along.

### Laptops with the lid closed, Bluetooth headphones and sleep

Per-app capture doesn't involve the output device at all, so what you listen through, or whether
you listen, makes no difference. Sleep does: if the PC sleeps, playback stops and the take is
discarded. Set the power plan to stay awake while harvesting.

### Cars and players that read the result

Any head unit that plays AAC from USB reads the tags and cover; the 2018 Mazda3 the app was built
around is the one tested. Synced lyrics are embedded and also written as `.lrc` files. foobar2000 with the
OpenLyrics component, MusicBee, Poweramp, Navidrome with Symfonium, and Jellyfin read the embedded
ones, and Plexamp reads the `.lrc` file.

## Sources and services

### Services it records

Spotify's desktop app, and YouTube and YouTube Music in Chrome or Edge once the bundled browser
extension is loaded. Any other Windows app that reports what it plays, which most players do, can be
added by process name in `config.toml`, untested. Metadata is then limited to what the app reports,
with fingerprinting doing the rest, which needs the free AcoustID key.

### Apple Music, Amazon Music, Tidal, JioSaavn and Gaana

Their Windows apps or browser players can be added as sources by process name. They haven't been
tested, their "now playing" information varies, and there is no bridge for them, so expect more
songs to need a manual check. Spotify and YouTube Music are the two paths tested end to end.

### Podcasts and audiobooks

They aren't recorded, though by length rather than by type. Anything longer than 15 minutes is
skipped as "longer than a song", and the limit is a setting. A short podcast episode or a long song that
falls on the wrong side of that line is the one case to watch for. Spotify Free's audio ads are
skipped by title.

### Ads on Spotify Free

An ad is reported as a different item, so the song before it ends normally and the ad is ignored by
title. With Spicetify's ad-blocking extensions the question doesn't arise.

### Why did a YouTube song get the channel as its artist or a view count as its album?

That was a bug in early builds, fixed in 0.1.0. The app now reads the song credits from the video
description and looks the film up in the YouTube Music catalog. A channel name or a view count
is never used.

Reload the browser extension after updating so it sends the description. A song that was filed
wrongly moves to the right place when you press **Look up again** on the Library page.

### How are a film's singers and its music director handled?

The singers go in the artist tag, and the music director goes in the album-artist and composer
tags. A soundtrack is filed by album, so every song from a film stays in one folder under
`Soundtracks` whoever sings it, and a player that groups by album artist shows the film under its
composer.

### Regular YouTube and the music-only rule

A gaming stream or a review isn't music, and recording it would only create files to delete.
YouTube marks music videos with a Music category, and the extension reads that mark. On
music.youtube.com everything is recorded.

## Metadata and lyrics

### Identifying the song it recorded

By acoustic fingerprint. Chromaprint describes how the first 2 minutes sound, AcoustID matches that
against its database, which needs the free application key from the Set up page, and MusicBrainz
supplies the details. Spotify's own ids and YouTube Music's
catalog serve as cross-checks and fallbacks.

### Fixing a misidentified song

Select it on the Library page, correct the fields and save. Your edits are protected from later
lookups. If the identity itself is wrong, fix the title and artist and select **Look up again**.

### Missing lyricists and ISRCs

Because MusicBrainz doesn't have it for that recording. Regional film music in particular is thinly
credited there. The app marks the field as missing, retries weekly, and lets you type it in.

### Lyrics sources

Spotify's own lyrics first, through the bridge, which covers languages that open databases lack.
LRCLIB second. Synced lyrics are preferred over plain ones, and a song with none is retried every
half hour for 10 attempts.

### Adding your own lyrics or cover

Yes. On the Library page, paste lyrics into the box, with or without timestamps, or choose a cover
image file, and save.

### Soundtracks versus Artists folders

MusicBrainz marks soundtrack releases, and a text rule catches album titles such as "Original Motion
Picture Soundtrack". Everything else is filed under the album artist, with singles and EPs in a
Singles folder. You can override the choice per song on the Library page.

## Storage and performance

### Disk space

About 9 MB per song as AAC, 30 MB as FLAC, plus 2 GB of working space and 30 MB for each take
waiting to be processed. The Settings page shows how many songs fit on the chosen drive.

### CPU and memory

On the author's laptop, with Spotify and Chrome both being watched, the recorder used 0.3 % of the
CPU while listening and a few seconds of one core per song when it encoded. Memory was about 500 MB
with the window open, most of it the Qt interface.

### Time to build a collection

As long as the music. 5,000 songs is about 375 hours of playback, so plan on months of ordinary
listening, or days of unattended harvesting with the speakers muted.

### Working without internet

Recording and verification need no internet. Identification, lyrics and cover art wait in the inbox
until the connection returns, however long that takes, and nothing is lost in the meantime.

## Data and privacy

### Where the data lives

In the folders set in `config.toml`: the library, the inbox and discard folders, the database and
the logs. The AcoustID key is in `config.toml`. The only trace elsewhere is the "Start with Windows"
entry in your user's registry, if you ticked it.

### Backing up or moving the library

Copy the library folder and the database file. Pointing the settings at the copies on another PC
continues where you left off, duplicates included.

### Deleting everything

Quit the app, untick Start with Windows, delete the Mynaphone folder, and delete the library and
working folders.

### Telemetry and usage data

No. There is no telemetry, no crash reporting and no update check. The log stays on your disk.

## The project

### Maturity of the project

It works end to end and is in daily use by its author. It has not had a public release yet, and
things that haven't been tested across many PCs, such as other browsers, other players and older
Windows builds, may need fixes. Bug reports are welcome.

### Choice of the GPL

So that improvements to the app come back as source, and because its heaviest dependencies use the
same family of license.

### Contributing, and changes that won't be merged

Yes, through issues and pull requests; the [contributing guide](../CONTRIBUTING.md) explains the
setup. Changes that download audio, bypass copy protection, automate a service's account, or send
data off the user's PC won't be merged.

### Maintainer

Salman Ravoof, who built it for a home with unreliable internet. Issues and pull requests go
through the GitHub repository.
