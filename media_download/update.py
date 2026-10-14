"""Find and install new versions of the app from GitHub releases.

The check asks GitHub's public API for the latest release; no account, no
tracking, nothing sent but the request. Installing downloads that release's
zip, checks the new app starts (its --self-test), then hands over to a small
script that waits for this app to quit, swaps the new version into place and
opens it. If any step fails, the app already installed is left as it was.

Only the packaged app installs itself. A copy run from Python source or pip
is told the command that updates it instead.
"""
from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from . import __version__

REPO = "Matthew2244/ytdl-accessible"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGE = f"https://github.com/{REPO}/releases/latest"
MAC_ASSET = "Wavelength-mac.zip"
WIN_ASSET = "Wavelength-windows.zip"
APP_NAME = "Wavelength"


class UpdateError(Exception):
    pass


def current_version() -> str:
    # lets the update path be tested against a real release
    return os.environ.get("MEDIA_DOWNLOAD_PRETEND_VERSION", __version__)


def _vt(v: str) -> tuple:
    return tuple(int(x) for x in v.lstrip("v").split(".") if x.isdigit())


def _context():
    try:
        import certifi  # bundled with the app so HTTPS works on any machine

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _get(url: str, timeout: float = 15):
    req = urllib.request.Request(url, headers={"User-Agent": f"wavelength/{__version__}"})
    return urllib.request.urlopen(req, timeout=timeout, context=_context())


def latest() -> dict | None:
    """{'version': '1.2.0', 'assets': {name: url}, 'notes': str} or None when unreachable."""
    try:
        with _get(API) as r:
            data = json.load(r)
    except Exception:
        return None
    return {
        "version": data.get("tag_name", "").lstrip("v"),
        "assets": {a["name"]: a["browser_download_url"] for a in data.get("assets", [])},
        "notes": data.get("body") or "",
    }


def newer(info: dict | None) -> bool:
    return bool(info and info["version"] and _vt(info["version"]) > _vt(current_version()))


def installed_app() -> str | None:
    """Path of the packaged app this is running from, or None when run from source."""
    if not getattr(sys, "frozen", False):
        return None
    exe = os.path.realpath(sys.executable)
    if sys.platform == "darwin":
        marker = ".app/Contents/MacOS/"
        if marker in exe:
            return exe[: exe.index(marker) + 4]
        return None
    if sys.platform == "win32":
        return os.path.dirname(exe)
    return None


def rename_old_bundle() -> None:
    """On the Mac, an app updated from before 3.0 can still sit in Applications as
    "Media Download.app". Once this copy has quit, rename it to the new name, unless a
    Wavelength.app is already there. The app's identity (bundle id, signature) is unchanged,
    so Full Disk Access and updates carry on; renaming a running bundle would pull its files
    out from under it, which is why this waits until it has gone."""
    target = installed_app()
    if sys.platform != "darwin" or not target or os.path.basename(target) != "Media Download.app":
        return
    parent = os.path.dirname(target)
    new = os.path.join(parent, APP_NAME + ".app")
    if os.path.exists(new) or not os.access(parent, os.W_OK):
        return
    pid = os.getpid()
    script = (f"while kill -0 {pid} 2>/dev/null; do sleep 0.3; done; "
              f'[ -e "{new}" ] || mv "{target}" "{new}"')
    subprocess.Popen(["/bin/sh", "-c", script], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def how_to_update_source() -> str:
    return f'pip install -U "git+https://github.com/{REPO}"  (or git pull in a clone)'


def install(info: dict, relaunch: bool = True) -> str:
    """Download, verify and stage the new version; the swap happens when this app quits.

    Returns a sentence saying what will happen. Raises UpdateError with a
    plain reason on any failure, leaving the installed app untouched.
    """
    target = installed_app()
    if not target:
        raise UpdateError(f"this copy runs from Python, so update it with: {how_to_update_source()}")
    parent = os.path.dirname(target)
    if not os.access(parent, os.W_OK) or not os.access(target, os.W_OK):
        raise UpdateError(f"there is no permission to replace the app in {parent}. Download it from {PAGE}")
    asset = MAC_ASSET if sys.platform == "darwin" else WIN_ASSET
    url = info["assets"].get(asset)
    if not url:
        raise UpdateError(f"the new release has no {asset}. Download it from {PAGE}")

    work = tempfile.mkdtemp(prefix="wavelength-update-")
    zpath = os.path.join(work, asset)
    try:
        with _get(url, timeout=120) as r, open(zpath, "wb") as f:
            shutil.copyfileobj(r, f)
        new_dir = os.path.join(work, "new")
        if sys.platform == "darwin":
            # ditto keeps the bundle's symlinks and permissions; zipfile would not
            subprocess.run(["ditto", "-x", "-k", zpath, new_dir], check=True, capture_output=True)
            new_app = os.path.join(new_dir, f"{APP_NAME}.app")
            exe = os.path.join(new_app, "Contents", "MacOS", APP_NAME)
            subprocess.run(["xattr", "-dr", "com.apple.quarantine", new_app], capture_output=True)
        else:
            with zipfile.ZipFile(zpath) as z:
                z.extractall(new_dir)
            new_app = os.path.join(new_dir, APP_NAME)
            exe = os.path.join(new_app, f"{APP_NAME}.exe")
        log = os.path.join(work, "self-test.txt")
        with open(log, "w") as out:  # a file, not a pipe: a broken build's helper could hold a pipe open forever
            try:
                test = subprocess.run([exe, "--self-test"], stdout=out, stderr=subprocess.STDOUT, timeout=90)
            except subprocess.TimeoutExpired:
                raise UpdateError("the downloaded version did not finish its self-test, so nothing was changed")
        if test.returncode != 0 or "OK" not in open(log).read():
            raise UpdateError("the downloaded version did not start in its self-test, so nothing was changed")
    except UpdateError:
        shutil.rmtree(work, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(work, ignore_errors=True)
        raise UpdateError(f"the download did not complete ({e}). Nothing was changed") from e

    pid = os.getpid()
    if sys.platform == "darwin":
        script = os.path.join(work, "swap.sh")
        with open(script, "w") as f:
            f.write(
                "#!/bin/sh\n"
                f"while kill -0 {pid} 2>/dev/null; do sleep 0.3; done\n"
                f'old="{target}.old-$$"\n'
                f'mv "{target}" "$old" && mv "{new_app}" "{target}" && rm -rf "$old" || '
                f'{{ [ -d "$old" ] && [ ! -d "{target}" ] && mv "$old" "{target}"; }}\n'
                + (f'open "{target}"\n' if relaunch else "")
                + f'rm -rf "{work}"\n'
            )
        os.chmod(script, 0o755)
        subprocess.Popen(["/bin/sh", script], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        script = os.path.join(work, "swap.bat")
        exe_name = f"{APP_NAME}.exe"
        with open(script, "w") as f:
            f.write(
                "@echo off\r\n"
                ":wait\r\n"
                f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul && (timeout /t 1 /nobreak >nul & goto wait)\r\n'
                f'robocopy "{new_app}" "{target}" /MIR /NFL /NDL /NJH /NJS >nul\r\n'
                + (f'start "" "{os.path.join(target, exe_name)}"\r\n' if relaunch else "")
                + f'rmdir /s /q "{work}"\r\n'
            )
        subprocess.Popen(["cmd", "/c", script], creationflags=0x00000008 | 0x00000200,  # detached, new group
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Version {info['version']} is downloaded and checked. It replaces this one as soon as the app quits."
