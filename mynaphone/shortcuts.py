# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""Ways to open the app: its Start menu and desktop shortcuts, the Start with Windows command, and the
taskbar identity they share.

Windows groups taskbar buttons by AppUserModelID. The app gives itself one at start-up and its shortcuts
carry the same one, so a pinned shortcut and the running window share one button, and pinning the running
window pins the Start menu shortcut instead of a bare pythonw.exe that opens nothing.
"""
from __future__ import annotations

import ctypes
import functools
import sys
import uuid
from ctypes import wintypes
from pathlib import Path

APP_ID = "Mynaphone"        # up to 128 characters and no spaces; the name alone is unique enough
LINK_NAME = "Mynaphone.lnk"
DESCRIPTION = "Keeps a private copy of the songs you play, for listening offline"
ICON = Path(__file__).resolve().parent / "gui" / "assets" / "mark" / "ico" / "mynaphone-stopped.ico"
PLACES = {
    "start_menu": "A77F5D77-2E2B-44C3-A6A2-ABA601054A51",     # FOLDERID_Programs
    "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",        # FOLDERID_Desktop, wherever OneDrive moved it
}


class _Guid(ctypes.Structure):
    _fields_ = [("data1", wintypes.DWORD), ("data2", wintypes.WORD), ("data3", wintypes.WORD),
                ("data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text: str) -> _Guid:
        return cls.from_buffer_copy(uuid.UUID(text).bytes_le)


class _PropertyKey(ctypes.Structure):
    _fields_ = [("fmtid", _Guid), ("pid", wintypes.DWORD)]


class _PropVariant(ctypes.Structure):
    """PROPVARIANT, holding only the string kind this module reads and writes."""
    class _Value(ctypes.Union):
        _fields_ = [("pwszVal", ctypes.c_wchar_p), ("_size", ctypes.c_ubyte * 16)]
    _anonymous_ = ("value",)
    _fields_ = [("vt", wintypes.USHORT), ("reserved1", wintypes.USHORT), ("reserved2", wintypes.USHORT),
                ("reserved3", wintypes.USHORT), ("value", _Value)]


_VT_LPWSTR = 31
_APP_ID_KEY = _PropertyKey(_Guid.parse("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5)     # System.AppUserModel.ID

# on private handles, so these signatures don't leak into other modules' calls
_shell32 = ctypes.WinDLL("shell32")
_shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(_Guid), wintypes.DWORD, wintypes.HANDLE,
                                          ctypes.POINTER(ctypes.c_void_p)]
_shell32.SHGetKnownFolderPath.restype = ctypes.HRESULT
_shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
_shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.HRESULT
_ole32 = ctypes.WinDLL("ole32")
_ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
_ole32.CoTaskMemFree.restype = None
_ole32.PropVariantClear.argtypes = [ctypes.POINTER(_PropVariant)]
_ole32.PropVariantClear.restype = ctypes.HRESULT


# -- the command that opens the app ----------------------------------------------------------

def interpreter() -> Path:
    """pythonw.exe beside the running Python, so the app opens without a console window."""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return pyw if pyw.exists() else exe


def gui_arguments(config_path: Path, minimized: bool = False) -> str:
    args = f'-m mynaphone --config "{config_path}" gui'
    return f"{args} --minimized" if minimized else args


def login_command(config_path: Path) -> str:
    """The Start with Windows entry, which opens the app in the tray."""
    return f'"{interpreter()}" {gui_arguments(config_path, minimized=True)}'


def set_app_id() -> None:
    """Give this process the app's taskbar identity. It has to happen before the first window opens."""
    _shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


# -- shortcuts -------------------------------------------------------------------------------

def shortcut_path(place: str) -> Path:
    """Where the shortcut for a place in PLACES goes."""
    out = ctypes.c_void_p()
    _shell32.SHGetKnownFolderPath(ctypes.byref(_Guid.parse(PLACES[place])), 0, None, ctypes.byref(out))
    try:
        return Path(ctypes.wstring_at(out.value)) / LINK_NAME
    finally:
        _ole32.CoTaskMemFree(out)


def has_shortcut(place: str) -> bool:
    try:
        return shortcut_path(place).exists()
    except OSError:
        return False


def add_shortcut(place: str, config_path: Path) -> Path:
    """Create the shortcut, or point an existing one at this Python and settings file again."""
    path = shortcut_path(place)
    write_link(path, interpreter(), gui_arguments(config_path), config_path.parent, ICON, DESCRIPTION)
    return path


def remove_shortcut(place: str) -> bool:
    try:
        shortcut_path(place).unlink()
        return True
    except FileNotFoundError:
        return False


def write_link(path: Path, target: Path, arguments: str, workdir: Path, icon: Path, description: str) -> None:
    """Save a .lnk that carries the app's AppUserModelID. COM errors come out as OSError."""
    from comtypes import COMError
    from comtypes.persist import IPersistFile
    try:
        link = _new_link()
        link.SetPath(str(target))
        link.SetArguments(arguments)
        link.SetWorkingDirectory(str(workdir))
        link.SetIconLocation(str(icon), 0)
        link.SetDescription(description)
        props = link.QueryInterface(_property_store())
        value = _PropVariant(vt=_VT_LPWSTR)
        value.pwszVal = APP_ID
        props.SetValue(ctypes.byref(_APP_ID_KEY), ctypes.byref(value))
        props.Commit()
        path.parent.mkdir(parents=True, exist_ok=True)
        link.QueryInterface(IPersistFile).Save(str(path), True)
    except COMError as e:
        raise OSError(f"could not write {path}: {e}") from e


def read_link(path: Path) -> dict:
    """What a .lnk opens: target, arguments, working folder, icon, description and AppUserModelID."""
    from comtypes import COMError
    from comtypes.persist import IPersistFile
    try:
        link = _new_link()
        link.QueryInterface(IPersistFile).Load(str(path), 0)
        icon, _index = link.GetIconLocation()
        value = link.QueryInterface(_property_store()).GetValue(ctypes.byref(_APP_ID_KEY))
        try:
            app_id = value.pwszVal if value.vt == _VT_LPWSTR else None
        finally:
            _ole32.PropVariantClear(ctypes.byref(value))
        return {"target": link.GetPath(0), "arguments": link.GetArguments(), "workdir": link.GetWorkingDirectory(),
                "icon": icon, "description": link.GetDescription(), "app_id": app_id}
    except COMError as e:
        raise OSError(f"could not read {path}: {e}") from e


def _new_link():
    from comtypes import CoCreateInstance
    from comtypes.shelllink import IShellLinkW, ShellLink
    return CoCreateInstance(ShellLink._reg_clsid_, interface=IShellLinkW)


@functools.cache
def _property_store():
    """IPropertyStore, which comtypes doesn't ship. Defined on first use, so opening the app loads no COM."""
    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

    class IPropertyStore(IUnknown):
        _iid_ = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
        _methods_ = [
            COMMETHOD([], HRESULT, "GetCount", (["out"], ctypes.POINTER(wintypes.DWORD), "count")),
            COMMETHOD([], HRESULT, "GetAt", (["in"], wintypes.DWORD, "index"),
                      (["out"], ctypes.POINTER(_PropertyKey), "key")),
            COMMETHOD([], HRESULT, "GetValue", (["in"], ctypes.POINTER(_PropertyKey), "key"),
                      (["out"], ctypes.POINTER(_PropVariant), "value")),
            COMMETHOD([], HRESULT, "SetValue", (["in"], ctypes.POINTER(_PropertyKey), "key"),
                      (["in"], ctypes.POINTER(_PropVariant), "value")),
            COMMETHOD([], HRESULT, "Commit"),
        ]
    return IPropertyStore
