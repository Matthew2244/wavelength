"""Entry point for the packaged app (PyInstaller)."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from media_download.launch import main
    sys.exit(main())
