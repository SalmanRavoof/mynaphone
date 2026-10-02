# Contributing

Thanks for taking an interest. Mynaphone is a small project with one maintainer, so clear reports
and focused changes are the most helpful things.

Everyone who takes part in the issues and pull requests agrees to the
[code of conduct](CODE_OF_CONDUCT.md).

## Reporting a bug

Open a GitHub issue with the bug report template. It asks for:

- Your Windows version (`winver`) and whether the Spotify bridge or browser extension was connected.
- What you did, what you expected, what happened.
- The relevant lines from the log (`D:\Music\mynaphone\logs\mynaphone.log` by default). Remove file
  names or titles you'd rather not share.
- For a wrongly kept or discarded take, the `.json` file next to it in the inbox or discard folder.

## Suggesting a change

For anything beyond a small fix, start with an issue so the approach can be agreed before you spend
time on it.

## What will not be merged

- Anything that downloads audio from a service, decrypts or bypasses copy protection, or automates a
  service's account or player beyond the ordinary "next track" control.
- Anything that sends audio, library contents or listening data off the user's PC.
- Features that evade a service's detection of misuse.

These boundaries define what the project is, as the [legal notice](docs/legal.md) explains.

## Development setup

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"
.\.venv\Scripts\python -m mynaphone setup-tools
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\ruff check .
```

The `dev` extra adds pytest and Ruff to the app's own dependencies. The tests need neither Spotify
nor an internet connection. 3 of them encode a short file with ffmpeg
and are skipped when ffmpeg is absent. The window tests in `tests/test_gui.py` run Qt offscreen and
start no recorder. Qt is loaded in `conftest.py` before anything else because the Windows Runtime
bindings the recorder uses crash the process when they load first.

Layout:

- `mynaphone/` the app: `daemon.py` (recorder state machine), `capture.py` (audio engines),
  `smtc.py` (Windows media sessions), `bridge.py` (extension WebSocket), `takes.py` (verdict and
  files), `postprocess.py`, `identify.py`, `musicbrainz.py`, `lyrics.py`, `library.py`,
  `metadata.py`, `export.py`, `store.py`, `config.py`, `gui/`.
- `helper/` the C# per-app capture helper.
- `spicetify/` and `browser-extension/` the 2 bridges.
- `tests/` pytest suite.
- `docs/` user documentation.
- `.github/` the test workflow and the issue and pull request templates.

## Code style

- Python 3.11+, type hints on public functions, 4-space indents, 120-column lines.
- Ruff checks line length, unused imports and import order with the settings in `pyproject.toml`.
  `ruff check --fix .` sorts the imports for you.
- `.editorconfig` sets UTF-8, LF line endings and the indent size for each file type, for editors
  that read it.
- Keep user-facing text in plain language; see the docs for tone.
- No new runtime dependencies without discussion; every one adds to the license notices.
- Add or update a test for behavior changes in the verdict rules, placement or identification.

## Licensing of contributions

Mynaphone is GPL-3.0-or-later. By submitting a change you agree that it is released under the same
license. New source files start with the same 2 header lines as the existing ones (copyright and
`SPDX-License-Identifier: GPL-3.0-or-later`).

## Pull requests

- One change per pull request, with a short description of what and why.
- Run the tests and Ruff before pushing. GitHub Actions runs both on every pull request, the tests
  on Windows with Python 3.11 and 3.13.
- Update the documentation and `CHANGELOG.md` (under Unreleased) when behavior or settings change.
- Do not add attribution lines for tools used to write the code.

## Making a release

1. Set the new version in `mynaphone/__init__.py`. The package metadata reads it from there.
2. Type the same version into `browser-extension/manifest.json`. Chrome reads the extension's
   version from that file alone, so it can't share the one in the package.
3. In `CHANGELOG.md`, give the Unreleased section the version number and the date. Then start a new
   empty Unreleased section above it.
4. Commit the changes and tag that commit `vX.Y.Z`. Then push the commit and the tag.
