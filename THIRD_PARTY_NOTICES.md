# Third-party notices

Mynaphone is licensed under the GNU General Public License v3.0 or later (see `LICENSE`). A working
installation contains code from other projects under their own licenses, all compatible with the
GPL, listed below. The `setup-tools` command downloads the binary
components into the `tools` folder; the Python packages are installed by pip into `.venv`. Each
package carries its full license text in its distribution; the texts of the GPL, LGPL, MIT and BSD
licenses are also available at the URLs given.

| Component | License (SPDX) | Role | Source |
|---|---|---|---|
| FFmpeg (gyan.dev "essentials" build) | GPL-3.0-only (static build with GPL components) | Invoked as a separate process to encode AAC. FFmpeg is a trademark of Fabrice Bellard, originator of the FFmpeg project. | https://www.gyan.dev/ffmpeg/builds/ (sources linked per build), https://ffmpeg.org/legal.html |
| Chromaprint / fpcalc 1.5.1 | LGPL-2.1-or-later (project asks that the whole be treated as LGPL because it includes FFmpeg components) | Invoked as a separate process to compute acoustic fingerprints. | https://github.com/acoustid/chromaprint |
| Qt 6 via PySide6 | LGPL-3.0-only (or GPL-2.0/3.0, or commercial) | Desktop window and tray icon. The Qt libraries are shipped as separate, replaceable DLLs inside the PySide6 wheel; you may replace them with your own build of Qt. | https://pypi.org/project/PySide6/, https://www.qt.io/licensing/open-source-lgpl-obligations |
| mutagen | GPL-2.0-or-later | Imported in-process to read and write audio tags. Compatible with Mynaphone's GPL-3.0-or-later license. | https://github.com/quodlibet/mutagen |
| pycaw | MIT | Reads Windows per-app audio sessions (device mode). | https://github.com/AndreMiras/pycaw |
| comtypes | MIT | COM access used by pycaw. | https://github.com/enthought/comtypes |
| psutil | BSD-3-Clause | Lists removable drives for the USB export and names the app behind each audio session (with pycaw). | https://github.com/giampaolo/psutil |
| PyAudioWPatch (PortAudio) | MIT (PortAudio: MIT-style) | Whole-device loopback capture (device mode). | https://github.com/s0d3s/PyAudioWPatch |
| numpy | BSD-3-Clause | Audio buffers and trimming. | https://numpy.org |
| python-soundfile (libsndfile) | BSD-3-Clause (libsndfile: LGPL-2.1-or-later) | Writes FLAC files. | https://github.com/bastibe/python-soundfile |
| websockets | BSD-3-Clause | Local WebSocket server for the bridges. | https://github.com/python-websockets/websockets |
| ytmusicapi | MIT | YouTube Music catalog lookups. | https://github.com/sigma67/ytmusicapi |
| PyWinRT (winrt-* packages) | MIT | Windows media-session API access. | https://github.com/pywinrt/pywinrt |
| Spicetify | MIT | Hosts the Spotify bridge extension (installed separately by the user). | https://github.com/spicetify/cli |

## Data services

- **MusicBrainz** data: core data CC0 1.0; some supplementary data CC BY-NC-SA 3.0. https://musicbrainz.org/doc/About/Data_License
- **AcoustID** web service: free for non-commercial use; each user registers their own application key. https://acoustid.org/webservice
- **LRCLIB**: open API. https://lrclib.net
- **Cover Art Archive**: images are served under the terms stated by the archive for each image. https://coverartarchive.org
- **Apple iTunes Search API**: open API, used to read genres. https://performance-partners.apple.com/search-api
- **Last.fm API**: used with the user's own API key, to read tags for genres. https://www.last.fm/api/tos
- **MusicBrainz genre list** (`mynaphone/genres.txt`): CC0 1.0, from https://musicbrainz.org/genres

## Distributing a bundled build

If you package Mynaphone with the `tools` binaries and the Python environment into a single
download, include this file and `LICENSE`, the full license texts of every component above, and
either the corresponding source code of Mynaphone, FFmpeg, Chromaprint and Qt or a written offer to
provide it, as the GPL and LGPL require. The documentation in `docs/` is licensed CC BY 4.0.

The Mynaphone name, the myna mark and the wordmark (`mynaphone/gui/assets/mark/`, the icons in
`browser-extension/` and `docs/images/mynaphone-horizontal*.svg`) are not licensed under the GPL or
CC BY 4.0. All rights reserved by Salman Ravoof.
