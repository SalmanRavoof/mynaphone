# Install Mynaphone

This page takes you from nothing to a running recorder. Allow 15 minutes, more on a slow connection
because of the ffmpeg download of about 115 MB.

## Before you start

Check that you have:

- Windows 10 version 2004 or later, or Windows 11. To check, press **Win + R**, type `winver` and
  press Enter. Version 2004 is build 19041.
- The Spotify desktop app, or Chrome or Edge for YouTube Music. The Microsoft Store edition of
  Spotify works for recording but can't take the Spotify bridge.
- A few gigabytes of free disk space on the drive where you want the library.

## Step 1: Python

1. Download Python 3.11 or later from the [Python downloads page](https://www.python.org/downloads/).
2. Run the installer. On the first screen, tick **Add python.exe to PATH**, then select **Install Now**.
3. To confirm, open PowerShell and run `python --version`. It should print 3.11 or higher.

## Step 2: The code

Either select **Code** > **Download ZIP** on the GitHub page and unzip it, or run:

```powershell
git clone https://github.com/<your-account>/mynaphone.git
```

Put the folder somewhere permanent, for example `D:\Mynaphone`. The app runs from this folder.

## Step 3: The Python environment and the tools

Open PowerShell in the folder (in File Explorer, type `powershell` in the address bar) and run these
commands one at a time:

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e .
.\.venv\Scripts\python -m mynaphone setup-tools
```

The first creates a private Python environment in a `.venv` folder, so nothing else on your PC is
touched. The second installs Mynaphone and its Python dependencies into it. The third downloads
ffmpeg for encoding and Chromaprint for fingerprinting into the `tools` folder, and builds the
per-app capture helper with the C# compiler that is part of Windows.

If the third command reports that the compiler was not found, the app still works but records the
whole output device instead of one app. The [troubleshooting guide](troubleshooting.md) covers that.

Nothing is installed system-wide and no administrator prompt should appear.

## The in-app Set up page

From here on you can do everything inside the app instead of in PowerShell. Start it once:

```powershell
.\.venv\Scripts\python -m mynaphone gui
```

On first run it opens on the **Set up** page, with a card for each remaining step. The cards cover
downloading the tools if you skipped the command above, the AcoustID key, the library folder with a
live estimate of how many songs fit on that drive, and the Spotify and browser bridges. Each card
shows Done when finished, and the page stays in the sidebar afterwards. The sections below describe
the same steps for those who prefer to do them by hand.

## Step 4: An AcoustID application key

Mynaphone identifies songs by comparing an acoustic fingerprint against the AcoustID database.
AcoustID asks every application to register, which costs nothing and takes a minute.

1. Create an account on the [AcoustID login page](https://acoustid.org/login).
2. Open your [AcoustID applications list](https://acoustid.org/my-applications) and select **Register a new application**.
3. Enter a name (for example `Mynaphone`), a version (`0.1`) and submit.
4. Copy the **Application API key** shown on the next page.

Your profile page also shows a "user API key". That one is for submitting fingerprints and the app doesn't need it.

Optionally, add a Last.fm API key as well. Genres come from Apple's catalog and MusicBrainz, and
Last.fm's tags fill in the songs both lack. Log in at Last.fm, open
[Create API account](https://www.last.fm/api/account/create), give it any name, and copy the
**API key**. The shared secret isn't needed. Paste it on the Set up page, or on the
`lastfm_api_key` line in step 5.

## Step 5: Your settings file

1. In the Mynaphone folder, copy `config.example.toml` and name the copy `config.toml`.
2. Open `config.toml` in Notepad.
3. Find the `[identify]` section and paste the key between the quotes on the `acoustid_key` line.
4. If you want the music somewhere other than `D:\Music\Library`, change the folders in the
   `[paths]` section. Everything else can be changed later from the app.
5. Save the file.

`.gitignore` lists `config.toml`, so the key never ends up in a fork you push.

## Step 6: First start

```powershell
.\.venv\Scripts\python -m mynaphone gui
```

The window opens and starts listening at once. Go to **Setup check** and select **Run checks**.
Each line shows OK, Info, Check or Problem with an explanation. Fix any Problem before recording.

To make Mynaphone start with Windows, open **Settings**, tick **Start with Windows** and select
**Save settings**. This adds an entry to your user's startup list and nothing system-wide.

## Step 7, recommended: The Spotify bridge

The bridge is a small extension for [the Spicetify tool](https://spicetify.app), which customizes
the Spotify desktop app. With it, Mynaphone gets the exact track id, the quality tier the song played at,
Spotify's own synced lyrics, and buffering and seek information. Without it, Mynaphone still records
from Spotify using the information Windows provides, but some metadata and many lyrics will be missing.

1. Set up Spicetify following its [getting-started guide](https://spicetify.app/docs/getting-started).
2. In the Mynaphone folder, run:

   ```powershell
   .\.venv\Scripts\python -m mynaphone install-spicetify --apply
   ```

   Spotify restarts once. While the recorder runs, the Status page then reads "Spotify bridge connected".

Each Spotify update undoes Spicetify, and `spicetify apply` puts it back. The Setup check page tells
you when the bridge is installed but not connected.

## Step 8, optional: The browser extension for YouTube

1. In Mynaphone's **Settings**, tick **Also record YouTube and YouTube Music playing in Chrome or
   Edge**, then select **Save settings**.
2. In Chrome, open `chrome://extensions` (in Edge, `edge://extensions`).
3. Switch on **Developer mode**.
4. Select **Load unpacked** and choose the `browser-extension` folder inside the Mynaphone folder.

The extension runs only on youtube.com and music.youtube.com and talks only to Mynaphone on your own
PC. Chrome shows a reminder about developer-mode extensions on each start, which is normal for an
extension that didn't come from the store.

## Updating

1. Stop Mynaphone through the tray icon's **Quit**.
2. Replace the folder's contents with the new version, or run `git pull`.
3. Run `.\.venv\Scripts\pip install -e .` again in case dependencies changed.
4. If the release notes mention the capture helper or the tools, run `.\.venv\Scripts\python -m mynaphone setup-tools --force`.
5. Start the app again.

Updates don't touch your `config.toml`, your library or the database.

## Uninstalling

1. Quit Mynaphone.
2. In **Settings**, untick **Start with Windows** and save, or delete the `Mynaphone` value under
   `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run` with Registry Editor.
3. Remove the extension from `chrome://extensions`. To remove the Spotify bridge too, run `spicetify
   config extensions mynaphone.js-` followed by `spicetify apply`.
4. Delete the Mynaphone folder.
5. Your music library and the working folder, `D:\Music\mynaphone` by default, are yours to keep or delete.
