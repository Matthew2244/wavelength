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
    if kind == "m4a":
        return ["-f", "bestaudio[ext=m4a]/bestaudio/best"]
    if kind == "opus":
        return ["-f", "bestaudio[acodec=opus]/bestaudio/best"]
    return ["-f", "bestaudio/best"]


def _safe_folder(name: str) -> str:
    bad = '<>:"/\\|?*' if sys.platform == "win32" else "/:"
    cleaned = "".join("_" if c in bad or ord(c) < 32 else c for c in name).strip().strip(".")
    return cleaned[:120] or "Playlist"


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
    flags = ["--concurrent-fragments", str(max(1, int(fragments)))]
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
            "--trim-filenames", "150" if sys.platform == "win32" else "180",
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
    elif kind == "mp3":
        args += ["-x", "--audio-format", "mp3", "--audio-quality", "320K", "--embed-metadata"]
    elif kind == "wav":
        args += ["-x", "--audio-format", "wav"]
    elif kind in ("flac", "m4a", "opus"):
        args += ["-x", "--audio-format", kind, "--embed-metadata"]
    else:
        args += ["-x", "--audio-format", "best", "--embed-metadata"]

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
    if spec.get("cookies"):
        args += ["--cookies-from-browser", spec["cookies"]]
    if spec.get("rate_limit"):
        args += ["--limit-rate", spec["rate_limit"]]
    if spec.get("extra"):
        args += shlex.split(spec["extra"])
    return args


def probe_args(spec: dict) -> list[str]:
    args = ["--yes-playlist", "--flat-playlist"]
    args += selector(spec)
    if spec.get("cookies"):
        args += ["--cookies-from-browser", spec["cookies"]]
    return args


SEARCH_SITES = [("youtube", "YouTube", "ytsearch"), ("soundcloud", "SoundCloud", "scsearch"),
                # yt-dlp has no "ytmsearch:"; its YouTube Music search page, songs section, works.
                ("youtube_music", "YouTube Music", "https://music.youtube.com/search?q=%s#songs")]
