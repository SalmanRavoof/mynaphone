# Third-party notices

Mynaphone is licensed under the GNU General Public License v3.0 or later (see [`LICENSE`](LICENSE)). A working
installation contains code from other projects under their own licenses, all compatible with the
GPL, listed below. The `setup-tools` command downloads the binary
components into the `tools` folder; the Python packages are installed by pip into `.venv`. Each
package carries its full license text in its distribution; the texts of the GPL, LGPL, MIT and BSD
licenses are also available through the links given.

| Component | License (SPDX) | Role | Source |
|---|---|---|---|
| [FFmpeg](https://ffmpeg.org) (gyan.dev "essentials" build) | GPL-3.0-only (static build with GPL components) | Invoked as a separate process to encode AAC. FFmpeg is a trademark of Fabrice Bellard, originator of the FFmpeg project. | [gyan.dev builds](https://www.gyan.dev/ffmpeg/builds/) (sources linked per build), [FFmpeg legal notes](https://ffmpeg.org/legal.html) |
| [Chromaprint](https://acoustid.org/chromaprint) / fpcalc 1.5.1 | LGPL-2.1-or-later (project asks that the whole be treated as LGPL because it includes FFmpeg components) | Invoked as a separate process to compute acoustic fingerprints. | [acoustid/chromaprint](https://github.com/acoustid/chromaprint) |
| [Qt 6](https://www.qt.io/) via [PySide6](https://doc.qt.io/qtforpython-6/) (the PySide6-Essentials wheel) | LGPL-3.0-only (or GPL-2.0/3.0, or commercial) | Desktop window and tray icon. The Qt libraries are shipped as separate, replaceable DLLs inside the PySide6 wheel; you may replace them with your own build of Qt. | [PySide6-Essentials on PyPI](https://pypi.org/project/PySide6-Essentials/), [Qt for Python source](https://code.qt.io/cgit/pyside/pyside-setup.git/), [Qt's LGPL obligations](https://www.qt.io/development/open-source-lgpl-obligations) |
| [mutagen](https://github.com/quodlibet/mutagen) | GPL-2.0-or-later | Imported in-process to read and write audio tags. Compatible with Mynaphone's GPL-3.0-or-later license. | [quodlibet/mutagen](https://github.com/quodlibet/mutagen) |
| [pycaw](https://github.com/AndreMiras/pycaw) | MIT | Reads Windows per-app audio sessions (device mode). | [AndreMiras/pycaw](https://github.com/AndreMiras/pycaw) |
| [comtypes](https://github.com/enthought/comtypes) | MIT | COM access used by pycaw. | [enthought/comtypes](https://github.com/enthought/comtypes) |
| [psutil](https://github.com/giampaolo/psutil) | BSD-3-Clause | Lists removable drives for the USB export and names the app behind each audio session (with pycaw). | [giampaolo/psutil](https://github.com/giampaolo/psutil) |
| [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) ([PortAudio](https://portaudio.com/)) | MIT (PortAudio: MIT-style) | Whole-device loopback capture (device mode). | [s0d3s/PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) |
| [NumPy](https://numpy.org) | BSD-3-Clause | Audio buffers and trimming. | [numpy/numpy](https://github.com/numpy/numpy) |
| [python-soundfile](https://github.com/bastibe/python-soundfile) ([libsndfile](https://libsndfile.github.io/libsndfile/)) | BSD-3-Clause (libsndfile: LGPL-2.1-or-later) | Writes FLAC files. | [bastibe/python-soundfile](https://github.com/bastibe/python-soundfile) |
| [websockets](https://github.com/python-websockets/websockets) | BSD-3-Clause | Local WebSocket server for the bridges. | [python-websockets/websockets](https://github.com/python-websockets/websockets) |
| [ytmusicapi](https://github.com/sigma67/ytmusicapi) | MIT | YouTube Music catalog lookups. | [sigma67/ytmusicapi](https://github.com/sigma67/ytmusicapi) |
| [PyWinRT](https://github.com/pywinrt/pywinrt) (winrt-* packages) | MIT | Windows media-session API access. | [pywinrt/pywinrt](https://github.com/pywinrt/pywinrt) |
| [Spicetify](https://github.com/spicetify/cli) | MIT | Hosts the Spotify bridge extension (installed separately by the user). | [spicetify/cli](https://github.com/spicetify/cli) |

## Data services

- **MusicBrainz** data: core data CC0 1.0; some supplementary data CC BY-NC-SA 3.0, per the [MusicBrainz data license](https://musicbrainz.org/doc/About/Data_License).
- **AcoustID** web service: free for non-commercial use; each user registers their own application key, per the [AcoustID web service terms](https://acoustid.org/webservice).
- **LRCLIB**: open API, documented in the [LRCLIB API docs](https://lrclib.net/docs).
- **Cover Art Archive**: images are served under the terms stated by the [Cover Art Archive](https://coverartarchive.org) for each image.
- **Apple iTunes Search API**: open API, used to read genres, per the [iTunes Search API documentation](https://performance-partners.apple.com/search-api).
- **Last.fm API**: used with the user's own API key, to read tags for genres, under the [Last.fm API terms](https://www.last.fm/api/tos).
- **MusicBrainz genre list** (`mynaphone/genres.txt`): CC0 1.0, from the [MusicBrainz genre list](https://musicbrainz.org/genres).
- **YouTube Music catalog**: searched without signing in, through ytmusicapi, for YouTube captures.

## Distributing a bundled build

If you package Mynaphone with the `tools` binaries and the Python environment into a single
download, include this file and `LICENSE`, the full license texts of every component above, and
either the corresponding source code of Mynaphone, FFmpeg, Chromaprint and Qt or a written offer to
provide it, as the GPL and LGPL require. The documentation in `docs/` is licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

The Mynaphone name, the myna mark and the wordmark (`mynaphone/gui/assets/mark/`, the icons in
`browser-extension/` and `docs/images/mynaphone-horizontal*.svg`, `docs/images/banner.png` and `docs/images/social-preview.png`) are not licensed under the GPL or
CC BY 4.0. All rights reserved by Salman Ravoof.
