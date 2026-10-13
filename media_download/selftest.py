"""--self-test: load everything, start a real worker process, show nothing.

Used by the build and by the updater before it swaps a new version in. A build
that lost the engine, the window code, or the ability to start its own worker
processes fails here instead of on someone's desk.
"""
from __future__ import annotations

import os
import sys
import tempfile


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
