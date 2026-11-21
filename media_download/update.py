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

import base64
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from . import __version__

REPO = "Matthew2244/wavelength"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGE = f"https://github.com/{REPO}/releases/latest"
MAC_ASSET = "Wavelength-mac.zip"
WIN_ASSET = "Wavelength-windows.zip"
WIN_SETUP = "Wavelength-Setup.exe"
APP_NAME = "Wavelength"
# The public half of the EdDSA key that signs every release (Sparkle's SUPublicEDKey and
# WinSparkle's key are this same one): a download is installed only if its signature checks out.
PUBLIC_KEY = "TJlHNK3idLU77+cj97Pwh4xeuvFhhIVm32CLFwN5Dz0="


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


def notes_rows(md: str) -> list[str]:
    """The release notes as one row per change, for the update window's list: each "- " item is a
    row, each paragraph is a row, Markdown's ** and ` are dropped (they'd be read aloud)."""
    rows = []
    for block in re.split(r"\n\s*\n", (md or "").strip()):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        if any(ln.startswith(("- ", "* ")) for ln in lines):
            item = []
            for ln in lines:
                if ln.startswith(("- ", "* ")):
                    if item:
                        rows.append(" ".join(item))
                    item = [ln[2:]]
                else:
                    item.append(ln)  # a wrapped line of the same item
            if item:
                rows.append(" ".join(item))
        else:
            rows.append(" ".join(lines))
    clean = []
    for r in rows:
        r = re.sub(r"\*\*([^*]+)\*\*", r"\1", r)
        r = re.sub(r"`([^`]+)`", r"\1", r)
        r = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", r)
        if r.strip():
            clean.append(r.strip())
    return clean


def windows_installed() -> bool:
    """Installed with Wavelength-Setup.exe (so updated with the next one), not unzipped."""
    if sys.platform != "win32":
        return False
    from . import winsparkle
    return winsparkle.installed()


def appcast_entry(info: dict, timeout: float = 15) -> dict | None:
    """The signed entry for this system's download in the release's appcast: {"url", "signature"}.
    None when the release has no appcast yet: CI attaches the builds first and the signed list
    comes minutes later, and a build without its signature is never installed."""
    name = "appcast-windows.xml" if windows_installed() else "appcast.xml"
    url = info.get("assets", {}).get(name)
    if not url:
        return None
    try:
        with _get(url, timeout=timeout) as r:
            xml = r.read().decode("utf-8", "replace")
    except Exception:
        return None
    m = re.search(r"<enclosure\b[^>]*>", xml)
    if not m:
        return None
    tag = m.group(0)
    u = re.search(r'url="([^"]+)"', tag)
    sig = re.search(r'sparkle:edSignature="([^"]+)"', tag)
    v = re.search(r"<sparkle:shortVersionString>([^<]+)<", xml)
    if not (u and sig) or (v and v.group(1).strip() != info.get("version")):
        return None
    return {"url": u.group(1).replace("&amp;", "&"), "signature": sig.group(1)}


def signature_ok(path: str, signature_b64: str, key_b64: str = PUBLIC_KEY) -> bool:
    """Ed25519 over the whole file, as Sparkle's sign_update makes it."""
    try:
        from Cryptodome.Signature import eddsa
        key = eddsa.import_public_key(base64.b64decode(key_b64))
        with open(path, "rb") as f:
            data = f.read()
        eddsa.new(key, "rfc8032").verify(data, base64.b64decode(signature_b64))
        return True
    except Exception:  # noqa: BLE001 - a bad signature, or no way to check one: not installed
        return False


def ready(info: dict | None) -> bool:
    """Newer, and its signed download is published: worth offering."""
    if not newer(info) or not installed_app():
        return newer(info)
    if sys.platform == "win32" and not windows_installed():
        return True  # a zip copy: no signed list for the zip, the self-test is its check
    return appcast_entry(info) is not None


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
    # Wait for this copy to quit, then for any Sparkle install to finish (an update installs at
    # this very path on quit), then rename only if nothing has appeared at the new name meanwhile.
    script = ('while kill -0 "$1" 2>/dev/null; do sleep 0.3; done; sleep 3; n=0; '
              'while pgrep -f "Sparkle|Autoupdate" >/dev/null 2>&1 && [ $n -lt 300 ]; do sleep 1; n=$((n+1)); done; '
              'sleep 2; [ -e "$3" ] || [ ! -d "$2" ] || mv "$2" "$3"')
    subprocess.Popen(["/bin/sh", "-c", script, "rename", str(os.getpid()), target, new], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def how_to_update_source() -> str:
    return f'pip install -U "git+https://github.com/{REPO}"  (or git pull in a clone)'


def windows_swap(work: str, pid: int, new_app: str, target: str, relaunch: bool) -> tuple[str, str]:
    """Write the Windows swap script into work. Returns (script path, command line to run it).

    The script stays plain ASCII and gets every path as an argument: cmd reads a batch file in
    the OEM code page, so a path written into it (C:\\Users\\José) would arrive garbled, while
    arguments arrive whole. The command is a string in cmd's /s form, since cmd /c strips the
    outer quotes of a line holding several quoted paths. ping waits a second where timeout
    can't (no console); /R:3 /W:1 keep one locked file from stalling the swap forever.
    """
    script = os.path.join(work, "swap.bat")
    with open(script, "w", encoding="ascii", newline="") as f:
        f.write(
            "@echo off\r\n"
            ":wait\r\n"
            f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul && (ping -n 2 127.0.0.1 >nul & goto wait)\r\n'
            'robocopy "%~1" "%~2" /MIR /IS /IT /R:3 /W:1 /NFL /NDL /NJH /NJS >nul\r\n'
            'if exist "%~5\\relaunch" start "" "%~2\\%~4"\r\n'
            'cd /d "%TEMP%"\r\n'
            'rmdir /s /q "%~5"\r\n'
        )
    command = 'cmd /s /c ""%s" "%s" "%s" %s "%s.exe" "%s""' % (
        script, new_app, target, "1" if relaunch else "0", APP_NAME, work)
    return script, command


def install(info: dict, relaunch: bool = True) -> str:
    """Download, verify and stage the new version; the swap happens when this app quits.

    Returns a sentence saying what will happen. Raises UpdateError with a
    plain reason on any failure, leaving the installed app untouched.
    """
    target = installed_app()
    if not target:
        raise UpdateError(f"this copy runs from Python, so update it with: {how_to_update_source()}")
    if windows_installed():
        return _install_setup(info, target, relaunch)
    parent = os.path.dirname(target)
    if not os.access(parent, os.W_OK) or not os.access(target, os.W_OK):
        raise UpdateError(f"there is no permission to replace the app in {parent}. Download it from {PAGE}")
    asset = MAC_ASSET if sys.platform == "darwin" else WIN_ASSET
    url = info["assets"].get(asset)
    if not url:
        raise UpdateError(f"the new release has no {asset}. Download it from {PAGE}")

    entry = appcast_entry(info) if sys.platform == "darwin" else None
    if sys.platform == "darwin" and not entry:
        raise UpdateError("the new version's signed download isn't published yet. Try again in a few minutes")
    work = tempfile.mkdtemp(prefix="wavelength-update-")
    zpath = os.path.join(work, asset)
    try:
        with _get(url, timeout=120) as r, open(zpath, "wb") as f:
            shutil.copyfileobj(r, f)
        if entry and not signature_ok(zpath, entry["signature"]):
            raise UpdateError("the download's signature didn't match, so nothing was changed")
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
                # Opened again only when the app asked for that as it closed (relaunch_after):
                # an update waiting for an ordinary quit must not bring the app back by itself.
                f'[ -f "{work}/relaunch" ] && open "{target}"\n'
                f'rm -rf "{work}"\n'
            )
        os.chmod(script, 0o755)
        subprocess.Popen(["/bin/sh", script], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        script, command = windows_swap(work, pid, new_app, target, relaunch)
        subprocess.Popen(command, creationflags=0x00000008 | 0x00000200,  # detached, new group
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _staged["work"] = work
    if relaunch:
        relaunch_after()
    return f"Version {info['version']} is downloaded and checked. It replaces this one as soon as the app quits."


_staged: dict = {"work": None}


def staged() -> bool:
    """A new version is downloaded, checked and waiting for this app to quit."""
    return bool(_staged["work"]) and os.path.isdir(_staged["work"])


def relaunch_after() -> None:
    """Open the new version once the swap is done: said just before the app closes itself to
    update. Without it an update waiting for an ordinary quit installs and stays closed."""
    if staged():
        open(os.path.join(_staged["work"], "relaunch"), "w").close()


def _install_setup(info: dict, target: str, relaunch: bool) -> str:
    """An installed Windows copy: fetch Wavelength-Setup.exe, check its signature, and run it
    quietly once this app has quit (per-user, so no administrator prompt)."""
    entry = appcast_entry(info)
    if not entry:
        raise UpdateError("the new version's signed installer isn't published yet. Try again in a few minutes")
    work = tempfile.mkdtemp(prefix="wavelength-update-")
    setup = os.path.join(work, WIN_SETUP)
    try:
        with _get(entry["url"], timeout=300) as r, open(setup, "wb") as f:
            shutil.copyfileobj(r, f)
        if not signature_ok(setup, entry["signature"]):
            raise UpdateError("the installer's signature didn't match, so nothing was changed")
    except UpdateError:
        shutil.rmtree(work, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(work, ignore_errors=True)
        raise UpdateError(f"the download did not complete ({e}). Nothing was changed") from e
    script, command = windows_setup_run(work, os.getpid(), setup)
    subprocess.Popen(command, creationflags=0x00000008 | 0x00000200,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _staged["work"] = work
    if relaunch:
        relaunch_after()
    return f"Version {info['version']} is downloaded and checked. It installs as soon as the app quits."


def windows_setup_run(work: str, pid: int, setup: str) -> tuple[str, str]:
    """The script that waits for this app to quit, then runs the installer quietly. The
    installer opens the app again only when the relaunch marker is there (/relaunch=1)."""
    script = os.path.join(work, "install.bat")
    with open(script, "w", encoding="ascii", newline="") as f:
        f.write(
            "@echo off\r\n"
            ":wait\r\n"
            f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul && (ping -n 2 127.0.0.1 >nul & goto wait)\r\n'
            'set R=0\r\n'
            'if exist "%~2\\relaunch" set R=1\r\n'
            '"%~1" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /relaunch=%R%\r\n'
            'cd /d "%TEMP%"\r\n'
            'rmdir /s /q "%~2"\r\n'
        )
    command = 'cmd /s /c ""%s" "%s" "%s""' % (script, setup, work)
    return script, command
