# Legal notice and intended use

This page explains what Mynaphone does and does not do, so that you can decide whether using it is
appropriate for you. It is not legal advice. The maintainer is not a lawyer, and nothing here tells
you what is or is not permitted in your country.

## What Mynaphone does

- It uses the Windows audio loopback API to capture the sound that one application (for example
  Spotify or a web browser) sends to your speakers, in the same way that a screen recorder or
  Audacity's "record what you hear" does.
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
for example section 52(1)(a) of India's Copyright Act, 1957, the private-copying exception in Article
5(2)(b) of EU Directive 2001/29/EC, or fair use under 17 U.S.C. § 107 in the United States.

Many countries also prohibit circumventing technical protection measures, for example section 65A of
India's Act, Article 6 of the EU Directive, and 17 U.S.C. § 1201. How these rules apply to recording
a stream you are playing is for you to check. If in doubt, ask a lawyer in your jurisdiction.

The terms of service of streaming platforms may forbid recording, "ripping" or otherwise copying
their content. Spotify's User Guidelines and YouTube's Terms of Service both contain such clauses.
Using Mynaphone with a service may breach your agreement with that service, and the service may act
on it, including suspending your account. You made that agreement with the service, and this
project is no party to it.

You are solely responsible for what you record and what you do with it.

## No affiliation; trademarks

This is an independent, open-source project. It is not affiliated with, sponsored by, endorsed
by or in any way officially connected with Spotify AB, Google LLC or YouTube, the MetaBrainz
Foundation (MusicBrainz), AcoustID OÜ, LRCLIB, or any other service mentioned in this documentation.
Product and service names are the trademarks of their respective owners and are used only to identify
the services the app can work with. No logos of those services are used.

## Data sources and their terms

- **MusicBrainz.** Core data is released under CC0; some supplementary data is CC BY-NC-SA 3.0.
  Mynaphone identifies itself to the MusicBrainz API with a proper User-Agent and stays within the
  one-request-per-second limit.
- **AcoustID.** Free for non-commercial use. Each user registers their own application key, and no
  key comes with the app. Mynaphone stays within 3 requests per second.
- **LRCLIB.** An open API without keys. Mynaphone identifies itself with a User-Agent.
- **Cover Art Archive.** Images are fetched by MusicBrainz release id.

## Warranty

Mynaphone is free software under the GNU General Public License, version 3 or later, and comes
"as is", without warranty of any kind, express or implied, as sections 15 and 16 of the
[license text](../LICENSE) state. The maintainers accept no responsibility for how you use it.

## Reporting concerns

If you are a rights holder or service operator with a concern about this project, open an issue in
the repository or contact the maintainer at the address given there.
