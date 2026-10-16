"""Where things live, which helper tools to use, and keeping yt-dlp current.

yt-dlp is the download engine. It breaks whenever a big site changes, so it
must update far more often than this app does. The app ships with one copy
inside it, and newer copies are fetched from PyPI into Application Support
and preferred whenever they are newer. A copy that fails to import is skipped,
so a bad update can never take the app down.

The helper tools (ffmpeg to convert, ffprobe to inspect, deno to answer
YouTube's player challenge) are found where they already are (Homebrew,
PATH), and otherwise fetched once into Application Support.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

HOME = os.path.expanduser("~")

if sys.platform == "darwin":
    SUPPORT = os.path.join(HOME, "Library", "Application Support", "Wavelength")
    CACHE = os.path.join(HOME, "Library", "Caches", "Wavelength")
elif sys.platform == "win32":
    SUPPORT = os.path.join(os.environ.get("APPDATA", HOME), "Wavelength")
    CACHE = os.path.join(os.environ.get("LOCALAPPDATA", HOME), "Wavelength", "Cache")
else:
    SUPPORT = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.join(HOME, ".local", "share")), "wavelength")
    CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.join(HOME, ".cache")), "wavelength")


def _move_old_folders():
    """The app was called Media Download until 3.0 (2026-10-13). Its folders (the download list,
    imported sounds, engine, helper tools, player positions) move to the new name once, by
    renaming, so nothing is lost or duplicated. A failure leaves them where they were."""
    for new in (SUPPORT, CACHE):
        old = new.replace("Wavelength", "Media Download").replace("wavelength", "media-download")
        if old == new or not os.path.isdir(old):
            continue
        try:
            if not os.path.exists(new):
                os.makedirs(os.path.dirname(new), exist_ok=True)
                os.rename(old, new)
                continue
            # A move that failed once (a file locked on Windows) left a fresh new folder behind:
            # bring over anything it doesn't have yet, item by item, instead of giving up for good.
            for name in os.listdir(old):
                src, dst = os.path.join(old, name), os.path.join(new, name)
                if not os.path.exists(dst):
                    os.rename(src, dst)
            if not os.listdir(old):
                os.rmdir(old)
        except OSError:
            pass


# For tests: keep every file this app writes inside one folder.
_TEST = os.environ.get("MEDIA_DOWNLOAD_TEST_DIR")
if not _TEST:
    _move_old_folders()
if _TEST:
    SUPPORT, CACHE = os.path.join(_TEST, "support"), os.path.join(_TEST, "cache")

ENGINES = os.path.join(SUPPORT, "engine")
TOOLS = os.path.join(SUPPORT, "tools")
TEMP = os.path.join(CACHE, "partial")
QUEUE_FILE = os.path.join(SUPPORT, "downloads.json")
ENGINE_STAMP = os.path.join(SUPPORT, "engine-checked")

# Shared with the ytdl command, so one set of defaults serves both.
CONFIG = os.path.join(_TEST, "config.json") if _TEST else os.path.join(HOME, ".config", "ytdl", "config.json")
PUSHOVER = os.path.join(HOME, "bin", "pushover")


def downloads_dir() -> str:
    """This computer's own Downloads folder. On Windows, wherever the person has moved it."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD),
                            ("d", ctypes.c_ubyte * 8)]
            # FOLDERID_Downloads {374DE290-123F-4565-9164-39C4925E467B}
            fid = GUID(0x374DE290, 0x123F, 0x4565, (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(out)) == 0:
                path = out.value
                ctypes.windll.ole32.CoTaskMemFree(out)
                if path:
                    return path
        except Exception:  # noqa: BLE001
            pass
    return os.path.join(HOME, "Downloads")


def default_folder() -> str:
    """Downloads > Media Downloads, on the computer itself, on every system. Not a cloud folder:
    a new person's files should land where they'd look first, and a synced folder would push
    every download to their other devices. Change Folder lets anyone choose otherwise."""
    return os.path.join(downloads_dir(), "Media Downloads")


DEFAULTS = {
    "format": "best",
    "to": None,              # None means default_folder()
    "max_height": None,
    "cookies": None,         # a browser name, or None
    "notify": False,
    "auto_update": True,
    "app_parallel": 0,       # 0 = automatic, from the number of cores
    "app_per_site": 3,
    "app_fragments": 4,
    "app_sounds": True,
    "app_cover_art": True,
    "app_announce_progress": 0,   # seconds between spoken progress; 0 = off
    "app_clipboard": True,
    "app_search_site": "youtube",
    "app_signin_browser": "",     # remembered for Retry Using a Browser's Sign-in
    "app_rate_limit": "",
    "app_keep_awake": True,
    "app_stats": {},              # {"count", "bytes", "seconds", "since"}: the running tally      # don't let the computer sleep while downloading         # "", "500K", "1M", "5M", "10M"
    "app_welcomed": False,
}


def load_settings() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG) as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            cfg.update(data)
    except (OSError, ValueError):
        pass
    if not cfg.get("to"):
        cfg["to"] = default_folder()
    _loaded.clear()
    _loaded.update(json.loads(json.dumps(cfg)))
    return cfg


_loaded: dict = {}  # the settings as this app last read or wrote them


def save_settings(cfg: dict) -> None:
    """Write back only what this app changed, keeping everything else in the file as it is now.
    The `ytdl` command shares the file: writing every key the app loaded at startup undid a
    `ytdl --set` made while the app was open."""
    current = None
    for _ in range(3):
        try:
            with open(CONFIG) as fh:
                current = json.load(fh)
            break
        except FileNotFoundError:
            current = {}
            break
        except (OSError, ValueError):
            # Caught mid-write (the ytdl command saving at the same moment): saving over it
            # now would keep only this app's changes and wipe every other setting.
            time.sleep(0.2)
    if current is None:
        current = dict(_loaded)  # still unreadable: write back everything as last known
    if not isinstance(current, dict):
        current = {}
    missing = object()
    changed = {k: v for k, v in cfg.items() if _loaded.get(k, missing) != v}
    current.update(changed)
    _loaded.update(json.loads(json.dumps(changed)))
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    tmp = CONFIG + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(current, fh, indent=2)
    os.replace(tmp, CONFIG)


def auto_parallel() -> int:
    """Downloads at once when set to automatic: half the cores, two to eight.

    Downloads are mostly network-bound; the cores matter for converting, which
    ffmpeg does per file, so several files at once is what uses a big machine.
    """
    cores = os.cpu_count() or 2
    return max(2, min(8, cores // 2))


# ---------------------------------------------------------------- helper tools

SEARCH_DIRS = [] if sys.platform == "win32" else ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]


def _exe(name: str) -> str:
    return name + (".exe" if sys.platform == "win32" else "")


def _runnable(p: str) -> bool:
    return os.path.isfile(p) and os.access(p, os.X_OK)


def ffmpeg_dir() -> str | None:
    """The first folder holding both ffmpeg and ffprobe. yt-dlp is told one folder and looks
    for ffprobe only beside ffmpeg, so the two must be found together."""
    dirs = list(SEARCH_DIRS)
    on_path = shutil.which("ffmpeg")
    if on_path:
        dirs.append(os.path.dirname(on_path))
    dirs.append(TOOLS)
    for d in dirs:
        if _runnable(os.path.join(d, _exe("ffmpeg"))) and _runnable(os.path.join(d, _exe("ffprobe"))):
            return d
    return None


def find_tool(name: str) -> str | None:
    exe = _exe(name)
    if name in ("ffmpeg", "ffprobe"):
        d = ffmpeg_dir()
        return os.path.join(d, exe) if d else None
    own = os.path.join(TOOLS, exe)
    for d in SEARCH_DIRS:
        p = os.path.join(d, exe)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    found = shutil.which(name)
    if found:
        return found
    if os.path.isfile(own) and os.access(own, os.X_OK):
        return own
    return None


def js_runtime() -> tuple[str, str] | None:
    for name in ("deno", "node", "bun"):
        p = find_tool(name)
        if p:
            return name, p
    return None


def tool_report() -> dict:
    return {"ffmpeg": find_tool("ffmpeg"), "ffprobe": find_tool("ffprobe"),
            "javascript": (js_runtime() or (None, None))[1]}


def missing_tools() -> list[str]:
    r = tool_report()
    return [k for k, v in r.items() if not v]


TOOL_WORDS = {
    "ffmpeg": "ffmpeg, which converts and joins audio and video",
    "ffprobe": "ffprobe, which checks what is inside a file",
    "javascript": "deno, which YouTube needs before it hands over most videos",
}


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def fetch(url: str, timeout: float = 60, progress=None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Wavelength"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        buf = io.BytesIO()
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            buf.write(chunk)
            if progress:
                progress(buf.tell(), total)
        return buf.getvalue()


def fetch_json(url: str, timeout: float = 20):
    return json.loads(fetch(url, timeout).decode("utf-8"))


def _arch() -> str:
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64") else "x86_64"


def tool_sources() -> dict:
    """Where each missing helper comes from: {key: (zip url, file inside it)}.

    Mac: Martin Riedl's static ffmpeg builds (signed and notarized, one file
    each) and deno's own release. Windows: yt-dlp's own ffmpeg builds (the ones
    its authors test against) and deno's release. Linux: use the package manager.
    """
    arch = _arch()
    deno_arch = "aarch64" if arch == "arm64" else "x86_64"
    deno = "https://github.com/denoland/deno/releases/latest/download/deno-%s-%s.zip"
    if sys.platform == "darwin":
        ff_arch = "arm64" if arch == "arm64" else "amd64"
        ff = "https://ffmpeg.martin-riedl.de/redirect/latest/macos/%s/release/%%s.zip" % ff_arch
        return {"ffmpeg": (ff % "ffmpeg", "ffmpeg"), "ffprobe": (ff % "ffprobe", "ffprobe"),
                "javascript": (deno % (deno_arch, "apple-darwin"), "deno")}
    if sys.platform == "win32":
        ff = ("https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/"
              "ffmpeg-master-latest-win%s-gpl.zip" % ("arm64" if arch == "arm64" else "64"))
        return {"ffmpeg": (ff, "ffmpeg.exe"), "ffprobe": (ff, "ffprobe.exe"),
                "javascript": (deno % ("x86_64", "pc-windows-msvc"), "deno.exe")}
    return {}


def sha256_from(text: str) -> str | None:
    """The hash in a .sha256sum file. Deno's Mac files read "hash  name"; its Windows ones are
    PowerShell's "Algorithm : SHA256 / Hash : HASH / Path : ..." list, so look for the hash."""
    found = re.search(r"\b[0-9a-fA-F]{64}\b", text)
    return found.group(0).lower() if found else None


def get_tools(which: list[str], say=lambda s: None, progress=None) -> list[str]:
    """Fetch the named helpers into TOOLS. Returns the ones that failed, with reasons."""
    sources = tool_sources()
    failed = []
    os.makedirs(TOOLS, exist_ok=True)
    cache = {}
    for i, key in enumerate(which):
        if key not in sources:
            failed.append("%s: install it with this system's package manager." % key)
            continue
        url, member = sources[key]
        say("Getting %s, %d of %d." % (member, i + 1, len(which)))
        try:
            data = cache.get(url) or fetch(url, timeout=600, progress=progress)
            cache[url] = data  # Windows ffmpeg and ffprobe share one archive
            if "denoland" in url:
                want = sha256_from(fetch(url + ".sha256sum", 30).decode("utf-8", "replace"))
                if not want:
                    raise RuntimeError("its checksum file couldn't be read")
                if hashlib.sha256(data).hexdigest() != want:
                    raise RuntimeError("the download didn't match its checksum")
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = [nm for nm in z.namelist() if os.path.basename(nm).lower() == member.lower()]
                if not names:
                    raise RuntimeError("the archive didn't contain %s" % member)
                dest = os.path.join(TOOLS, member)
                tmp = dest + ".new"
                with z.open(names[0]) as src, open(tmp, "wb") as out:
                    shutil.copyfileobj(src, out)
            os.chmod(tmp, 0o755)
            if sys.platform == "darwin":
                subprocess.run(["xattr", "-d", "com.apple.quarantine", tmp], capture_output=True)
                sig = subprocess.run(["codesign", "--verify", "--strict", tmp], capture_output=True, text=True)
                if sig.returncode != 0:
                    os.remove(tmp)
                    raise RuntimeError("its signature didn't check out")
            ver = subprocess.run([tmp, "--version" if member.startswith("deno") else "-version"],
                                 capture_output=True, text=True, timeout=60, **hidden_window())
            if ver.returncode != 0:
                os.remove(tmp)
                raise RuntimeError("it wouldn't run on this computer")
            os.replace(tmp, dest)
        except Exception as exc:  # noqa: BLE001 - each helper reports its own failure
            failed.append("%s: %s" % (member, exc))
    return failed


def hidden_window() -> dict:
    """Popen arguments that keep a console window from flashing up on Windows."""
    if sys.platform == "win32":
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


# ---------------------------------------------------------------- the engine

def _version_key(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0"))


def installed_engines() -> list[tuple[str, str]]:
    """(version, folder) for each fetched engine, newest first."""
    out = []
    try:
        for name in os.listdir(ENGINES):
            if name.startswith("."):
                continue  # an update interrupted mid-download, never a working engine
            d = os.path.join(ENGINES, name)
            if os.path.isfile(os.path.join(d, "yt_dlp", "__init__.py")):
                out.append((name, d))
    except OSError:
        pass
    return sorted(out, key=lambda x: _version_key(x[0]), reverse=True)


def _purge_modules():
    for m in list(sys.modules):
        if m == "yt_dlp" or m.startswith("yt_dlp.") or m == "yt_dlp_ejs" or m.startswith("yt_dlp_ejs."):
            del sys.modules[m]


def load_engine():
    """Import the newest working yt-dlp. Returns the module."""
    bundled = None
    try:
        import importlib.metadata as md
        bundled = md.version("yt-dlp")
    except Exception:
        pass
    for version, folder in installed_engines():
        if bundled and _version_key(version) <= _version_key(bundled):
            break
        sys.path.insert(0, folder)
        try:
            import yt_dlp  # noqa: F401
            from yt_dlp.version import __version__ as got
            if _version_key(got) == _version_key(version):
                return yt_dlp
        except Exception:
            pass
        sys.path.remove(folder)
        _purge_modules()
    import yt_dlp
    return yt_dlp


def engine_version() -> str:
    """The version a worker would use, without importing it here."""
    try:
        import importlib.metadata as md
        bundled = md.version("yt-dlp")
    except Exception:
        bundled = "0"
    fetched = installed_engines()
    if fetched and _version_key(fetched[0][0]) > _version_key(bundled):
        return fetched[0][0]
    return bundled


def latest_engine() -> tuple[str, list] | None:
    """(version, [(wheel url, sha256), ...]) for yt-dlp and yt-dlp-ejs on PyPI, or None."""
    try:
        main = fetch_json("https://pypi.org/pypi/yt-dlp/json")
        ver = main["info"]["version"]
        wheels = []
        for f in main["urls"]:
            if f["packagetype"] == "bdist_wheel":
                wheels.append((f["url"], f["digests"]["sha256"]))
                break
        # yt-dlp pins the exact solver version it was tested with; take that one.
        pin = ""
        for req in main["info"].get("requires_dist") or []:
            m = re.match(r"yt-dlp-ejs\s*==\s*([\w.]+)", req)
            if m:
                pin = m.group(1)
        ejs = fetch_json("https://pypi.org/pypi/yt-dlp-ejs/%sjson" % (pin + "/" if pin else ""))
        for f in ejs["urls"]:
            if f["packagetype"] == "bdist_wheel":
                wheels.append((f["url"], f["digests"]["sha256"]))
                break
        return (ver, wheels) if len(wheels) == 2 else None
    except Exception:
        return None


def update_engine(say=lambda s: None) -> tuple[str, str]:
    """Fetch a newer yt-dlp if there is one. Returns (outcome, sentence).

    outcome is "updated", "current" or "failed". Never raises.
    """
    try:
        os.makedirs(SUPPORT, exist_ok=True)
        with open(ENGINE_STAMP, "w") as fh:
            fh.write(str(int(time.time())))
    except OSError:
        pass
    have = engine_version()
    latest = latest_engine()
    if not latest:
        return "failed", "Couldn't check for a newer download engine. Still on %s." % have
    ver, wheels = latest
    if _version_key(ver) <= _version_key(have):
        return "current", "The download engine is up to date (%s)." % have
    say("Updating the download engine from %s to %s." % (have, ver))
    try:
        os.makedirs(ENGINES, exist_ok=True)
        for name in os.listdir(ENGINES):
            if name.startswith(".new-"):
                shutil.rmtree(os.path.join(ENGINES, name), ignore_errors=True)
        tmp = tempfile.mkdtemp(dir=ENGINES, prefix=".new-")
    except OSError as exc:
        return "failed", "Couldn't update the download engine (%s). Still on %s." % (exc.strerror or exc, have)
    try:
        for url, sha in wheels:
            data = fetch(url, timeout=120)
            if hashlib.sha256(data).hexdigest() != sha:
                raise RuntimeError("a download didn't match PyPI's checksum")
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                z.extractall(tmp)
        # Prove it imports and reports the right version before keeping it.
        probe = ("import sys; sys.path.insert(0, sys.argv[1]); import yt_dlp, yt_dlp_ejs;"
                 "from yt_dlp.version import __version__ as v; print(v)")
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--probe-engine", tmp]
        else:
            cmd = [sys.executable, "-c", probe, tmp]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120, **hidden_window())
        if out.returncode != 0 or [_version_key(x) for x in out.stdout.strip().splitlines()[-1:]] != [_version_key(ver)]:
            raise RuntimeError("the new engine didn't start")
        final = os.path.join(ENGINES, ver)
        if os.path.exists(final):
            shutil.rmtree(final, ignore_errors=True)
        os.replace(tmp, final)
        # Keep the newest two, so a bad release can be stepped back from.
        for _, old in installed_engines()[2:]:
            shutil.rmtree(old, ignore_errors=True)
        return "updated", "Updated the download engine to %s." % ver
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(tmp, ignore_errors=True)
        return "failed", "The download engine update didn't work (%s). Still on %s." % (exc, have)


def engine_check_due(every: float = 24 * 3600) -> bool:
    try:
        with open(ENGINE_STAMP) as fh:
            return time.time() - float(fh.read().strip()) > every
    except (OSError, ValueError):
        return True


def clean_temp(older_than_days: float = 7) -> None:
    cutoff = time.time() - older_than_days * 86400
    try:
        for name in os.listdir(TEMP):
            p = os.path.join(TEMP, name)
            try:
                if os.path.getmtime(p) < cutoff:
                    shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
            except OSError:
                pass
    except OSError:
        pass
