"""--self-test: load everything, start a real worker process, show nothing.

Used by the build and by the updater before it swaps a new version in. A build
that lost the engine, the window code, or the ability to start its own worker
processes fails here instead of on someone's desk.
"""
from __future__ import annotations

import os
import sys
import tempfile


def check_list_reads_states() -> str | None:
    """A check list's rows, read the way a screen reader reads them: each must be a checkbox that
    says whether it's checked. Mac: the table's accessibility tree, in this process. Windows: the
    list's MSAA object (what NVDA and JAWS read; Narrator's UI Automation bridges from it).
    Returns what's wrong, or None."""
    import wx
    from . import system
    frame = wx.Frame(None)
    lst = wx.CheckListBox(frame, choices=["Safari", "Chrome"])
    system.check_list_states(lst)
    lst.Check(1)
    lst.SetSelection(0)
    try:
        if sys.platform == "darwin":
            ctypes, send = system._objc_send()
            import ctypes.util
            objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
            objc.objc_getClass.restype = ctypes.c_void_p
            objc.objc_getClass.argtypes = [ctypes.c_char_p]

            def ns(t):
                return send(objc.objc_getClass(b"NSString"), "stringWithUTF8String:", t.encode(),
                            argtypes=(ctypes.c_char_p,))

            def ax(el, name):
                return send(el, "accessibilityAttributeValue:", ns(name), argtypes=(ctypes.c_void_p,))

            def text(o):
                return send(send(o, "description"), "UTF8String", restype=ctypes.c_char_p).decode() if o else ""
            table = send(lst.GetHandle(), "documentView")
            rows = ax(table, "AXRows")
            got = []
            for r in range(send(rows, "count", restype=ctypes.c_ulong)):
                kids = ax(send(rows, "objectAtIndex:", r, argtypes=(ctypes.c_ulong,)), "AXChildren")
                cells = [send(kids, "objectAtIndex:", k, argtypes=(ctypes.c_ulong,))
                         for k in range(send(kids, "count", restype=ctypes.c_ulong))]
                got.append(tuple(text(ax(c, a)) for c in cells for a in ("AXRole", "AXValue")))
            want = [("AXCheckBox", "0", "AXTextField", "unchecked"), ("AXCheckBox", "1", "AXTextField", "checked")]
            return None if got == want else "rows read %s" % got
        if sys.platform == "win32":
            got = _msaa_rows(lst.GetHandle(), 2)
            checkbutton, checked = 0x2C, 0x10
            want = [("Safari", checkbutton, False), ("Chrome", checkbutton, True)]
            seen = [(name, role, bool(state & checked)) for name, role, state in got]
            return None if seen == want else "rows read (name, role, checked) %s" % seen
        return None
    finally:
        frame.Destroy()


def _msaa_rows(hwnd, count):
    """(name, role, state) of a window's first `count` children through its MSAA object, with ctypes."""
    import ctypes
    from ctypes import wintypes

    class VARIANT(ctypes.Structure):
        _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                    ("r3", ctypes.c_ushort), ("val", ctypes.c_longlong), ("pad", ctypes.c_longlong)]

    class GUID(ctypes.Structure):
        _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort),
                    ("d", ctypes.c_ubyte * 8)]
    iid = GUID(0x618736E0, 0x3C3D, 0x11CF, (ctypes.c_ubyte * 8)(0x81, 0x0C, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71))
    acc = ctypes.c_void_p()
    oleacc = ctypes.windll.oleacc
    hr = oleacc.AccessibleObjectFromWindow(wintypes.HWND(hwnd), ctypes.c_long(-4), ctypes.byref(iid),
                                           ctypes.byref(acc))
    if hr != 0 or not acc:
        raise OSError("AccessibleObjectFromWindow failed: %#x" % (hr & 0xFFFFFFFF))
    vtbl = ctypes.cast(ctypes.cast(acc, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, VARIANT, ctypes.POINTER(VARIANT))
    get_role, get_state = proto(vtbl[13]), proto(vtbl[14])
    get_name = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, VARIANT, ctypes.POINTER(ctypes.c_void_p))(vtbl[10])
    out = []
    try:
        for i in range(1, count + 1):
            child, role, state = VARIANT(vt=3, val=i), VARIANT(), VARIANT()
            get_role(acc, child, ctypes.byref(role))
            get_state(acc, child, ctypes.byref(state))
            bstr = ctypes.c_void_p()
            get_name(acc, child, ctypes.byref(bstr))
            name = ctypes.wstring_at(bstr.value) if bstr.value else None
            if bstr.value:
                ctypes.windll.oleaut32.SysFreeString(bstr)
            out.append((name, role.val & 0xFFFFFFFF, state.val & 0xFFFFFFFF))
    finally:
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])(acc)
    return out


def update_signature_check() -> str | None:
    """Updates are installed only with a good EdDSA signature: the check must work inside the
    app, and must refuse a file that was changed. A throwaway key, signed here."""
    import base64
    from Cryptodome.PublicKey import ECC
    from Cryptodome.Signature import eddsa
    from . import update
    key = ECC.generate(curve="Ed25519")
    pub = base64.b64encode(key.public_key().export_key(format="raw")).decode()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "blob")
        with open(path, "wb") as f:
            f.write(b"wavelength update")
        sig = base64.b64encode(eddsa.new(key, "rfc8032").sign(b"wavelength update")).decode()
        if not update.signature_ok(path, sig, pub):
            return "a good signature was refused"
        with open(path, "ab") as f:
            f.write(b"!")
        if update.signature_ok(path, sig, pub):
            return "a changed file was accepted"
    return None


def run() -> int:
    from . import APP_NAME, __version__
    with tempfile.TemporaryDirectory() as d:
        os.environ["MEDIA_DOWNLOAD_TEST_DIR"] = d
        import importlib
        from . import engine
        importlib.reload(engine)
        problems = []
        try:
            import wx
            from . import gui
            app = wx.App(False)
            if sys.platform in ("darwin", "win32"):
                # Sign In Here: a real sign-in window, a page on this computer, an HttpOnly cookie kept.
                from . import signin
                said = signin.round_trip()
                if said:
                    problems.append("sign-in window: %s" % said)
                else:
                    print("Sign-in window: kept an HttpOnly cookie from a page on this computer.")
            said = check_list_reads_states()
            if said:
                problems.append("check list: %s" % said)
            else:
                print("Check lists: each row reads as a checkbox with its state.")
            frame = gui.MainFrame()
            frame.timer.Stop()
            frame.Destroy()
            app.Destroy()
        except Exception as exc:  # noqa: BLE001
            problems.append("window: %s" % exc)
        try:
            from .manager import run_task
            names = []
            events = run_task({"task": "recognise", "url": "https://www.youtube.com/watch?v=jNQXAC9IVRw"},
                              lambda ev: names.append(ev.get("name")) if ev.get("ev") == "recognised" else None,
                              timeout=60)
            engine_ev = [e for e in events if e.get("ev") == "engine"]
            if not engine_ev or not names:
                problems.append("worker: %s" % (events[-3:] or "no output"))
        except Exception as exc:  # noqa: BLE001
            problems.append("worker: %s" % exc)
        if getattr(sys, "frozen", False):
            imp = [e for e in run_task({"task": "impersonate"}, timeout=60) if e.get("ev") == "impersonate"]
            if not imp or not imp[0].get("targets"):
                problems.append("impersonation: curl_cffi missing from the app")
        if getattr(sys, "frozen", False):
            try:
                import importlib.metadata as md
                md.version("yt-dlp")  # without it the app can't tell which engine it ships
            except Exception as exc:  # noqa: BLE001
                problems.append("engine metadata: %s" % exc)
        try:
            said = update_signature_check()
            if said:
                problems.append("update signatures: %s" % said)
        except Exception as exc:  # noqa: BLE001
            problems.append("update signatures: %s" % exc)
        try:
            import yt_dlp_ejs  # noqa: F401  the YouTube challenge solver must be inside
        except Exception as exc:  # noqa: BLE001
            problems.append("ejs: %s" % exc)
        if sys.platform == "darwin" and getattr(sys, "frozen", False):
            from . import sparkle
            if not sparkle.load():
                problems.append("updates: Sparkle.framework didn't load")
        if sys.platform == "win32" and getattr(sys, "frozen", False):
            from . import winsparkle
            if winsparkle.load() is None:
                problems.append("updates: WinSparkle.dll didn't load")
        if sys.platform == "win32":
            # Windows speech: Prism must load inside the app and offer UI Automation at least.
            try:
                from .system import load_prism
                prism = load_prism()
                print("Prism compiled part: %s" % getattr(sys.modules.get("prism._prism_cffi"), "__file__", "?"))
                ctx = prism.Context()
                if not ctx.exists(prism.BackendId.UIA):
                    problems.append("speech: Prism has no UI Automation backend")
                names = [ctx.name_of(ctx.id_of(i)) for i in range(ctx.backends_count)]
                print("Windows speech backends: " + ", ".join(names))
            except Exception as exc:  # noqa: BLE001
                problems.append("speech: %s" % exc)
                base = getattr(sys, "_MEIPASS", "")
                for root, _, files in os.walk(base):
                    for f in files:
                        if "prism" in f.lower() or "cffi" in f.lower():
                            print("  bundled: " + os.path.join(root, f)[len(base):])
    status = "OK" if not problems else "FAILED: " + "; ".join(problems)
    print("%s %s %s" % (APP_NAME, __version__, status))
    sys.stdout.flush()
    return 0 if not problems else 1
