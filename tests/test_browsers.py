# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""YouTube in every supported browser: their names, older configs, and telling each browser's extension apart."""
import asyncio
import json
import os
import socket
import time

import psutil
import websockets

from mynaphone import browsers
from mynaphone.bridge import Bridge, YouTubeState
from mynaphone.config import Config
from mynaphone.gui import verify


def test_browsers_are_found_by_program_file():
    assert browsers.program("C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\Brave.exe") == "brave.exe"
    assert browsers.find("vivaldi.exe").name == "Vivaldi"
    assert browsers.find("OPERA.EXE").extensions_page == "opera://extensions"
    assert browsers.find("Spotify.exe") is None and browsers.find("") is None
    assert browsers.name_of("msedge.exe") == "Edge" and browsers.name_of("thorium.exe") == "thorium.exe"
    assert all(browsers.is_browser(p) for p in browsers.PROCESSES)
    assert browsers.is_browser("firefox.exe") and not browsers.is_browser("Spotify.exe")


def test_browser_lists_read_as_a_sentence():
    assert browsers.names() == "Chrome, Edge, Brave, Vivaldi, and Opera"
    assert browsers.names(["Spotify.exe", "brave.exe", "chrome.exe"]) == "Chrome and Brave"
    assert browsers.listed(["Brave"]) == "Brave" and browsers.listed([]) == ""


def test_the_youtube_option_from_an_older_version_covers_the_new_browsers(tmp_path):
    old = ["Spotify.exe", "chrome.exe", "msedge.exe"]
    assert browsers.with_new_browsers(old) == old + ["brave.exe", "vivaldi.exe", "opera.exe"]
    assert browsers.with_new_browsers(["Spotify.exe", "chrome.exe"]) == ["Spotify.exe", "chrome.exe"]   # by hand
    every = ["Spotify.exe", *browsers.PROCESSES]
    assert browsers.with_new_browsers(every) == every
    p = tmp_path / "config.toml"
    p.write_text('[rules]\nsources = ["Spotify.exe", "chrome.exe", "msedge.exe"]\n', encoding="utf-8")
    assert Config.load(p).rules.sources == ["Spotify.exe", *browsers.PROCESSES]


def test_the_program_on_a_port_is_the_one_that_connected():
    conns = [(8765, 50000, 10), (50000, 8765, 4242), (50001, 443, 4242)]
    table = [(10, 1, "pythonw.exe"), (4242, 1, "Brave.exe")]
    assert browsers.program_on_port(50000, 8765, conns, table) == "brave.exe"
    assert browsers.program_on_port(50002, 8765, conns, table) == ""


def test_windows_lists_this_processs_own_connection():
    server = socket.create_server(("127.0.0.1", 0))
    client = socket.create_connection(server.getsockname())
    try:
        mine = (client.getsockname()[1], server.getsockname()[1], os.getpid())
        assert mine in browsers.tcp_connections()
    finally:
        client.close()
        server.close()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_bridge_keeps_each_browsers_report_apart():
    """The extension can't say which browser it runs in, so the bridge asks Windows which program holds the socket.
    Here the browser is this test's own Python, and Brave, which never connected, has nothing to say."""
    me = psutil.Process().name().lower()
    seen = []

    async def main():
        port = _free_port()
        b = Bridge(asyncio.get_running_loop(), asyncio.Queue(), port, on_extension=lambda *a: seen.append(a))
        await b.start()
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}/youtube") as ws:
                await ws.send(json.dumps({"type": "youtube", "event": "play", "videoId": "abc", "isMusic": True,
                                          "paused": False, "duration": 200}))
                for _ in range(200):
                    if b.youtube_for(me).video_id:
                        break
                    await asyncio.sleep(0.01)
                assert b.youtube_connected
            for _ in range(200):
                if len(seen) == 2:
                    break
                await asyncio.sleep(0.01)
        finally:
            await b.stop()
        return b

    b = asyncio.run(main())
    assert b.youtube_for(me).video_id == "abc" and b.youtube_for(me).browser == me
    assert not b.youtube_for("brave.exe").fresh
    assert seen == [(me, True), (me, False)] and not b.youtube_connected


def test_a_report_from_an_untraced_connection_stands_in_for_any_browser():
    b = Bridge(None, asyncio.Queue(), 0)
    now = time.monotonic()
    brave = YouTubeState(video_id="b", received_at=now, browser="brave.exe")
    b.youtube_by_browser["brave.exe"] = brave
    assert b.youtube_for("brave.exe") is brave and not b.youtube_for("chrome.exe").fresh
    untraced = YouTubeState(video_id="u", received_at=now)
    b.youtube_by_browser[""] = untraced
    assert b.youtube_for("chrome.exe") is untraced and b.youtube_for("brave.exe") is brave


def test_setup_check_reports_where_the_extension_connected_from(tmp_config):
    tmp_config.rules.sources = ["Spotify.exe", *browsers.PROCESSES]
    stopped = verify.check_browser_extension(tmp_config, None)
    assert stopped.status == verify.INFO and "Chrome, Edge, Brave, Vivaldi, and Opera" in stopped.detail
    ok = verify.check_browser_extension(tmp_config, ["Brave", "Chrome"])
    assert ok.status == verify.OK and "Brave and Chrome" in ok.detail
    assert verify.check_browser_extension(tmp_config, []).status == verify.WARN
    tmp_config.rules.sources = ["Spotify.exe"]
    off = verify.check_browser_extension(tmp_config, ["Brave"])
    assert off.status == verify.INFO and "off" in off.detail
