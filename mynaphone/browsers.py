# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""The browsers Mynaphone records YouTube and YouTube Music from, through its browser extension.

All of them are built on Chromium, so the one extension folder loads in each of them, from the browser's own
extensions page with Developer mode on. Windows names a browser's media session after its program file
(chrome.exe), as it does Spotify's, and per-app capture follows the same file.

The extension can't reliably say which browser it runs in, since several of them send Chrome's user agent, so the
bridge asks Windows which program owns each connection instead.
"""
from __future__ import annotations

import ctypes
import socket
from ctypes import wintypes
from dataclasses import dataclass


@dataclass(frozen=True)
class Browser:
    """A browser the extension runs in, with the name people know it by. `process` is its program file, and Windows
    names its media session after it. `extensions_page` is where you turn on Developer mode and load the extension
    folder."""
    name: str               # the browser as people know it
    process: str            # its program file, which names its media session and which per-app capture follows
    extensions_page: str    # where you switch on Developer mode and load the extension folder


BROWSERS: tuple[Browser, ...] = (
    Browser("Chrome", "chrome.exe", "chrome://extensions"),
    Browser("Edge", "msedge.exe", "edge://extensions"),
    Browser("Brave", "brave.exe", "brave://extensions"),
    Browser("Vivaldi", "vivaldi.exe", "vivaldi://extensions"),
    Browser("Opera", "opera.exe", "opera://extensions"),
)
PROCESSES: list[str] = [b.process for b in BROWSERS]

# A browser's sound is only recorded while the extension says a music video or a YouTube Music track is playing, so
# browsers the extension doesn't run in (Firefox) count too: their videos must never be recorded unchecked.
_BROWSER_WORDS = ("chrome", "msedge", "firefox", "brave", "opera", "vivaldi")


def program(app: str) -> str:
    """The program file a media-session app id or a path names, lowercased: 'C:\\x\\Brave.exe' is 'brave.exe'."""
    return (app or "").replace("/", "\\").rsplit("\\", 1)[-1].lower()


def find(app: str) -> Browser | None:
    """The supported browser an app id, a program file or a path belongs to."""
    p = program(app)
    return next((b for b in BROWSERS if b.process == p), None)


def name_of(app: str) -> str:
    """'Brave' for brave.exe, the program file itself for a browser this list doesn't know."""
    b = find(app)
    return b.name if b else program(app)


def is_browser(app: str) -> bool:
    """True when `app` has chrome, msedge, firefox, brave, opera or vivaldi in it, whatever its case. Firefox counts
    too, so the recorder checks the extension's report before it records Firefox."""
    a = (app or "").lower()
    return any(w in a for w in _BROWSER_WORDS)


def names(processes: list[str] | None = None) -> str:
    """'Chrome, Edge, Brave, Vivaldi, and Opera' for every supported browser, or for the ones in `processes`."""
    wanted = None if processes is None else {program(p) for p in processes}
    return listed([b.name for b in BROWSERS if wanted is None or b.process in wanted])


def listed(items: list[str]) -> str:
    """'A', 'A and B', or 'A, B, and C'."""
    if len(items) < 3:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def with_new_browsers(sources: list[str]) -> list[str]:
    """Sources with the browsers added since the config was written. The YouTube option in Settings writes every
    browser in BROWSERS, and versions before Brave, Vivaldi and Opera wrote chrome.exe and msedge.exe, so a list with
    both of those came from that option. A list that names only some browsers stays as it is."""
    have = {program(s) for s in sources}
    if not {"chrome.exe", "msedge.exe"} <= have:
        return list(sources)
    return list(sources) + [p for p in PROCESSES if p not in have]


# ----------------------------------------------------------------------------- which browser holds a connection

class _TcpRow(ctypes.Structure):
    """MIB_TCPROW_OWNER_PID from tcpmib.h. The ports are in network byte order in the low 16 bits."""
    _fields_ = [("state", wintypes.DWORD), ("local_addr", wintypes.DWORD), ("local_port", wintypes.DWORD),
                ("remote_addr", wintypes.DWORD), ("remote_port", wintypes.DWORD), ("pid", wintypes.DWORD)]


TCP_TABLE_OWNER_PID_CONNECTIONS = 4
ERROR_INSUFFICIENT_BUFFER = 122


def tcp_connections() -> list[tuple[int, int, int]]:
    """(local port, remote port, owning pid) of every IPv4 TCP connection on this PC, from GetExtendedTcpTable."""
    fn = ctypes.WinDLL("iphlpapi").GetExtendedTcpTable
    fn.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL, wintypes.ULONG, ctypes.c_int,
                   wintypes.ULONG)
    fn.restype = wintypes.DWORD
    size = wintypes.DWORD(0)
    for _ in range(4):
        buf = ctypes.create_string_buffer(max(size.value, 4))
        rc = fn(buf, ctypes.byref(size), False, socket.AF_INET, TCP_TABLE_OWNER_PID_CONNECTIONS, 0)
        if rc == 0:
            n = wintypes.DWORD.from_buffer(buf).value
            rows = (_TcpRow * n).from_buffer(buf, ctypes.sizeof(wintypes.DWORD))
            return [(socket.ntohs(r.local_port & 0xFFFF), socket.ntohs(r.remote_port & 0xFFFF), int(r.pid))
                    for r in rows]
        if rc != ERROR_INSUFFICIENT_BUFFER:     # the table grows between calls; try again at the size it asked for
            raise ctypes.WinError(rc)
    return []


def program_on_port(client_port: int, server_port: int, connections: list[tuple[int, int, int]] | None = None,
                    table: list[tuple[int, int, str]] | None = None) -> str:
    """The program file, lowercased, of the process that connected from client_port to server_port on this PC, or ''
    when Windows doesn't list that connection. A browser's connections belong to its network process, which runs the
    browser's own program file."""
    from .capture import process_table
    conns = connections if connections is not None else tcp_connections()
    pid = next((p for local, remote, p in conns if local == client_port and remote == server_port), None)
    if pid is None:
        return ""
    return next((exe.lower() for p, _, exe in (table if table is not None else process_table()) if p == pid), "")
