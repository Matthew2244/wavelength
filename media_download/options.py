"""Turn a download's settings into yt-dlp's own command-line flags.

Written as flags rather than as an options dictionary on purpose: yt-dlp's
parse_options() then does the translation it does for its own command line,
so this app and `ytdl` mean exactly the same thing by every choice, and any
raw flag a person adds under More Options works without special handling.
"""
from __future__ import annotations

import os
import shlex
import sys

from . import engine, words

AUDIO_KINDS = ("best", "mp3", "m4a", "opus", "wav", "flac")
VIDEO_KINDS = ("video", "video_only")
# "Best audio" keeps a file that already plays everywhere and makes AAC (.m4a) of anything else:
# a bare .opus or .webm opens in almost nothing on a Mac (Rocco, 2026-10-16: "nothing can open it").
PLAYS_EVERYWHERE = "m4a>m4a/mp3>mp3/aac>aac/flac>flac/wav>wav/m4a"
COVER_OK = ("best", "mp3", "m4a", "opus", "flac")


def selector(spec: dict) -> list[str]:
    """The format selector, shared by the lookup and the download, so a lookup
    can never describe a different stream from the one that arrives."""
    if spec.get("format_id"):
        return ["-f", spec["format_id"]]
    kind = spec.get("kind", "best")
    if kind == "video":
        cap = int(spec.get("max_height") or 0)
        if cap < 0:  # highest available, whatever the codec
            return ["-f", "bv*+ba/b"]
        if cap == 0 or cap <= 1080:
            # H.264 first: it plays everywhere. YouTube's AV1 and VP9 streams don't play in
            # QuickTime on many Macs, nor on older TVs and phones.
            lim = "[height<=%d]" % cap if cap else ""
            return ["-f", "bv*[vcodec^=avc1]%s+ba[ext=m4a]/bv*%s[ext=mp4]+ba[ext=m4a]/bv*%s+ba/b%s/b"
                    % (lim, lim, lim, lim)]
        return ["-f", "bv*[height<=%d]+ba/b[height<=%d]/b" % (cap, cap)]
    if kind == "video_only":
        cap = int(spec.get("max_height") or 0)
        if cap < 0:
            return ["-f", "bv*/b"]
        lim = "[height<=%d]" % cap if cap else ""
        return ["-f", "bv*[vcodec^=avc1]%s/bv*%s[ext=mp4]/bv*%s/b%s/b" % (lim, lim, lim, lim)]
    if kind in ("m4a", "best"):
        # The site's own AAC first, so "best" seldom has to convert at all.
        return ["-f", "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/best"]
    if kind == "opus":
        return ["-f", "bestaudio[acodec=opus]/bestaudio/best"]
    return ["-f", "bestaudio/best"]


_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {"LPT%d" % i for i in range(1, 10)}


def _safe_folder(name: str) -> str:
    bad = '<>:"/\\|?*' if sys.platform == "win32" else "/:"
    cleaned = "".join("_" if c in bad or ord(c) < 32 else c for c in name)
    # Trimmed after cutting too: a cut can leave a trailing space or dot, which Windows drops
    # silently, so the folder made and the folder looked for would differ.
    cleaned = cleaned[:120].strip().strip(".").strip()
    if sys.platform == "win32" and cleaned.split(".")[0].upper() in _RESERVED:
        cleaned += "_"  # "CON" or "nul.txt" can't be a name on Windows at all
    return cleaned or "Playlist"


def safe_folder(name: str) -> str:
    """The folder name a playlist really gets, for anything that needs to find it."""
    return _safe_folder(name)


def name_budget(spec: dict) -> int:
    """How long the name under the download folder may be. Windows still stops most programs,
    ffmpeg included, at 260 characters for a whole path, and the temporary copy lives deeper
    than the finished one, with a fragment suffix on top."""
    if sys.platform != "win32":
        return 180
    deepest = max(len(spec.get("dest", "")), len(temp_dir(spec)))
    return max(60, min(150, 260 - deepest - 40))


def temp_dir(spec: dict) -> str:
    return os.path.join(engine.TEMP, spec.get("tmp") or "shared")


def output_template(spec: dict) -> str:
    if spec.get("name"):
        # A "/" in a name would make a folder; ":" is a separator on older Mac paths.
        return _safe_folder(spec["name"]).replace("%", "%%") + ".%(ext)s"
    stem = "%(title)s.%(ext)s"
    if spec.get("item_title"):
        # A playlist's listing often names items better than the item's own page does
        # (archive.org lists "Turning"; the file itself is "gd1977-05-08d01t01").
        stem = _safe_folder(spec["item_title"])[:150].replace("%", "%%") + ".%(ext)s"
    if spec.get("index"):
        stem = "%03d - " % int(spec["index"]) + stem
    if spec.get("subfolder"):
        return _safe_folder(spec["subfolder"]).replace("%", "%%") + "/" + stem
    return stem


def tool_flags(fragments: int = 4) -> list[str]:
    flags = ["--concurrent-fragments", str(max(1, int(fragments))),
             # YouTube's lists and search results then carry a date (from "2 years ago"), so every
             # result can say when it was uploaded.
             "--extractor-args", "youtubetab:approximate_date"]
    ff = engine.find_tool("ffmpeg")
    if ff:
        flags += ["--ffmpeg-location", os.path.dirname(ff)]
    js = engine.js_runtime()
    if js:
        flags += ["--js-runtimes", "%s:%s" % js]
    return flags


def download_args(spec: dict, fragments: int = 4) -> list[str]:
    # Each download gets its own temporary folder. A shared one let two downloads of the same
    # video (as MP3 and as FLAC, say) overwrite each other's partial files (found in training).
    args = ["-P", "home:" + spec["dest"], "-P", "temp:" + temp_dir(spec),
            "--trim-filenames", str(name_budget(spec)),
            "-o", output_template(spec),
            "--no-playlist", "--no-mtime",  # the file's date is the day you got it, so it sorts to the top
            "--retries", "10", "--fragment-retries", "10"]
    args += selector(spec)
    kind = spec.get("kind", "best")
    fid = spec.get("format_id")
    if fid:
        # A stream named exactly is taken as it comes: converting it would undo
        # the reason for naming it.
        if spec.get("format_audio_only"):
            args += ["-x", "--audio-format", "best", "--embed-metadata"]
        else:
            args += ["--merge-output-format", "mp4", "--embed-metadata"]
    elif kind == "video":
        args += ["--merge-output-format", "mp4", "--embed-metadata"]
    elif kind == "video_only":
        args += ["--remux-video", "mp4", "--embed-metadata"]
    elif kind == "mp3":
        args += ["-x", "--audio-format", "mp3", "--audio-quality", "320K", "--embed-metadata"]
    elif kind == "wav":
        args += ["-x", "--audio-format", "wav"]
    elif kind in ("flac", "m4a", "opus"):
        args += ["-x", "--audio-format", kind, "--embed-metadata"]
    else:
        args += ["-x", "--audio-format", PLAYS_EVERYWHERE, "--audio-quality", "192K", "--embed-metadata"]

    if spec.get("cover_art", True) and not fid and kind in COVER_OK:
        args += ["--embed-thumbnail"]

    start, end = words.parse_time(spec.get("start")), words.parse_time(spec.get("end"))
    if start is not None or end is not None:
        args += ["--download-sections",
                 "*%s-%s" % (words.clock(start or 0), words.clock(end) if end is not None else "inf"),
                 "--force-keyframes-at-cuts"]
    if spec.get("chapters"):
        folder = (_safe_folder(spec["subfolder"]).replace("%", "%%") + "/") if spec.get("subfolder") else ""
        args += ["--split-chapters", "-o",
                 "chapter:" + folder + "%(title)s - %(section_number)02d %(section_title)s.%(ext)s"]
    if spec.get("subtitles") or spec.get("transcript"):
        # "en.*" matches every auto-translated track and earns an HTTP 429.
        args += ["--write-auto-subs", "--write-subs", "--sub-langs", "en,en-orig,en-US,en-GB",
                 "--convert-subs", "srt"]
    args += cookie_args(spec.get("cookies"))
    if spec.get("rate_limit"):
        args += ["--limit-rate", spec["rate_limit"]]
    if spec.get("extra"):
        args += split_extra(spec["extra"])
    return args


def split_extra(text: str) -> list[str]:
    """The raw yt-dlp options typed under More Options, split the way the person's own system
    would. On Windows a backslash is a path separator, not an escape: POSIX splitting turned
    C:\\tools into C:tools. Raises ValueError for an unclosed quote."""
    if sys.platform == "win32":
        parts = shlex.split(text, posix=False)
        return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]
    return shlex.split(text)


def probe_args(spec: dict) -> list[str]:
    args = ["--yes-playlist", "--flat-playlist"]
    args += selector(spec)
    args += cookie_args(spec.get("cookies"))
    return args


def cookie_args(spec, warn=None) -> list[str]:
    """The engine's flags for a sign-in (accounts.signin): one browser as --cookies-from-browser,
    as always; several, or Wavelength's own, as one merged --cookies file for this run."""
    from . import accounts
    if not spec:
        return []
    if not accounts.needs_file(spec):
        return ["--cookies-from-browser", accounts.sources(spec)[0]]
    if warn is None:
        def warn(text):
            from .worker import emit
            emit("log", text="WARNING: " + text)
    try:
        return ["--cookies", accounts.cookie_file(spec, warn)]
    except Exception:  # noqa: BLE001
        # Nothing could be read: hand the engine the first browser, so it fails the way it always
        # has, with the words the rest of the app knows (Full Disk Access, a locked keychain...).
        browsers = [p for p in accounts.sources(spec) if p != accounts.WAVELENGTH]
        return ["--cookies-from-browser", browsers[0]] if browsers else []


SEARCH_SITES = [("youtube", "YouTube", "ytsearch"),
                ("soundcloud", "SoundCloud", "scsearch"),
                # yt-dlp has no "ytmsearch:"; its YouTube Music search page, songs section, works.
                ("youtube_music", "YouTube Music", "https://music.youtube.com/search?q=%s#songs")]
