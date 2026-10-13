"""Updates on the Mac through Sparkle, the update system most Mac apps outside the App Store use.

Why Sparkle and not our own updater: every update is signed with an EdDSA key that lives
only in Matthew's Keychain (the public half is SUPublicEDKey in Info.plist), so a
compromised GitHub release can't push anything to anyone. People also get the update
window Mac users already know: release notes, Install, Skip This Version, Remind Me
Later, with background downloads installed on quit.

Sparkle.framework sits in the app's Contents/Frameworks (build_app.py puts it there).
It's driven through the Objective-C runtime with ctypes, the way system.py talks to
AppKit, so there's no extra Python dependency. Run from source, or on Windows, this
module reports itself unavailable and update.py does the job instead.
"""
from __future__ import annotations

import os
import sys

_state = {"controller": None, "failed": False}


def _objc():
    import ctypes
    import ctypes.util
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]

    def send(obj, sel, *args, restype=ctypes.c_void_p, argtypes=()):
        f = objc.objc_msgSend
        f.restype = restype
        f.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
        return f(obj, objc.sel_registerName(sel.encode()), *args)

    def nsstr(text):
        return send(objc.objc_getClass(b"NSString"), "stringWithUTF8String:", text.encode(),
                    argtypes=(ctypes.c_char_p,))
    return ctypes, objc, send, nsstr


def framework_path() -> str | None:
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    exe = os.path.realpath(sys.executable)  # .../Media Download.app/Contents/MacOS/Media Download
    path = os.path.join(os.path.dirname(os.path.dirname(exe)), "Frameworks", "Sparkle.framework")
    return path if os.path.isdir(path) else None


def load() -> bool:
    """Load the framework and find its controller class. True when Sparkle can be used."""
    path = framework_path()
    if not path:
        return False
    try:
        ctypes, objc, send, nsstr = _objc()
        bundle = send(objc.objc_getClass(b"NSBundle"), "bundleWithPath:", nsstr(path),
                      argtypes=(ctypes.c_void_p,))
        if not bundle or not send(bundle, "load", restype=ctypes.c_bool):
            return False
        return bool(objc.objc_getClass(b"SPUStandardUpdaterController"))
    except Exception:  # noqa: BLE001 - no Sparkle means the old updater, never a crash
        return False


def start() -> bool:
    """Start Sparkle's updater: it checks on its own schedule (daily). True when running."""
    if _state["controller"] is not None:
        return True
    if _state["failed"] or not load():
        _state["failed"] = True
        return False
    try:
        ctypes, objc, send, nsstr = _objc()
        cls = objc.objc_getClass(b"SPUStandardUpdaterController")
        obj = send(cls, "alloc")
        ctrl = send(obj, "initWithStartingUpdater:updaterDelegate:userDriverDelegate:", True, None, None,
                    argtypes=(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p))
        if not ctrl:
            _state["failed"] = True
            return False
        _state["controller"] = ctrl  # alloc'd, so it stays alive for the life of the app
        return True
    except Exception:  # noqa: BLE001
        _state["failed"] = True
        return False


def check() -> bool:
    """Help, Check for App Updates: Sparkle's own window takes it from here."""
    if not start():
        return False
    try:
        ctypes, objc, send, nsstr = _objc()
        send(_state["controller"], "checkForUpdates:", None, restype=None, argtypes=(ctypes.c_void_p,))
        return True
    except Exception:  # noqa: BLE001
        return False
