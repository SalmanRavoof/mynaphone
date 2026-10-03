# Legal notice and intended use

This page explains what Mynaphone does and does not do, so that you can decide whether using it is
appropriate for you. It is not legal advice. The maintainer is not a lawyer, and nothing here tells
you what is or is not permitted in your country.

## What Mynaphone does

- It uses Windows' [process loopback capture](https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ne-audioclientactivationparams-audioclient_activation_type)
  to record the sound that one application, for example Spotify or a web browser, sends to your
  speakers, in the same way that a screen recorder or Audacity's "record what you hear" does.
- It keeps only recordings of complete songs, identifies them with an acoustic fingerprint, looks up
  titles and cover art in public databases, fetches lyrics, encodes them to AAC, and files them in a
  folder you choose.
- Everything stays on your computer. Mynaphone has no accounts, no cloud, and no sharing or upload
  features.

## Things it does not do

- It does not download audio files from Spotify, YouTube or any other service.
- It does not decrypt, descramble, remove or bypass DRM or any other technical protection measure. It
  never touches the services' protected streams, caches or internals; it only records the already-
  decoded audio that Windows is sending to your output device.
- It does not log in to any service on your behalf, play content faster than normal speed, or interfere
  with the services' features. Harvest mode uses the same "next track" control you would press yourself.
- It does not include any means to share, publish or distribute recordings.

## Who it is for

Mynaphone is intended for a single person making private copies, on their own device, of music they
already have access to, for their own listening, for example to keep listening when the internet is
unavailable. Any other use, including sharing, uploading, selling, broadcasting or public performance
of recordings, is outside the intended use and is not supported.

## Your responsibilities

Copyright law differs by country. Many countries have a private-copying or fair-dealing exception,
for example section 52(1)(a) of [India's Copyright Act, 1957](https://www.indiacode.nic.in/bitstream/123456789/1367/1/a195714.pdf),
the private-copying exception in Article 5(2)(b) of [EU Directive 2001/29/EC](https://eur-lex.europa.eu/eli/dir/2001/29/oj),
or fair use under [17 U.S.C. § 107](https://www.law.cornell.edu/uscode/text/17/107) in the United States.

Many countries also prohibit circumventing technical protection measures, for example section 65A of
India's Act, Article 6 of the EU Directive, and [17 U.S.C. § 1201](https://www.law.cornell.edu/uscode/text/17/1201). How these rules apply to recording
a stream you are playing is for you to check. If in doubt, ask a lawyer in your jurisdiction.

The terms of service of streaming platforms may forbid recording, "ripping" or otherwise copying
their content. [Spotify's User Guidelines](https://www.spotify.com/us/legal/user-guidelines/) and
[YouTube's Terms of Service](https://www.youtube.com/t/terms) both contain such clauses.
Using Mynaphone with a service may breach your agreement with that service, and the service may act
on it, including suspending your account. You made that agreement with the service, and this
project is no party to it.

You are solely responsible for what you record and what you do with it.

## No affiliation; trademarks

This is an independent, open-source project. It is not affiliated with, sponsored by, endorsed
by or in any way officially connected with Spotify AB, Google LLC or YouTube, the MetaBrainz
Foundation (MusicBrainz), AcoustID OÜ, LRCLIB, Apple Inc., Last.fm Ltd, or any other service mentioned
in this documentation.
Product and service names are the trademarks of their respective owners and are used only to identify
the services the app can work with. No logos of those services are used.

## Name and logo

The Mynaphone name, the myna mark and the wordmark belong to Salman Ravoof. All rights are reserved:
they aren't covered by the GPL that applies to the code or by the CC BY 4.0 license that applies to
this documentation, and they may not be copied, modified or reused. That covers the files in
`mynaphone/gui/assets/mark/`, the icons in `browser-extension/` and the wordmark images in
`docs/images/`.

You may fork and distribute the code under the GPL. A version you distribute needs its own name and
logo, so nobody mistakes it for this project.

## Data sources and their terms

- **MusicBrainz.** Core data is released under CC0; some supplementary data is CC BY-NC-SA 3.0, as
  the [MusicBrainz data license](https://musicbrainz.org/doc/About/Data_License) explains. Mynaphone
  identifies itself to the MusicBrainz API with a proper User-Agent and stays within the
  [one-request-per-second limit](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting).
- **AcoustID.** [Free for non-commercial use](https://acoustid.org/webservice). Each user registers
  their own application key, and no key comes with the app. Mynaphone stays within 3 requests per second.
- **LRCLIB.** An [open API without keys](https://lrclib.net/docs). Mynaphone identifies itself with a User-Agent.
- **Cover Art Archive.** Images are fetched by MusicBrainz release id through the
  [Cover Art Archive API](https://musicbrainz.org/doc/Cover_Art_Archive/API).
- **Apple's iTunes Search API.** An [open API without keys](https://performance-partners.apple.com/search-api). The app reads only a song's genre name
  from it and uses none of Apple's previews or artwork. Apple limits the API to about 20 requests a
  minute, so the app waits at least 3 seconds between them.
- **YouTube Music and YouTube.** For YouTube captures, the app searches YouTube Music's catalog
  through the unofficial [ytmusicapi](https://github.com/sigma67/ytmusicapi) library without signing
  in, and reads a video's public watch page when the browser extension didn't send its description.
- **Last.fm.** Used only when you add your own free API key, to read a song's tags, under the
  [Last.fm API terms](https://www.last.fm/api/tos). No key comes
  with the app, and nothing is scrobbled or posted to your account.

## Warranty

Mynaphone is free software under the GNU General Public License, version 3 or later, and comes
"as is", without warranty of any kind, express or implied, as sections 15 and 16 of the
[license text](../LICENSE) state. The maintainers accept no responsibility for how you use it.

## Reporting concerns

If you are a rights holder or service operator with a concern about this project,
[open an issue](https://github.com/SalmanRavoof/mynaphone/issues) or contact the maintainer through
[salmanravoof.com](https://salmanravoof.com).
