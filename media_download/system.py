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


_menu_views: dict = {}    # NSView pointer -> function that opens that control's context menu
_menu_classes: set = set()
_menu_imps: list = []     # the ctypes callbacks must outlive the Objective-C methods using them


def mac_menu_action(ctrl, open_menu) -> None:
    """Let VoiceOver open a control's right-click menu (VO-Shift-M, its "show menu" action).

    A wx list on the Mac offers VoiceOver no actions at all, so VO-Shift-M had nothing to do.
    This gives the list's table view the standard AXShowMenu action, answered by open_menu.
    Done once per Objective-C class, then looked up per view; a failure leaves the control as
    it was (the right click and Command-K still work)."""
    if sys.platform != "darwin":
        return
    try:
        import ctypes
        import ctypes.util
        ctypes_, send = _objc_send()
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        for fn, res, args in (("object_getClass", ctypes.c_void_p, [ctypes.c_void_p]),
                              ("class_getSuperclass", ctypes.c_void_p, [ctypes.c_void_p]),
                              ("class_getMethodImplementation", ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_void_p]),
                              ("class_replaceMethod", ctypes.c_void_p,
                               [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]),
                              ("sel_registerName", ctypes.c_void_p, [ctypes.c_char_p]),
                              ("objc_getClass", ctypes.c_void_p, [ctypes.c_char_p])):
            getattr(objc, fn).restype = res
            getattr(objc, fn).argtypes = args
        view = ctrl.GetHandle()
        if send(view, "respondsToSelector:", objc.sel_registerName(b"documentView"),
                restype=ctypes.c_bool, argtypes=(ctypes.c_void_p,)):
            view = send(view, "documentView") or view
        _menu_views[view] = open_menu
        cls = objc.object_getClass(view)
        if cls in _menu_classes:
            return
        _menu_classes.add(cls)
        sup = objc.class_getSuperclass(cls)
        sel = objc.sel_registerName

        def show(self_):
            cb = _menu_views.get(self_)
            if cb:
                import wx
                wx.CallAfter(cb)
                return True
            return False

        name_str = send(objc.objc_getClass(b"NSString"), "stringWithUTF8String:", b"AXShowMenu",
                        argtypes=(ctypes.c_char_p,))
        send(name_str, "retain")

        PERFORM = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        perform = PERFORM(lambda self_, _cmd: show(self_))

        NAMES = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
        sup_names = NAMES(objc.class_getMethodImplementation(sup, sel(b"accessibilityActionNames")))

        def names_imp(self_, _cmd):
            arr = sup_names(self_, _cmd)
            if self_ not in _menu_views:
                return arr
            if not arr:
                arr = send(objc.objc_getClass(b"NSArray"), "array")
            return send(arr, "arrayByAddingObject:", name_str, argtypes=(ctypes.c_void_p,))
        names = NAMES(names_imp)

        ACT = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
        sup_act = ACT(objc.class_getMethodImplementation(sup, sel(b"accessibilityPerformAction:")))

        def act_imp(self_, _cmd, name):
            text = send(name, "UTF8String", restype=ctypes.c_char_p) if name else b""
            if text == b"AXShowMenu" and show(self_):
                return
            sup_act(self_, _cmd, name)
        act = ACT(act_imp)

        _menu_imps.extend([perform, names, act, sup_names, sup_act])
        objc.class_replaceMethod(cls, sel(b"accessibilityPerformShowMenu"), ctypes.cast(perform, ctypes.c_void_p), b"c@:")
        objc.class_replaceMethod(cls, sel(b"accessibilityActionNames"), ctypes.cast(names, ctypes.c_void_p), b"@@:")
        objc.class_replaceMethod(cls, sel(b"accessibilityPerformAction:"), ctypes.cast(act, ctypes.c_void_p), b"v@:@")
    except Exception:  # noqa: BLE001 - never stop the app over this
        pass


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


def _windows_value(ctrl, text: str) -> None:
    """The words a Windows screen reader reads as a slider's value. The accessible object is made
    once and reads the latest words each time; name, role and the rest stay Windows' own."""
    ctrl._value_words = text
    if getattr(ctrl, "_windows_value", None) is not None:
        return
    try:
        import wx
        if not hasattr(wx, "Accessible"):
            return

        class _Valued(wx.Accessible):
            def GetValue(self, child_id):
                words = getattr(ctrl, "_value_words", "")
                if child_id == 0 and words:
                    return (wx.ACC_OK, words)
                return (wx.ACC_NOT_IMPLEMENTED, "")

        acc = _Valued(ctrl)
        ctrl.SetAccessible(acc)
        ctrl._windows_value = acc  # keep the Python object alive with the control
    except Exception:  # noqa: BLE001
        pass


def mac_value_description(ctrl, text: str) -> None:
    """What VoiceOver says for a slider's value: "1 minute 3 seconds of 4 minutes", not "63".
    On Windows the same words go to NVDA, JAWS and Narrator through the slider's accessible value."""
    if sys.platform == "win32":
        _windows_value(ctrl, text)
        return
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


# Every sound the app makes: the name used in code, what it means in words (the Settings list
# reads these), and the system sound used if a theme's file is ever missing. The direction
# convention from Matthew's other tools: rising for good or begun, falling for failed or stopped.
SOUNDS = [
    ("opening", "Wavelength opens", "Ping"),
    ("done", "Downloads finished", "Glass"),
    ("failed", "A download failed", "Basso"),
    ("item_done", "One download finished, others still going", "Tink"),
    ("added", "Added to the list", "Pop"),
    ("stopped", "Stopped", "Bottle"),
    ("waiting", "Trying again by itself", "Morse"),
    ("results", "Search results arrived", "Purr"),
    ("no_more", "Nothing found, or no more results", "Funk"),
    ("copied", "Copied", "Tink"),
    ("update", "An update is ready", "Hero"),
    ("queue_end", "The player reached the end", "Submarine"),
    ("tour_done", "Finished the welcome tour", "Sosumi"),
    ("milestone", "A milestone: your 100th download and on", "Frog"),
    ("signed_in", "A browser's sign-in works", "Hero"),
    ("closing", "Wavelength closes", "Blow"),
]
SOUND_WORDS = {k: w for k, w, _ in SOUNDS}
# Ear candy from ElevenLabs, the same in every set: they live once in assets/sounds/shared.
SHARED = ("tour_done", "milestone", "signed_in")
THEMES = [("rhodes", "Rhodes electric piano"), ("kalimba", "Kalimba"), ("pizzicato", "Pizzicato strings"),
          ("soft", "Soft clicks"), ("system", "The system's own sounds")]


cue_handler = None  # the main window's _sound, set when it opens: settings, spacing and theme apply


def cue(kind: str) -> None:
    """Play a sound from any window (Search, the player), through the main window's rules."""
    if cue_handler:
        try:
            cue_handler(kind)
        except Exception:  # noqa: BLE001
            pass


def _sounds_dir() -> str:
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", "sounds")


def _ext() -> str:
    return ".wav" if sys.platform == "win32" else ".mp3"


def sound_file(kind: str, theme: str = "rhodes") -> str | None:
    """A theme's file for this sound, inside the app or beside the source; None means use the
    system sound. A theme missing one sound borrows Rhodes's before falling back."""
    if theme == "system" or kind not in SOUND_WORDS:
        return None
    ext = ".wav" if sys.platform == "win32" else ".mp3"
    for t in (theme, "shared", "rhodes"):
        path = os.path.join(_sounds_dir(), t, kind + ext)
        if os.path.exists(path):
            return path
    legacy = {"done": "done", "failed": "fail"}.get(kind)  # before themes: assets/sounds/done.mp3
    path = os.path.join(_sounds_dir(), legacy + ext) if legacy else ""
    return path if path and os.path.exists(path) else None


def sound_volume(cfg) -> float:
    """0 to 1. Zero is a real choice (silence), so never `or 1.0`."""
    try:
        return max(0.0, min(1.0, float(cfg.get("app_sound_volume", 1.0))))
    except (TypeError, ValueError):
        return 1.0


def sound_map(cfg) -> dict:
    """Each action's chosen sound (Choose Sounds); 2.5's "sounds off" list reads as "No sound"."""
    m = dict(cfg.get("app_sound_map") or {})
    for kind in cfg.get("app_sounds_off") or []:
        m.setdefault(kind, "none")
    return m


def custom_dir() -> str:
    """Where sounds people import live (inside the app's own folder, never in the app)."""
    from .engine import SUPPORT
    return os.path.join(SUPPORT, "sounds")


def custom_sounds() -> list[tuple[str, str]]:
    """Imported sounds: (file name, the name people see)."""
    try:
        names = sorted(f for f in os.listdir(custom_dir()) if f.lower().endswith((".wav", ".mp3", ".aiff", ".m4a"))
                       and ".part." not in f)
    except OSError:
        return []
    return [(f, os.path.splitext(f)[0]) for f in names]


def sound_choices() -> list[tuple[str, str]]:
    """Everything an action can sound like: (spec, words). "" follows the chosen set."""
    out = [("", "The sound set's own"), ("none", "No sound")]
    for f, name in custom_sounds():
        out.append(("custom:" + f, "Your sound: " + name))
    for theme, tw in THEMES:
        for kind, kw, _ in SOUNDS:
            out.append(("%s:%s" % (theme, kind), "%s: %s" % (tw, kw)))
    return out


def spec_words(spec: str) -> str:
    return dict(sound_choices()).get(spec, "The sound set's own")


def resolve(kind: str, theme: str, sound_map: dict | None = None) -> tuple[str, str] | None:
    """What to play for an action: ("file", path), ("system", name), or None for silence.

    An action follows the sound set unless Choose Sounds gave it something else: another
    set's sound, an imported file, or no sound."""
    spec = (sound_map or {}).get(kind, "")
    if spec == "none":
        return None
    if spec.startswith("custom:"):
        path = os.path.join(custom_dir(), spec[7:])
        if os.path.exists(path):
            return ("file", path)
        spec = ""  # the file was removed: fall back to the set rather than go quiet
    if ":" in spec:
        theme, kind = spec.split(":", 1)
    own = sound_file(kind, theme)
    if own:
        return ("file", own)
    return ("system", next((f for k, _, f in SOUNDS if k == kind), "Pop"))


def _scaled_wav(path: str, volume: float) -> str:
    """Windows plays a WAV at the system's level only, so make a quieter copy (16-bit only)."""
    import array
    import hashlib
    import wave
    from .engine import CACHE
    pct = int(round(volume * 100))
    key = hashlib.sha1(("%s|%s" % (path, os.path.getmtime(path))).encode()).hexdigest()[:16]
    out = os.path.join(CACHE, "sound-volume", str(pct), key + ".wav")
    if os.path.exists(out):
        return out
    with wave.open(path, "rb") as r:
        params = r.getparams()
        frames = r.readframes(r.getnframes())
    if params.sampwidth != 2 or params.nframes > params.framerate * 30:
        return path  # 16-bit only, and not a long file on the main thread
    samples = array.array("h", frames)
    if sys.byteorder != "little":
        samples.byteswap()
    for i in range(len(samples)):
        samples[i] = int(samples[i] * volume)
    if sys.byteorder != "little":
        samples.byteswap()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp"
    with wave.open(tmp, "wb") as w:  # whole or not at all: a half-written copy would be reused forever
        w.setparams(params)
        w.writeframes(samples.tobytes())
    os.replace(tmp, out)
    return out


def play_resolved(what, volume: float = 1.0, wait: bool = False) -> None:
    """Play what resolve() chose. A sound that can't play is never an error. `wait` is for the
    closing sound on Windows, where the sound dies with the app: it plays to the end first,
    up to 2 s. afplay on the Mac runs in its own session and carries on after the app has gone."""
    if not what or volume <= 0:
        return
    try:
        how, ref = what
        if sys.platform == "darwin":
            path = ref if how == "file" else "/System/Library/Sounds/%s.aiff" % ref
            cmd = ["afplay", path]
            if volume < 0.999:
                cmd[1:1] = ["-v", "%.2f" % volume]
            # Its own session: the closing sound carries on after the app has gone.
            subprocess.Popen(cmd, start_new_session=True)
        elif sys.platform == "win32":
            import winsound
            if how == "file" and ref.lower().endswith(".wav"):
                path = _scaled_wav(ref, volume) if volume < 0.999 else ref
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                if wait:
                    # The sound dies with the app: give it time to finish, but never more than
                    # two seconds, so a long sound of your own can't freeze the window.
                    import time
                    import wave
                    try:
                        with wave.open(path) as w:
                            length = w.getnframes() / float(w.getframerate())
                    except Exception:  # noqa: BLE001
                        length = 0.8
                    time.sleep(min(length, 2.0))
            else:
                winsound.MessageBeep(winsound.MB_OK)
    except Exception:  # noqa: BLE001
        pass


def play(kind: str, theme: str = "rhodes", volume: float = 1.0, sound_map: dict | None = None,
         wait: bool = False) -> None:
    """Play the sound for an action, through the set and any choice made in Choose Sounds."""
    play_resolved(resolve(kind, theme, sound_map), volume, wait)


def import_sound(src: str) -> tuple[str | None, str]:
    """Bring a sound file in for Choose Sounds: (file name, or None; a sentence saying what happened).

    Converted to a 16-bit WAV with ffmpeg when it's there, so it plays on Windows too and in
    any format afplay can't read (Ogg, Opus, FLAC...). Its level is left as made."""
    import re
    import shutil
    from .engine import find_tool, hidden_window
    stem = re.sub(r"[^\w\- ]+", "", os.path.splitext(os.path.basename(src))[0]).strip()[:60] or "sound"
    os.makedirs(custom_dir(), exist_ok=True)
    name, k = stem, 2
    while any(os.path.splitext(f)[0].lower() == name.lower() for f, _ in custom_sounds()):  # Mac and Windows ignore case
        name, k = "%s %d" % (stem, k), k + 1
    ffmpeg = find_tool("ffmpeg")
    if ffmpeg:
        out = os.path.join(custom_dir(), name + ".wav")
        part = out + ".part.wav"
        try:
            # The first 30 seconds: a sound for an action, never a whole song or mix.
            r = subprocess.run([ffmpeg, "-y", "-v", "error", "-i", src, "-vn", "-t", "30", "-ac", "2", "-ar", "44100",
                                "-c:a", "pcm_s16le", part], capture_output=True, text=True, timeout=120,
                               **hidden_window())
            if r.returncode == 0 and os.path.exists(part) and os.path.getsize(part) > 100:
                os.replace(part, out)
                return name + ".wav", "Imported %s." % name
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            os.remove(part)
        except OSError:
            pass
        return None, "That file couldn't be read as sound."
    ext = os.path.splitext(src)[1].lower()
    ok = (".wav",) if sys.platform == "win32" else (".wav", ".mp3", ".aiff", ".m4a")
    if ext not in ok:
        return None, ("Only %s files can be imported until the helper tools are here (Help, Get Helper Tools)."
                      % " or ".join(e[1:].upper() for e in ok))
    try:
        shutil.copyfile(src, os.path.join(custom_dir(), name + ext))
    except OSError as exc:
        return None, "That file couldn't be copied: %s." % exc.strerror
    return name + ext, "Imported %s." % name


def remove_sound(filename: str) -> None:
    try:
        os.remove(os.path.join(custom_dir(), os.path.basename(filename)))
    except OSError:
        pass


def pushover(text: str, failed: bool = False) -> None:
    """Ping a phone through a `pushover` command, if this person has one (Matthew's setup)."""
    from .engine import PUSHOVER
    if not os.path.exists(PUSHOVER):
        return
    base = [PUSHOVER, "send", text, "--title", "Wavelength"]
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
