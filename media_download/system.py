"""What differs between Mac and Windows: speaking, showing files, sounds."""
from __future__ import annotations

import os
import subprocess
import sys

import wx


def mac_accessibility_label(ctrl: wx.Window, label: str) -> None:
    """Give a control a spoken name on macOS, where wx has no API for it.

    Without this VoiceOver announces the report as just "text". Windows screen
    readers already take the name from the static label placed before it.
    """
    if sys.platform != "darwin":
        return
    try:
        import ctypes
        import ctypes.util

        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        def send(obj, sel, *args, restype=ctypes.c_void_p, argtypes=()):
            f = objc.objc_msgSend
            f.restype = restype
            f.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
            return f(obj, objc.sel_registerName(sel.encode()), *args)

        text = send(objc.objc_getClass(b"NSString"), "stringWithUTF8String:",
                    label.encode(), argtypes=(ctypes.c_char_p,))
        view = ctrl.GetHandle()
        targets = [view]
        if send(view, "respondsToSelector:", objc.sel_registerName(b"documentView"),
                restype=ctypes.c_bool, argtypes=(ctypes.c_void_p,)):
            doc = send(view, "documentView")
            if doc:
                targets.append(doc)
        for t in targets:
            send(t, "setAccessibilityLabel:", text, restype=None, argtypes=(ctypes.c_void_p,))
    except Exception:
        pass  # a missing label must never stop the app


def announce(text: str) -> None:
    """Have the screen reader say something without moving focus (macOS VoiceOver).

    Used for short confirmations like "Report copied". Elsewhere the same text
    also goes to the status bar, where Windows screen readers can read it.
    """
    if sys.platform != "darwin":
        return
    try:
        import ctypes
        import ctypes.util

        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        appkit = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/AppKit.framework/AppKit")
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        def send(obj, sel, *args, restype=ctypes.c_void_p, argtypes=()):
            f = objc.objc_msgSend
            f.restype = restype
            f.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
            return f(obj, objc.sel_registerName(sel.encode()), *args)

        def nsstr(t):
            return send(objc.objc_getClass(b"NSString"), "stringWithUTF8String:", t.encode(),
                        argtypes=(ctypes.c_char_p,))

        info = send(objc.objc_getClass(b"NSMutableDictionary"), "dictionary")
        send(info, "setObject:forKey:", nsstr(text), nsstr("AXAnnouncementKey"),
             restype=None, argtypes=(ctypes.c_void_p, ctypes.c_void_p))
        high = send(objc.objc_getClass(b"NSNumber"), "numberWithInt:", 90, argtypes=(ctypes.c_int,))
        send(info, "setObject:forKey:", high, nsstr("AXPriorityKey"),
             restype=None, argtypes=(ctypes.c_void_p, ctypes.c_void_p))
        app = send(objc.objc_getClass(b"NSApplication"), "sharedApplication")
        post = appkit.NSAccessibilityPostNotificationWithUserInfo
        post.restype = None
        post.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        post(app, nsstr("AXAnnouncementRequested"), info)
    except Exception:
        pass


def reveal(paths: list[str]) -> None:
    """Show files in Finder or File Explorer, selected.

    Copies spread over many folders would open a window per folder, so past a
    few folders only the first copy is shown.
    """
    if not paths:
        return
    if len({os.path.dirname(p) for p in paths}) > 3:
        paths = paths[:1]
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", *paths])
    elif sys.platform == "win32":
        subprocess.run(["explorer", "/select,", os.path.normpath(paths[0])])
    else:
        subprocess.run(["xdg-open", os.path.dirname(paths[0])])


def open_path(path: str) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - opening the user's own file
    else:
        subprocess.Popen(["xdg-open", path])


def play(kind: str) -> None:
    """'done' or 'failed'. System sounds, so nothing to ship and nothing to learn."""
    try:
        if sys.platform == "darwin":
            name = {"done": "Glass", "failed": "Basso"}.get(kind, "Pop")
            subprocess.Popen(["afplay", "/System/Library/Sounds/%s.aiff" % name])
        elif sys.platform == "win32":
            import winsound
            winsound.MessageBeep(winsound.MB_OK if kind == "done" else winsound.MB_ICONHAND)
    except Exception:  # noqa: BLE001 - a missing sound must never matter
        pass


def pushover(text: str, failed: bool = False) -> None:
    """Ping a phone through a `pushover` command, if this person has one (Matthew's setup)."""
    from .engine import PUSHOVER
    if not os.path.exists(PUSHOVER):
        return
    base = [PUSHOVER, "send", text, "--title", "Media Download"]
    if failed:
        base += ["--priority", "1"]
    sound = "ytdl-fail" if failed else "ytdl-done"

    # No Mac-side echo: the app has already spoken and played its own sound, so the echo would
    # say everything twice. Its VoiceOver speech landing on top of the app's own announcement
    # also left VoiceOver not answering until it was restarted (2026-10-12).
    env = dict(os.environ, PUSHOVER_NO_LOCAL_ECHO="1")

    def go():
        for cmd in (base + ["--sound", sound], base):
            try:
                if subprocess.run(cmd, capture_output=True, timeout=30, env=env).returncode == 0:
                    return
            except Exception:  # noqa: BLE001
                return
    import threading
    threading.Thread(target=go, daemon=True).start()
