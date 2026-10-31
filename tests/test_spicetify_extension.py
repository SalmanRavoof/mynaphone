# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Spotify bridge extension: run in Node against stand-ins for Spicetify and Spotify's player, and what the app
logs about the state it sends."""
import asyncio
import json
import logging
import shutil
import socket
import subprocess
from pathlib import Path

import pytest
import websockets

from mynaphone.bridge import Bridge

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_the_extension_in_node():
    """On October 30, 2026 Spicetify's copy of the player stayed empty while a song played, and the extension
    sent nothing for 40 minutes."""
    out = subprocess.run(["node", str(ROOT / "tests" / "js" / "extension_harness.mjs"),
                          str(ROOT / "spicetify" / "mynaphone.js")], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr


def test_the_log_says_when_spicetifys_copy_is_empty(caplog):
    async def scenario():
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        bridge = Bridge(asyncio.get_running_loop(), asyncio.Queue(), port)
        await bridge.start()
        async with websockets.connect(f"ws://127.0.0.1:{port}/spotify") as ext:
            for empty in (True, True, False):
                await ext.send(json.dumps({"type": "state", "uri": "spotify:track:k",
                                           "name": "Kabhi Khushi Kabhie Gham", "spicetifyEmpty": empty}))
            await asyncio.sleep(0.1)
            assert bridge.state.uri == "spotify:track:k"
        await bridge.stop()

    with caplog.at_level(logging.INFO, logger="mynaphone"):
        asyncio.run(scenario())
    said = [r.getMessage() for r in caplog.records if r.name == "mynaphone.bridge"
            and r.getMessage().startswith(("first state", "Spicetify's copy"))]
    assert said == ["first state from Spotify: Kabhi Khushi Kabhie Gham (quality no, track details pending)",
                         "Spicetify's copy of the player is empty, so the bridge reads Spotify's own player",
                         "Spicetify's copy of the player has the song again"]
