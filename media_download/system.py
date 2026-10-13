"""What differs between Mac and Windows: speaking, showing files, sounds."""
from __future__ import annotations

import os
import subprocess
import sys




def windows_name(ctrl, label: str) -> None:
    """Give a control a spoken name on Windows, for the few with no label straight before them
    (a progress bar, say). Only the control's own name is replaced; its items, value and role
    still come from Windows, which is what wx does for anything answered 'not implemented'."""
    if sys.platform != "win32":
        return
    try:
        import wx
        if not hasattr(wx, "Accessible"):
            return

        class _Named(wx.Accessible):
            def GetName(self, child_id):
                if child_id == 0:
                    return (wx.ACC_OK, label)
                return (wx.ACC_NOT_IMPLEMENTED, "")

        acc = _Named(ctrl)
        ctrl.SetAccessible(acc)
        ctrl._windows_name = acc  # keep the Python object alive with the control
    except Exception:  # noqa: BLE001
        pass


def mac_accessibility_label(ctrl, label: str) -> None:
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


_win_reader = {"ctx": None, "failed": False}

# Screen readers first, checked as running; then UI Automation notifications, which Narrator
# (and NVDA, JAWS) hear. Never SAPI or OneCore: with no screen reader running, a sighted
# person should not suddenly be talked at.
_WIN_ORDER = ("NVDA", "JAWS", "ZDSR", "SYSTEM_ACCESS", "ZOOM_TEXT", "SENSE_READER", "PC_TALKER",
              "BOY_PC_READER", "UIA")


def load_prism():
    """Import Prism, also inside the packaged app.

    Prism finds its compiled part by adding prism/_native to the package's path at import
    time, which the packaged app's importer doesn't follow ("No module named
    prism._prism_cffi", caught by the Windows self-test). So when frozen, find it by name
    and load it first.
    """
    if getattr(sys, "frozen", False) and "prism._prism_cffi" not in sys.modules:
        import importlib.util
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        for root, _, files in os.walk(base):
            hit = [f for f in files if f.startswith("_prism_cffi") and f.endswith((".pyd", ".so"))]
            if hit:
                if sys.platform == "win32":
                    os.add_dll_directory(root)  # prism.dll sits beside it
                spec = importlib.util.spec_from_file_location("prism._prism_cffi", os.path.join(root, hit[0]))
                mod = importlib.util.module_from_spec(spec)
                sys.modules["prism._prism_cffi"] = mod
                spec.loader.exec_module(mod)
                break
    import prism
    return prism


def _announce_windows(text: str) -> str | None:
    """Speak through the running Windows screen reader with Prism. Returns the reader's name."""
    if _win_reader["failed"]:
        return None
    try:
        prism = load_prism()
        if _win_reader["ctx"] is None:
            _win_reader["ctx"] = prism.Context()
        ctx = _win_reader["ctx"]
        for name in _WIN_ORDER:
            bid = getattr(prism.BackendId, name, None)
            if bid is None or not ctx.exists(bid):
                continue
            try:
                backend = ctx.acquire(bid)  # initialising fails for a reader that isn't running
            except Exception:  # noqa: BLE001
                continue
            feats = backend.features
            if name != "UIA" and not feats.is_supported_at_runtime:
                continue
            if feats.supports_output:
                backend.output(text, interrupt=False)  # speech and braille
            else:
                backend.speak(text, interrupt=False)
            return name
    except Exception:  # noqa: BLE001 - no Prism, or it failed to load: the status bar still shows it
        _win_reader["failed"] = True
    return None


def _objc_send():
    import ctypes
    import ctypes.util
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]

    def send(o, sel, *a, restype=ctypes.c_void_p, argtypes=()):
        f = objc.objc_msgSend
        f.restype = restype
        f.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
        return f(o, objc.sel_registerName(sel.encode()), *a)
    return ctypes, send


def mac_focus(ctrl) -> bool:
    """Give a control keyboard focus the Mac's way. A wx slider takes it from the Mac but not
    from wx's SetFocus, and wx doesn't notice either way, so ask the window directly."""
    if sys.platform != "darwin":
        ctrl.SetFocus()
        return wx_focus_is(ctrl)
    try:
        ctypes, send = _objc_send()
        h = ctrl.GetHandle()
        win = send(h, "window")
        send(win, "makeFirstResponder:", h, restype=ctypes.c_bool, argtypes=(ctypes.c_void_p,))
        return mac_has_focus(ctrl)
    except Exception:  # noqa: BLE001
        return False


def mac_has_focus(ctrl) -> bool:
    if sys.platform != "darwin":
        return wx_focus_is(ctrl)
    try:
        ctypes, send = _objc_send()
        h = ctrl.GetHandle()
        return send(send(h, "window"), "firstResponder") == h
    except Exception:  # noqa: BLE001
        return False


def wx_focus_is(ctrl) -> bool:
    import wx
    return wx.Window.FindFocus() is ctrl


def mac_value_description(ctrl, text: str) -> None:
    """What VoiceOver says for a slider's value: "1 minute 3 seconds of 4 minutes", not "63"."""
    if sys.platform != "darwin":
        return
    try:
        import ctypes
        import ctypes.util
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        f = objc.objc_msgSend
        f.restype = ctypes.c_void_p
        f.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]
        s = f(objc.objc_getClass(b"NSString"), objc.sel_registerName(b"stringWithUTF8String:"), text.encode())
        f.restype = None
        f.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        f(ctrl.GetHandle(), objc.sel_registerName(b"setAccessibilityValueDescription:"), s)
    except Exception:  # noqa: BLE001
        pass


def announce(text: str) -> None:
    """Have the screen reader say something without moving focus.

    Mac: VoiceOver, through an accessibility announcement. Windows: NVDA, JAWS and the
    others through Prism, or UI Automation for Narrator. The same text also goes to the
    status bar, so nothing depends on this working.
    """
    if sys.platform == "win32":
        _announce_windows(text)
        return
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


def dock_badge(text: str) -> None:
    """The number on the Dock icon ("3"), or none. Readable at a glance from any app, and
    VoiceOver reads it in the Dock too."""
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
        app = send(objc.objc_getClass(b"NSApplication"), "sharedApplication")
        tile = send(app, "dockTile")
        label = send(objc.objc_getClass(b"NSString"), "stringWithUTF8String:", text.encode(),
                     argtypes=(ctypes.c_char_p,)) if text else None
        send(tile, "setBadgeLabel:", label, restype=None, argtypes=(ctypes.c_void_p,))
    except Exception:  # noqa: BLE001
        pass


def taskbar_progress(frame, fraction: float | None) -> None:
    """Progress on the Windows taskbar button. None clears it."""
    if sys.platform != "win32":
        return
    try:
        bar = frame.MSWGetTaskBarButton()
        if fraction is None:
            bar.SetProgressState(0)  # no progress
        else:
            bar.SetProgressRange(1000)
            bar.SetProgressValue(int(fraction * 1000))
    except Exception:  # noqa: BLE001
        pass


_awake = {"proc": None, "on": False}


def keep_awake(on: bool) -> None:
    """Keep the computer from going to sleep while downloads run, and only then.

    A long playlist left overnight stops halfway if the computer sleeps. The screen may still
    turn off. Mac: `caffeinate -i` while busy. Windows: SetThreadExecutionState. Call from the
    main thread, as the window's timer does.
    """
    if on == _awake["on"]:
        return
    _awake["on"] = on
    try:
        if sys.platform == "darwin":
            if on:
                _awake["proc"] = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())],
                                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif _awake["proc"] is not None:
                _awake["proc"].terminate()
                _awake["proc"] = None
        elif sys.platform == "win32":
            import ctypes
            ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:  # noqa: BLE001
        pass


def open_path(path: str) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - opening the user's own file
    else:
        subprocess.Popen(["xdg-open", path])


def sound_file(kind: str) -> str | None:
    """The app's own sound for 'done' or 'failed', inside the app or beside the source."""
    name = {"done": "done", "failed": "fail"}.get(kind)
    if not name:
        return None
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "assets", "sounds", name + (".wav" if sys.platform == "win32" else ".mp3"))
    return path if os.path.exists(path) else None


def play(kind: str) -> None:
    """'done' (rising) or 'failed' (falling): the app's own sounds, chosen by ear, falling back to
    the system's Glass and Basso if a file is ever missing. A missing sound must never matter."""
    try:
        own = sound_file(kind)
        if sys.platform == "darwin":
            if own:
                subprocess.Popen(["afplay", own])
            else:
                name = {"done": "Glass", "failed": "Basso"}.get(kind, "Pop")
                subprocess.Popen(["afplay", "/System/Library/Sounds/%s.aiff" % name])
        elif sys.platform == "win32":
            import winsound
            if own:
                winsound.PlaySound(own, winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                winsound.MessageBeep(winsound.MB_OK if kind == "done" else winsound.MB_ICONHAND)
    except Exception:  # noqa: BLE001
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
