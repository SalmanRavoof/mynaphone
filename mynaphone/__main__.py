# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import Config

HERE = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = HERE / "config.toml"


def setup_logging(log_dir: Path, verbose: bool) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)
    fh = logging.handlers.RotatingFileHandler(log_dir / "mynaphone.log", maxBytes=5_000_000, backupCount=5,
                                              encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(fh)
    logging.getLogger("websockets").setLevel(logging.WARNING)


def cmd_run(args) -> int:
    cfg = Config.load(args.config)
    setup_logging(cfg.paths.log_dir, args.verbose)
    from .daemon import Recorder
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    rec = Recorder(cfg)
    try:
        loop.run_until_complete(rec.run())
    except KeyboardInterrupt:
        logging.getLogger("mynaphone").info("stopping")
    return 0


def cmd_status(args) -> int:
    cfg = Config.load(args.config)
    from .store import Store, local_time
    st = Store(cfg.paths.db_path)
    s = st.summary()
    print(f"inbox: {s['tracks_inbox']}  library: {s['tracks_library']}  "
          f"takes kept/discarded/skipped: {s['takes_kept']}/{s['takes_discarded']}/{s['takes_skipped']}")
    print("recent takes:")
    for r in st.recent_takes(args.n):
        exp = (r["expected_ms"] or 0) / 1000
        cap = (r["captured_ms"] or 0) / 1000
        when = local_time(r["started_at"], "%Y-%m-%d %H:%M:%S")
        print(f"  {when}  {r['verdict']:<8} {r['artist']} - {r['title']}  "
              f"({cap:.1f}s/{exp:.1f}s) {r['quality_tier'] or ''} {r['reasons'] or ''}")
    return 0


def cmd_devices(args) -> int:
    from .capture import list_devices
    for line in list_devices():
        print(line)
    return 0


def cmd_install_spicetify(args) -> int:
    src = HERE / "spicetify" / "mynaphone.js"
    ext_dir = Path(os.environ["APPDATA"]) / "spicetify" / "Extensions"
    ext_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, ext_dir / "mynaphone.js")
    print(f"copied {src.name} -> {ext_dir}")
    if args.apply:
        subprocess.run(["spicetify", "config", "extensions", "mynaphone.js"], check=False)
        subprocess.run(["spicetify", "apply"], check=False)
    else:
        print("now run:  spicetify config extensions mynaphone.js  &&  spicetify apply")
    return 0


def cmd_refresh(args) -> int:
    """Look up every library song again, re-tag it and recompute what is still missing. Manual edits are kept."""
    from .metadata import LABELS, refresh_track
    from .store import Store
    cfg = Config.load(args.config)
    setup_logging(cfg.paths.log_dir, args.verbose)
    st = Store(cfg.paths.db_path)
    rows = st.library_rows(only_incomplete=args.incomplete)
    for r in rows:
        try:
            res = refresh_track(cfg, st, r, lookup=True, move=not args.no_move)
            miss = ", ".join(LABELS.get(m, m) for m in res["missing"]) or "complete"
            print(f"{Path(res['path']).name}: {miss}" + (f"  ({res['note']})" if res["note"] else ""))
        except Exception as e:
            print(f"{r['title']}: failed: {e}")
    return 0


FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
CHROMAPRINT_URL = "https://github.com/acoustid/chromaprint/releases/download/v1.5.1/chromaprint-fpcalc-1.5.1-windows-x86_64.zip"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"


def cmd_setup_tools(args) -> int:
    """Download ffmpeg and Chromaprint into tools/ and build the per-app capture helper."""
    import shutil
    import urllib.request
    import zipfile

    from .tools import TOOLS
    TOOLS.mkdir(parents=True, exist_ok=True)
    dl = TOOLS / "dl"
    dl.mkdir(exist_ok=True)

    def fetch(url: str, name: str) -> Path:
        dst = dl / name
        if dst.exists() and not args.force:
            print(f"already downloaded: {name}")
            return dst
        print(f"downloading {url}")
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "mynaphone/0.1"}),
                                    timeout=60) as r, open(dst, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total:
                    print(f"  {got / 1e6:6.1f} / {total / 1e6:.1f} MB", end="\r")
        print()
        return dst

    if not (TOOLS / "ffmpeg" / "bin" / "ffmpeg.exe").exists() or args.force:
        z = fetch(FFMPEG_URL, "ffmpeg.zip")
        with zipfile.ZipFile(z) as zf:
            root = zf.namelist()[0].split("/")[0]
            zf.extractall(dl)
        shutil.rmtree(TOOLS / "ffmpeg", ignore_errors=True)
        shutil.move(str(dl / root), str(TOOLS / "ffmpeg"))
    print("ffmpeg:", TOOLS / "ffmpeg" / "bin" / "ffmpeg.exe")

    if not (TOOLS / "chromaprint" / "fpcalc.exe").exists() or args.force:
        z = fetch(CHROMAPRINT_URL, "chromaprint.zip")
        with zipfile.ZipFile(z) as zf:
            root = zf.namelist()[0].split("/")[0]
            zf.extractall(dl)
        shutil.rmtree(TOOLS / "chromaprint", ignore_errors=True)
        shutil.move(str(dl / root), str(TOOLS / "chromaprint"))
    print("fpcalc:", TOOLS / "chromaprint" / "fpcalc.exe")

    helper = TOOLS / "mynaphone-capture.exe"
    src = HERE / "helper" / "ProcessLoopback.cs"
    if (not helper.exists() or args.force) and src.exists():
        if not CSC.exists():
            print(f"C# compiler not found at {CSC}; per-app capture will fall back to whole-device capture")
        else:
            print("building the per-app capture helper")
            r = subprocess.run([str(CSC), "/nologo", "/target:exe", "/platform:x64", "/optimize+",
                                f"/out:{helper}", str(src)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                print(r.stdout, r.stderr)
                return 1
    print("capture helper:", helper if helper.exists() else "not built")
    shutil.rmtree(dl, ignore_errors=True)
    print("done")
    return 0


def cmd_export(args) -> int:
    from . import export
    cfg = Config.load(args.config)
    dest = Path(args.dest)
    p = export.plan(cfg.paths.library_dir, dest, include_lyrics=args.lyrics, mirror=args.mirror)
    print(f"{len(p.copy)} to copy ({p.bytes_to_copy/1e9:.2f} GB), {p.skip} up to date, {len(p.remove)} to remove")
    if args.dry_run:
        return 0
    c, r = export.run(p, progress=lambda d, t, n: print(f"  {d}/{t} {n}"))
    print(f"copied {c}, removed {r}")
    return 0


def cmd_gui(args) -> int:
    cfg = Config.load(args.config)
    setup_logging(cfg.paths.log_dir, args.verbose)
    from .gui.app import run_gui
    return run_gui(Path(args.config).resolve(), minimized=args.minimized)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="mynaphone", description="always-on loopback song archiver")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="run the recorder").set_defaults(fn=cmd_run)
    s = sub.add_parser("status", help="show archive counts and recent takes")
    s.add_argument("-n", type=int, default=15)
    s.set_defaults(fn=cmd_status)
    sub.add_parser("devices", help="list capture devices").set_defaults(fn=cmd_devices)
    s = sub.add_parser("refresh", help="look up library songs again, re-tag them and list what is still missing")
    s.add_argument("--incomplete", action="store_true", help="only songs with missing metadata")
    s.add_argument("--no-move", action="store_true", help="never move files even if the folder name changed")
    s.set_defaults(fn=cmd_refresh)
    s = sub.add_parser("setup-tools", help="download ffmpeg and Chromaprint, build the capture helper")
    s.add_argument("--force", action="store_true", help="re-download and rebuild even if present")
    s.set_defaults(fn=cmd_setup_tools)
    s = sub.add_parser("export", help="copy the library to a USB drive or folder")
    s.add_argument("dest")
    s.add_argument("--lyrics", action="store_true", help="also copy .lrc lyrics files")
    s.add_argument("--mirror", action="store_true", help="remove files on the destination that are not in the library")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_export)
    s = sub.add_parser("gui", help="open the desktop window (tray app)")
    s.add_argument("--minimized", action="store_true", help="start hidden in the tray")
    s.set_defaults(fn=cmd_gui)
    s = sub.add_parser("install-spicetify", help="install the Spicetify bridge extension")
    s.add_argument("--apply", action="store_true", help="also run spicetify config + apply (restarts Spotify)")
    s.set_defaults(fn=cmd_install_spicetify)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
