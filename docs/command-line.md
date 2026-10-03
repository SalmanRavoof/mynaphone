# Command line

Everything the window does can also be started from PowerShell, in the Mynaphone folder. Every
command has the same form:

```powershell
.\.venv\Scripts\python -m mynaphone [--config PATH] [-v] <command> [options]
```

Installing the package also creates `.venv\Scripts\mynaphone.exe`, so
`.\.venv\Scripts\mynaphone <command>` works the same way.

| Option | What it does |
|---|---|
| `--config PATH` | Use a different settings file. The default is `config.toml` in the Mynaphone folder |
| `-v`, `--verbose` | Log more detail, to the console and the log file |
| `-h`, `--help` | List the commands, or a command's options when given after it |

## Commands

| Command | What it does |
|---|---|
| [`gui`](#gui) | Open the window and the tray icon |
| [`run`](#run) | Run the recorder in the console, without the window |
| [`status`](#status) | Print the archive counts and the latest takes |
| [`devices`](#devices) | List the audio devices that device mode can record |
| [`refresh`](#refresh) | Look up library songs again and re-tag them |
| [`export`](#export) | Copy the library to a USB drive or a folder |
| [`setup-tools`](#setup-tools) | Download ffmpeg and Chromaprint and build the capture helper |
| [`install-spicetify`](#install-spicetify) | Install the Spotify bridge extension |

### gui

```powershell
.\.venv\Scripts\python -m mynaphone gui [--minimized]
```

Opens the window. `--minimized` starts it hidden in the tray, which is how **Start with Windows**
launches it. If Mynaphone is already running, the command brings its window back instead.

### run

```powershell
.\.venv\Scripts\python -m mynaphone run
```

Runs the recorder in the console and prints the log as it goes. Press <kbd>Ctrl</kbd>+<kbd>C</kbd>
to stop. Don't run it while the window is open, since both would record the same songs.

### status

```powershell
.\.venv\Scripts\python -m mynaphone status [-n 15]
```

Prints how many songs are in the inbox and the library and how many takes were kept, discarded
or skipped, then the latest takes with their lengths, tier and reasons. `-n` sets how many takes to list.

### devices

```powershell
.\.venv\Scripts\python -m mynaphone devices
```

Lists the audio devices that can be recorded in device mode. Any part of a name works as the
`device` setting in `config.toml`.

### refresh

```powershell
.\.venv\Scripts\python -m mynaphone refresh [--incomplete] [--no-move]
```

Looks every library song up again, re-tags it, moves it if its folder name changed, and prints what
is still missing. Your manual edits are kept.

| Option | What it does |
|---|---|
| `--incomplete` | Only songs with missing metadata |
| `--no-move` | Never move a file, even if its folder name changed |

### export

```powershell
.\.venv\Scripts\python -m mynaphone export <destination> [--lyrics] [--mirror] [--dry-run]
```

Copies new and changed library files to `<destination>`, a drive such as `E:\` or any folder.

| Option | What it does |
|---|---|
| `--lyrics` | Also copy the `.lrc` lyrics files |
| `--mirror` | Remove files from the destination that are no longer in the library |
| `--dry-run` | Print what would be copied and removed, and write nothing |

### setup-tools

```powershell
.\.venv\Scripts\python -m mynaphone setup-tools [--force]
```

Downloads ffmpeg from the [gyan.dev builds](https://www.gyan.dev/ffmpeg/builds/) and Chromaprint's
`fpcalc` from the [Chromaprint releases](https://github.com/acoustid/chromaprint/releases) into the
`tools` folder, and compiles `helper/ProcessLoopback.cs` into `tools/mynaphone-capture.exe` with the
C# compiler that comes with Windows. `--force` downloads and builds again even when the files are
present.

### install-spicetify

```powershell
.\.venv\Scripts\python -m mynaphone install-spicetify [--apply]
```

Copies `spicetify/mynaphone.js` into `%APPDATA%\spicetify\Extensions`. With `--apply`, it also runs
`spicetify config extensions mynaphone.js` and `spicetify apply`, which restarts Spotify. Without it,
the command prints those 2 commands for you to run.
