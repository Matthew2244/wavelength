"""Updates on Windows through WinSparkle, Sparkle's Windows twin.

Same idea as sparkle.py on the Mac: a daily check, a window with what's new, Install,
Skip, Remind Me Later, and every update signed with the EdDSA key in Matthew's Keychain
(the public half is below). WinSparkle installs by running the new installer, so this is
only used by a copy that was itself installed (it has an uninstaller beside it). A copy
unzipped somewhere keeps using update.py, which swaps the folder in place.

WinSparkle.dll is bundled by build_app.py and driven with ctypes.
"""
from __future__ import annotations

import ctypes
import os
import sys

from . import __version__

APPCAST = "https://github.com/Matthew2244/ytdl-accessible/releases/latest/download/appcast-windows.xml"
PUBLIC_KEY = "TJlHNK3idLU77+cj97Pwh4xeuvFhhIVm32CLFwN5Dz0="

_state = {"dll": None, "callbacks": None, "failed": False}


def app_dir() -> str | None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    return os.path.dirname(os.path.abspath(sys.executable))


def installed() -> bool:
    """True for a copy put there by the installer (it has an uninstaller beside it)."""
    d = app_dir()
    return bool(d) and any(n.lower().startswith("unins") and n.lower().endswith(".exe") for n in os.listdir(d))


def _dll_path() -> str | None:
    d = app_dir()
    if not d:
        return None
    for root, _, files in os.walk(d):
        if "WinSparkle.dll" in files:
            return os.path.join(root, "WinSparkle.dll")
    return None


def load():
    """The loaded DLL, or None. Loading alone never shows anything."""
    if _state["dll"] is not None:
        return _state["dll"]
    path = _dll_path()
    if not path:
        return None
    try:
        dll = ctypes.CDLL(path)
        dll.win_sparkle_set_appcast_url.argtypes = [ctypes.c_char_p]
        dll.win_sparkle_set_eddsa_public_key.argtypes = [ctypes.c_char_p]
        dll.win_sparkle_set_eddsa_public_key.restype = ctypes.c_int
        dll.win_sparkle_set_app_details.argtypes = [ctypes.c_wchar_p] * 3
        _state["dll"] = dll
        return dll
    except OSError:
        return None


def start(on_shutdown) -> bool:
    """Start WinSparkle (call once, from the main thread, after the window exists).

    on_shutdown: closes the app when WinSparkle is ready to run the new installer.
    """
    if _state["failed"] or not installed():
        return False
    if _state["callbacks"] is not None:
        return True
    dll = load()
    if dll is None:
        _state["failed"] = True
        return False
    try:
        can = ctypes.CFUNCTYPE(ctypes.c_int)(lambda: 1)
        shut = ctypes.CFUNCTYPE(None)(on_shutdown)
        _state["callbacks"] = (can, shut)  # kept alive for as long as WinSparkle may call them
        dll.win_sparkle_set_appcast_url(APPCAST.encode())
        if dll.win_sparkle_set_eddsa_public_key(PUBLIC_KEY.encode()) != 1:
            _state["failed"] = True
            return False
        dll.win_sparkle_set_app_details("Matthew Whitaker", "Media Download", __version__)
        dll.win_sparkle_set_can_shutdown_callback(can)
        dll.win_sparkle_set_shutdown_request_callback(shut)
        dll.win_sparkle_set_automatic_check_for_updates(1)
        dll.win_sparkle_set_update_check_interval(86400)
        dll.win_sparkle_init()
        return True
    except Exception:  # noqa: BLE001 - updates failing must never stop the app
        _state["failed"] = True
        return False


def check() -> bool:
    if _state["callbacks"] is None or _state["dll"] is None:
        return False
    try:
        _state["dll"].win_sparkle_check_update_with_ui()
        return True
    except Exception:  # noqa: BLE001
        return False


def cleanup() -> None:
    if _state["callbacks"] is not None and _state["dll"] is not None:
        try:
            _state["dll"].win_sparkle_cleanup()
        except Exception:  # noqa: BLE001
            pass
