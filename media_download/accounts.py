"""Your accounts: what you can open once Wavelength borrows your browser's sign-in.

No password is ever asked for or kept. The download engine reads the sign-in your browser
already has (--cookies-from-browser) each time it needs it, and sends it only to that site.
With a browser chosen in Settings, every download, search and stream uses it, so members-only,
age-checked and private things work on any of the sites; this file adds the places that only
exist when you're signed in: Liked videos, Watch Later, your subscriptions, your likes.

Checked against the engine, 2026-10-13: YouTube's feeds and LL/WL lists answer only to a real
youtube.com sign-in (a browser signed in to Google but never to YouTube itself is refused);
SoundCloud's likes, tracks and playlists work by profile name; Vimeo's likes page is gone
(HTTP 410) and Bandcamp collections aren't supported, so neither is offered.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

# key, service, what, address ({user} = the profile name asked for once), needs a profile name
COLLECTIONS = [
    ("youtube_liked", "YouTube", "Liked videos", "https://www.youtube.com/playlist?list=LL", None),
    ("youtube_later", "YouTube", "Watch Later", "https://www.youtube.com/playlist?list=WL", None),
    ("youtube_subs", "YouTube", "New from your subscriptions", "https://www.youtube.com/feed/subscriptions", None),
    ("youtube_playlists", "YouTube", "Your playlists", "https://www.youtube.com/feed/playlists", None),
    ("youtube_history", "YouTube", "Watch history", "https://www.youtube.com/feed/history", None),
    ("ytmusic_liked", "YouTube Music", "Liked music", "https://music.youtube.com/playlist?list=LM", None),
    ("soundcloud_likes", "SoundCloud", "Your likes", "https://soundcloud.com/{user}/likes", "soundcloud"),
    ("soundcloud_tracks", "SoundCloud", "Your tracks", "https://soundcloud.com/{user}/tracks", "soundcloud"),
    ("soundcloud_sets", "SoundCloud", "Your playlists", "https://soundcloud.com/{user}/sets", "soundcloud"),
]

PROFILE_WORDS = {"soundcloud": "your SoundCloud profile name (the part after soundcloud.com/ in your page's address)"}


# ---------------------------------------------------------------- where sign-ins come from
#
# A "sign-in" is a list of sources joined with SEP: browser specs ("safari", "chrome:Profile 1",
# "firefox:<path>") and WAVELENGTH, the sign-in made in Wavelength's own sign-in window. One
# browser on its own is handed to the engine as --cookies-from-browser, exactly as before;
# anything more is merged into one cookies file for that run (cookie_file below). So YouTube
# signed in through Chrome and SoundCloud through Safari both work at once.

WAVELENGTH = "wavelength"
SEP = "|"


def sources(spec: str) -> list[str]:
    return [p for p in (spec or "").split(SEP) if p]


def join(parts) -> str:
    out = []
    for p in parts:
        if p and p not in out:
            out.append(p)
    return SEP.join(out)


def chosen_browsers(cfg: dict) -> list[str]:
    """The browsers checked in Settings, Your Accounts or the tour. Settings from before 3.11
    kept one browser in app_signin; that still counts until something is checked again."""
    many = cfg.get("app_signins")
    if isinstance(many, list):
        return [b for b in many if b and b != WAVELENGTH]
    one = cfg.get("app_signin", "") or ""
    return [b for b in one.split(SEP) if b and b != WAVELENGTH]


def set_browsers(cfg: dict, browsers) -> None:
    """Keep the checked browsers. app_signin keeps the first, for anything that reads only one."""
    keep = [b for b in browsers if b and b != WAVELENGTH]
    cfg["app_signins"] = keep
    cfg["app_signin"] = keep[0] if keep else ""


def signin(cfg: dict) -> str:
    """Every sign-in Wavelength uses, as one spec: your own sign-in made in Wavelength (when
    there is one) and each checked browser. "" for none."""
    return join(([WAVELENGTH] if has_own_signin() else []) + chosen_browsers(cfg))


def signin_words(spec: str) -> str:
    """'safari' -> "Safari's sign-in"; two browsers -> "the sign-ins from Safari and Google Chrome";
    with Wavelength's own -> "your Wavelength sign-in and Safari's"."""
    parts = sources(spec)
    if not parts:
        return "no sign-in"
    own = WAVELENGTH in parts
    names = [spec_words(p) for p in parts if p != WAVELENGTH]
    if not names:
        return "your Wavelength sign-in"
    if own:
        return "your Wavelength sign-in and %s" % (names[0] + "'s" if len(names) == 1 else
                                                    "the ones from " + and_list(names))
    return names[0] + "'s sign-in" if len(names) == 1 else "the sign-ins from " + and_list(names)


def and_list(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


# ---------------------------------------------------------------- Wavelength's own sign-in
#
# The sign-in window (signin.py) keeps the sign-in it makes here, as a cookies file only this
# account can read. It's the site's own sign-in, the same thing a browser keeps; no password.

SERVICE_COOKIES = {  # a cookie that exists only once you're signed in
    "YouTube": (".youtube.com", ("SAPISID", "__Secure-3PAPISID", "LOGIN_INFO")),
    "SoundCloud": (".soundcloud.com", ("oauth_token",)),
}


def own_folder() -> str:
    from . import engine
    return os.path.join(engine.SUPPORT, "signin")


def own_file() -> str:
    return os.path.join(own_folder(), "cookies.txt")


def has_own_signin() -> bool:
    try:
        return os.path.getsize(own_file()) > 40
    except OSError:
        return False


def _private_write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        os.chmod(os.path.dirname(path), 0o700)
    except OSError:
        pass
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def netscape_text(cookies) -> str:
    """Cookies as dicts (name, value, domain, path, secure, expires: seconds, 0 = session) in the
    Netscape cookies.txt layout the engine reads."""
    lines = ["# Netscape HTTP Cookie File", "# Made by Wavelength. Your sign-in; keep it private.", ""]
    for c in cookies:
        domain = c.get("domain") or ""
        name = c.get("name") or ""
        if not domain or not name or any(ch in (str(c.get("value", "")) + name) for ch in "\t\n\r"):
            continue
        lines.append("\t".join([domain, "TRUE" if domain.startswith(".") else "FALSE", c.get("path") or "/",
                                 "TRUE" if c.get("secure") else "FALSE", str(int(c.get("expires") or 0)),
                                 name, str(c.get("value", ""))]))
    return "\n".join(lines) + "\n"


def read_netscape(path: str) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if line.startswith("#HttpOnly_"):
                    line = line[len("#HttpOnly_"):]
                elif not line or line.startswith("#"):
                    continue
                f = line.split("\t")
                if len(f) == 7:
                    out.append({"domain": f[0], "path": f[2], "secure": f[3] == "TRUE",
                                "expires": int(f[4] or 0) if f[4].isdigit() else 0, "name": f[5], "value": f[6]})
    except OSError:
        pass
    return out


def save_own(cookies) -> list[str]:
    """Keep the sign-in window's cookies (replacing what was kept). Returns the services it's
    signed in to."""
    cookies = list(cookies)
    if cookies:
        _private_write(own_file(), netscape_text(cookies))
    else:
        forget_own()
    return services_in(cookies)


def forget_own() -> None:
    try:
        os.remove(own_file())
    except OSError:
        pass


def services_in(cookies) -> list[str]:
    import time
    now = time.time()
    out = []
    for service, (domain, names) in SERVICE_COOKIES.items():
        for c in cookies:
            d = c.get("domain") or ""
            if c.get("name") in names and (d == domain or d.endswith(domain) or "." + d == domain) \
                    and (not c.get("expires") or c["expires"] > now):
                out.append(service)
                break
    return out


def own_services() -> list[str]:
    return services_in(read_netscape(own_file())) if has_own_signin() else []


# ---------------------------------------------------------------- one cookies file for a run

COOKIE_CACHE_SECONDS = 600


def needs_file(spec: str) -> bool:
    """One browser goes to the engine as it always did; anything more needs a merged file."""
    parts = sources(spec)
    return len(parts) > 1 or parts == [WAVELENGTH]


def cookie_file(spec: str, warn=lambda text: None) -> str:
    """One cookies file holding every source in `spec`, for one engine run. Built in the app's
    temporary folder with private permissions, reused for COOKIE_CACHE_SECONDS (reading several
    browsers takes a moment and asks the keychain), and copied per process, because the engine
    writes its cookies back at the end of a run. Every copy goes when Wavelength quits.

    A source that can't be read is skipped with a warning; if none can, the first problem is
    raised, so the failure reads as it always did (Full Disk Access, a locked keychain...)."""
    import hashlib
    import shutil
    import time
    from . import engine
    os.makedirs(engine.TEMP, exist_ok=True)
    key = hashlib.sha1(spec.encode("utf-8")).hexdigest()[:12]
    shared = os.path.join(engine.TEMP, "signin-%s.txt" % key)
    try:
        age = time.time() - os.path.getmtime(shared)
        fresh = age < COOKIE_CACHE_SECONDS and (not has_own_signin()
                                                or os.path.getmtime(own_file()) <= os.path.getmtime(shared))
    except OSError:
        fresh = False
    if not fresh:
        from yt_dlp.cookies import YoutubeDLCookieJar, extract_cookies_from_browser
        jar = YoutubeDLCookieJar()
        problems, read = [], 0
        for part in sources(spec):
            try:
                if part == WAVELENGTH:
                    if not has_own_signin():
                        continue
                    got = YoutubeDLCookieJar(own_file())
                    got.load()
                else:
                    name, _, profile = part.partition(":")
                    got = extract_cookies_from_browser(name, profile or None)
                for c in got:
                    jar.set_cookie(c)
                read += 1
            except Exception as exc:  # noqa: BLE001 - one unreadable browser mustn't cost the others
                problems.append(exc)
                # Plain words, never the error itself: a failed run with an unreadable-cookie error
                # in its log is retried with no sign-in at all, which would drop the ones that worked.
                warn("Left out %s this time: it couldn't be read." % signin_words(part))
        if not read and problems:
            raise problems[0]
        tmp = "%s.%d.tmp" % (shared, os.getpid())
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.close(fd)
        jar.save(tmp)
        os.chmod(tmp, 0o600)
        os.replace(tmp, shared)
    mine = os.path.join(engine.TEMP, "signin-%s-%d.txt" % (key, os.getpid()))
    shutil.copyfile(shared, mine)
    os.chmod(mine, 0o600)
    import atexit
    atexit.register(lambda: os.path.exists(mine) and os.remove(mine))
    return mine


def clear_cookie_files() -> None:
    """Every merged cookies file, gone: called when Wavelength quits and when it starts."""
    from . import engine
    try:
        for name in os.listdir(engine.TEMP):
            if name.startswith("signin-"):
                try:
                    os.remove(os.path.join(engine.TEMP, name))
                except OSError:
                    pass
    except OSError:
        pass


def profile_name(text: str, service: str) -> str:
    """'https://soundcloud.com/matthew-whitaker/likes' or '@matthew-whitaker' -> 'matthew-whitaker'."""
    text = (text or "").strip()
    m = re.search(r"%s\.com/([^/?#\s]+)" % service, text)
    if m:
        text = m.group(1)
    return text.lstrip("@").strip("/ ")


def address(key: str, cfg: dict) -> str | None:
    """The link for a collection; None while it still needs a profile name."""
    for k, _, _, url, needs in COLLECTIONS:
        if k == key:
            if needs:
                user = cfg.get("app_profile_" + needs, "")
                return url.format(user=user) if user else None
            return url
    return None


def row_words(key: str, cfg: dict) -> str:
    for k, service, what, _, needs in COLLECTIONS:
        if k == key:
            extra = ""
            if needs and not cfg.get("app_profile_" + needs):
                extra = " (asks for your profile name the first time)"
            return "%s: %s%s" % (service, what, extra)
    return key


def explain_signin(log: str, browser: str, service: str = "") -> str | None:
    """A sentence for a sign-in problem, or None if the trouble is something else."""
    low = (log or "").lower()
    name = spec_words(browser) if browser else "Your browser"
    if "could not copy chrome cookie database" in low or ("database is locked" in low):
        return ("%s is still open, so its sign-in can't be read. Close every %s window (and check it isn't "
                "running near the clock), then try again." % (name, name))
    if "unlock" in low and "decrypt" in low or "could not be decrypted" in low:
        if sys.platform == "darwin":
            # On the Mac this is the Keychain prompt answered Deny (it names "security", not Wavelength).
            return ("%s's sign-in is locked in the Keychain. Try again, and when macOS asks whether "
                    "\"security\" may use \"%s Safe Storage\", type your Mac password and choose Always Allow."
                    % (name, keychain_name(browser)))
        return ("%s keeps its sign-in locked so other apps can't read it. On Windows, newer versions of Chrome, "
                "Edge and Brave do this; Firefox doesn't. Sign in to your services in Firefox and choose it instead."
                % name)
    about_cookies = any(w in low for w in ("cookie", "binarycookies", "com.apple.safari", "full disk access"))
    if about_cookies and ("operation not permitted" in low or "permission denied" in low
                          or "full disk access" in low):
        return ("Wavelength isn't allowed to read %s's sign-in. On a Mac, add Wavelength under System "
                "Settings, Privacy & Security, Full Disk Access, then try again." % name)
    if "could not find" in low and "cookies database" in low:
        return "%s doesn't seem to be on this computer, or has never been opened. Choose another browser." % name
    if "login details are needed" in low or "playlist does not exist" in low or "sign in to confirm" in low \
            or "missing required authentication" in low:
        where = service or "that site"
        return ("%s isn't signed in to %s. Open %s in %s, sign in there, then try again; Wavelength borrows "
                "that sign-in and never asks for a password." % (name, where, where, name))
    return None


# ---------------------------------------------------------------- browsers

# Every browser the download engine can borrow a sign-in from, on every system it runs on.
# key, the name people know, Mac app name, Mac bundle id, Windows ProgId start, Linux commands.
BROWSERS = [
    ("safari", "Safari", "Safari", "com.apple.safari", "", ()),
    ("chrome", "Google Chrome", "Google Chrome", "com.google.chrome", "ChromeHTML", ("google-chrome", "google-chrome-stable")),
    ("edge", "Microsoft Edge", "Microsoft Edge", "com.microsoft.edgemac", "MSEdgeHTM", ("microsoft-edge", "microsoft-edge-stable")),
    ("firefox", "Firefox", "Firefox", "org.mozilla.firefox", "FirefoxURL", ("firefox",)),
    ("brave", "Brave", "Brave Browser", "com.brave.browser", "BraveHTML", ("brave-browser", "brave")),
    ("vivaldi", "Vivaldi", "Vivaldi", "com.vivaldi.vivaldi", "VivaldiHTM", ("vivaldi", "vivaldi-stable")),
    ("opera", "Opera", "Opera", "com.operasoftware.opera", "Opera", ("opera",)),
    ("chromium", "Chromium", "Chromium", "org.chromium.chromium", "ChromiumHTM", ("chromium", "chromium-browser")),
    ("whale", "Naver Whale", "Whale", "com.naver.whale", "WhaleHTML", ("naver-whale", "whale")),
]
NAMES = {b[0]: b[1] for b in BROWSERS}


def _chromium_dir(key: str) -> str:
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        local, roaming = os.environ.get("LOCALAPPDATA", ""), os.environ.get("APPDATA", "")
        return {"chrome": os.path.join(local, "Google", "Chrome", "User Data"),
                "chromium": os.path.join(local, "Chromium", "User Data"),
                "edge": os.path.join(local, "Microsoft", "Edge", "User Data"),
                "brave": os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data"),
                "vivaldi": os.path.join(local, "Vivaldi", "User Data"),
                "opera": os.path.join(roaming, "Opera Software", "Opera Stable"),
                "whale": os.path.join(local, "Naver", "Naver Whale", "User Data")}.get(key, "")
    if sys.platform == "darwin":
        sup = os.path.join(home, "Library", "Application Support")
        return {"chrome": os.path.join(sup, "Google", "Chrome"), "chromium": os.path.join(sup, "Chromium"),
                "edge": os.path.join(sup, "Microsoft Edge"), "brave": os.path.join(sup, "BraveSoftware", "Brave-Browser"),
                "vivaldi": os.path.join(sup, "Vivaldi"), "opera": os.path.join(sup, "com.operasoftware.Opera"),
                "whale": os.path.join(sup, "Naver", "Whale")}.get(key, "")
    conf = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return {"chrome": os.path.join(conf, "google-chrome"), "chromium": os.path.join(conf, "chromium"),
            "edge": os.path.join(conf, "microsoft-edge"), "brave": os.path.join(conf, "BraveSoftware", "Brave-Browser"),
            "vivaldi": os.path.join(conf, "vivaldi"), "opera": os.path.join(conf, "opera"),
            "whale": os.path.join(conf, "naver-whale")}.get(key, "")


def _firefox_dirs() -> list[str]:
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        return [os.path.join(os.environ.get("APPDATA", ""), "Mozilla", "Firefox", "Profiles"),
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages", "Mozilla.Firefox_n80bbvh6b1yt2",
                             "LocalCache", "Roaming", "Mozilla", "Firefox", "Profiles")]
    if sys.platform == "darwin":
        return [os.path.join(home, "Library", "Application Support", "Firefox", "Profiles")]
    conf = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return [os.path.join(conf, "mozilla", "firefox"), os.path.join(home, ".mozilla", "firefox"),
            os.path.join(home, ".var", "app", "org.mozilla.firefox", ".mozilla", "firefox"),
            os.path.join(home, "snap", "firefox", "common", ".mozilla", "firefox")]


def profiles(key: str) -> list[tuple[str, str]]:
    """A browser's profiles on this computer: (what to hand the engine, the name people see).
    Empty when the browser isn't here. One profile means there's nothing to choose."""
    if key == "safari":
        return [("", "Safari")] if sys.platform == "darwin" else []
    if key == "firefox":
        out = []
        for d in _firefox_dirs():
            try:
                for name in sorted(os.listdir(d)):
                    path = os.path.join(d, name)
                    if os.path.exists(os.path.join(path, "cookies.sqlite")):
                        out.append((path, name.split(".", 1)[-1] if "." in name else name))
            except OSError:
                continue
        return out
    base = _chromium_dir(key)
    if not base or not os.path.isdir(base):
        return []
    names = {}
    try:
        with open(os.path.join(base, "Local State"), encoding="utf-8") as fh:
            names = {d: (v.get("name") or d) for d, v in json.load(fh).get("profile", {}).get("info_cache", {}).items()}
    except (OSError, ValueError, AttributeError):
        pass
    if key == "opera":  # Opera keeps one profile in the folder itself
        return [("", "Opera")] if os.path.exists(os.path.join(base, "Cookies")) or os.path.exists(
            os.path.join(base, "Network", "Cookies")) else []
    out = []
    for d in sorted(os.listdir(base)):
        if d == "Default" or d.startswith("Profile "):
            if os.path.exists(os.path.join(base, d, "Cookies")) or os.path.exists(os.path.join(base, d, "Network", "Cookies")):
                out.append((d, names.get(d, d)))
    return out


def installed() -> list[tuple[str, str]]:
    """Every browser-and-profile on this computer, as (setting, words), always in the same order,
    Safari first (Rocco, 2026-10-16: "do not change the order"). The setting is what
    --cookies-from-browser takes: "chrome:Profile 1", "firefox:<path>"."""
    out = []
    for key, name, *_ in BROWSERS:
        found = profiles(key)
        for prof, pname in found:
            spec = key + (":" + prof if prof and len(found) > 1 else "")
            words = name if len(found) <= 1 else "%s, %s" % (name, pname)
            out.append((spec, words))
    return out


def spec_words(spec: str) -> str:
    """'chrome:Profile 1' -> 'Google Chrome, Work' (the profile's own name where known)."""
    if not spec:
        return "No browser"
    if SEP in spec:
        return and_list([spec_words(p) for p in sources(spec)])
    if spec == WAVELENGTH:
        return "Wavelength"
    key, _, prof = spec.partition(":")
    name = NAMES.get(key, key.capitalize())
    if not prof:
        return name
    for p, pname in profiles(key):
        if p == prof:
            return "%s, %s" % (name, pname)
    return "%s, %s" % (name, os.path.basename(prof.rstrip("/\\")) or prof)


def default_browser() -> str:
    """The system's default web browser, as a key, or "" if it can't be told."""
    try:
        if sys.platform == "darwin":
            import plistlib
            path = os.path.expanduser("~/Library/Preferences/com.apple.LaunchServices/"
                                      "com.apple.launchservices.secure.plist")
            with open(path, "rb") as fh:
                handlers = plistlib.load(fh).get("LSHandlers", [])
            for h in handlers:
                if h.get("LSHandlerURLScheme") in ("https", "http"):
                    bid = (h.get("LSHandlerRoleAll") or "").lower()
                    for key, _, _, mac_id, _, _ in BROWSERS:
                        if bid == mac_id:
                            return key
            return "safari"
        if sys.platform == "win32":
            import winreg
            path = "\\".join(("Software", "Microsoft", "Windows", "Shell", "Associations", "UrlAssociations",
                                "https", "UserChoice"))
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
                prog = winreg.QueryValueEx(k, "ProgId")[0]
            for key, _, _, _, win_id, _ in BROWSERS:
                if win_id and prog.startswith(win_id):
                    return key
            return ""
        out = subprocess.run(["xdg-settings", "get", "default-web-browser"], capture_output=True, text=True,
                             timeout=5).stdout.lower()
        for key, _, _, _, _, cmds in BROWSERS:
            if any(c in out for c in cmds) or key in out:
                return key
    except Exception:  # noqa: BLE001 - a guess, never a requirement
        pass
    return ""


def open_in(spec: str, url: str) -> None:
    """Open a page in that browser specifically (so the sign-in lands where it will be read)."""
    import webbrowser
    key, _, prof = (spec or "").partition(":")
    entry = next((b for b in BROWSERS if b[0] == key), None)
    # The chosen profile, not whichever was used last: signing in to the wrong one is how a
    # sign-in check fails for no visible reason.
    extra = []
    if prof and key == "firefox":
        extra = ["-profile", prof]
    elif prof and key not in ("safari", "opera"):
        extra = ["--profile-directory=%s" % prof]
    try:
        if entry and sys.platform == "darwin":
            if extra:  # -n: a running browser only takes these from a fresh launch
                subprocess.Popen(["open", "-na", entry[2], "--args"] + extra + [url])
            else:
                subprocess.Popen(["open", "-a", entry[2], url])
            return
        if entry and sys.platform == "win32":
            exe = _windows_exe(key)
            if exe:
                subprocess.Popen([exe] + extra + [url])
                return
        if entry and entry[5]:
            import shutil
            for c in entry[5]:
                if shutil.which(c):
                    subprocess.Popen([c] + extra + [url])
                    return
    except OSError:
        pass
    webbrowser.open(url)


def _windows_exe(key: str) -> str:
    parts = {"chrome": ("Google", "Chrome", "Application", "chrome.exe"),
             "edge": ("Microsoft", "Edge", "Application", "msedge.exe"),
             "firefox": ("Mozilla Firefox", "firefox.exe"),
             "brave": ("BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
             "vivaldi": ("Vivaldi", "Application", "vivaldi.exe"), "opera": ("Programs", "Opera", "launcher.exe"),
             "chromium": ("Chromium", "Application", "chrome.exe"),
             "whale": ("Naver", "Naver Whale", "Application", "whale.exe")}.get(key)
    rel = os.path.join(*parts) if parts else ""
    if not rel:
        return ""
    for root in (os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", ""),
                 os.environ.get("LOCALAPPDATA", "")):
        path = os.path.join(root, rel)
        if root and os.path.exists(path):
            return path
    return ""


def keychain_name(spec: str) -> str:
    """The name a Chromium browser's keychain item goes by: "<this> Safe Storage"."""
    key = (spec or "").split(":", 1)[0]
    return {"chrome": "Chrome", "edge": "Microsoft Edge", "brave": "Brave", "vivaldi": "Vivaldi",
            "opera": "Opera", "chromium": "Chromium", "whale": "Whale"}.get(key, NAMES.get(key, key))


def permission_steps(spec: str) -> list[str]:
    """What this system needs before Wavelength can read this browser's sign-in, step by
    step; empty when nothing is needed."""
    key = (spec or "").split(":", 1)[0]
    name = NAMES.get(key, key)
    if sys.platform == "darwin" and key == "safari":
        return ["Safari keeps its sign-in in a protected place, so macOS asks you to allow Wavelength in.",
                "Press Open System Settings below. It opens Privacy & Security, Full Disk Access.",
                "Find Wavelength in the list and turn it on. If it isn't listed, press the Add button, "
                "choose Applications, then Wavelength.",
                "macOS may ask for your password, and may ask to quit Wavelength. If it does, choose Later. "
                "I notice by myself the moment it's on, so there's nothing to press after that."]
    if sys.platform == "darwin" and key != "firefox":
        return ["%s locks its sign-in with a key in your keychain." % name,
                "When you press Check Again, macOS asks whether \"security\" may use \"%s Safe Storage\". "
                "That's the Mac's own keychain tool, reading it for Wavelength. Type your Mac's password, then "
                "choose Always Allow, so it doesn't ask every time." % keychain_name(key)]
    if sys.platform == "win32" and key != "firefox":
        return ["On Windows, %s has to be closed completely while Wavelength reads its sign-in: close every "
                "%s window, and check it isn't still running near the clock." % (name, name),
                "Newer versions of %s on Windows lock their sign-in so no other app can read it. If Check Again "
                "says so, Firefox works: sign in to your services in Firefox and choose it here." % name]
    if sys.platform.startswith("linux") and key != "firefox":
        return ["%s may keep its sign-in locked with your desktop's keyring. If the keyring asks, allow it." % name]
    return []


SAFARI_COOKIES = os.path.expanduser("~/Library/Containers/com.apple.Safari/Data/Library/Cookies/"
                                    "Cookies.binarycookies")


def safari_readable() -> bool:
    """Can this app read Safari's sign-in right now? Cheap enough to ask every second or two:
    macOS answers a file open at once, Full Disk Access or not."""
    old = os.path.expanduser("~/Library/Cookies/Cookies.binarycookies")  # before Safari's container
    for path in (SAFARI_COOKIES, old):
        if not os.path.exists(path) and path != SAFARI_COOKIES:
            continue
        try:
            with open(path, "rb") as f:
                f.read(4)
            return True
        except OSError:
            continue
    return False


def settings_page_url(spec: str) -> str:
    """Where the Open System Settings button goes for this browser on this system, or ""."""
    key = (spec or "").split(":", 1)[0]
    if sys.platform == "darwin" and key == "safari":
        return "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
    return ""
