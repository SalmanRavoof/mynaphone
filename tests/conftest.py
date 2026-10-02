# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Qt must be loaded before the Windows Runtime bindings the recorder uses (winrt); the other way
# round crashes the process. The app itself always loads Qt first, so the tests do the same.
try:
    import PySide6.QtCore  # noqa: F401
except ImportError:
    pass

from mynaphone.config import Config  # noqa: E402


class FakeClock:
    """Controllable replacement for time.monotonic."""

    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    """A config whose folders live under tmp_path."""
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        "[paths]\n"
        f'inbox_dir = "{(tmp_path / "inbox").as_posix()}"\n'
        f'discard_dir = "{(tmp_path / "discard").as_posix()}"\n'
        f'library_dir = "{(tmp_path / "library").as_posix()}"\n'
        f'db_path = "{(tmp_path / "db.sqlite").as_posix()}"\n'
        f'log_dir = "{(tmp_path / "logs").as_posix()}"\n'
        "[capture]\nmode = \"device\"\nbit_depth = 16\n"
        "[rules]\nsources = [\"Spotify.exe\", \"chrome.exe\"]\nmin_duration_seconds = 30\n"
        "[bridge]\nenabled = false\n",
        encoding="utf-8",
    )
    return Config.load(cfg_path)


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    c = FakeClock()
    import mynaphone.capture as cap
    import mynaphone.daemon as d
    monkeypatch.setattr(d.time, "monotonic", c)
    monkeypatch.setattr(cap.time, "monotonic", c)
    return c
