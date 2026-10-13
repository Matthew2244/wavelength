"""One entry point for every way this program is started.

The packaged app is a single executable, so its download workers, its engine
probe and its self-test are all the same program started with a flag.
"""
from __future__ import annotations

import sys


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # A windowed Windows build may start with no stdout or stderr at all.
    import os
    for name, fd in (("stdout", 1), ("stderr", 2)):
        if getattr(sys, name) is None:
            try:
                setattr(sys, name, os.fdopen(fd, "w", buffering=1, encoding="utf-8"))
            except OSError:
                setattr(sys, name, open(os.devnull, "w"))
    if argv[:1] == ["--worker"]:
        from .worker import main as worker_main
        return worker_main()
    if argv[:1] == ["--probe-engine"] and len(argv) > 1:
        sys.path.insert(0, argv[1])
        import yt_dlp  # noqa: F401
        import yt_dlp_ejs  # noqa: F401
        from yt_dlp.version import __version__
        print(__version__)
        return 0
    if argv[:1] == ["--self-test"]:
        from .selftest import run
        return run()
    if "--multiprocessing-fork" in argv:
        return 0
    from .gui import main as gui_main
    return gui_main(argv)
