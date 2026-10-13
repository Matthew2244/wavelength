"""The process that does one piece of work and reports it as JSON lines.

Started as `<app> --worker` (or `python -m media_download --worker`), given
one task as JSON on stdin. Every event is one line on stdout:

    {"ev": "info", "title": ..., "duration": ..., "uploader": ...}
    {"ev": "progress", "done": bytes, "total": bytes, "speed": ..., "eta": ..., "part": 1, "parts": 2}
    {"ev": "stage", "text": "Converting"}
    {"ev": "file", "path": ...}
    {"ev": "log", "text": ...}            warnings and errors, for explaining a failure
    {"ev": "end", "ok": true}             always last

A separate process for each download is what lets several run on several
cores at once, keeps one crash from taking the window with it, and makes Stop
immediate: the app ends the process group, ffmpeg included.
"""
from __future__ import annotations

import json
import os
import sys
import time

_out = sys.stdout


def emit(ev: str, **data) -> None:
    data["ev"] = ev
    _out.write(json.dumps(data) + "\n")
    _out.flush()


class Logger:
    def __init__(self):
        self.tail = []

    def _keep(self, msg):
        self.tail.append(msg)
        del self.tail[:-30]

    def debug(self, msg):
        if "has already been downloaded" in msg or "already been recorded" in msg:
            emit("already")
        if msg.startswith("[download] Destination:") or msg.startswith("[Merger]") \
                or msg.startswith("[ExtractAudio]") or msg.startswith("[SplitChapters]"):
            pass

    def info(self, msg):
        self.debug(msg)

    def warning(self, msg):
        self._keep(msg)
        emit("log", text=msg)

    def error(self, msg):
        self._keep(msg)
        emit("log", text=msg)


STAGE_WORDS = {
    "Merger": "Joining sound and picture",
    "FFmpegMerger": "Joining sound and picture",
    "ExtractAudio": "Converting",
    "FFmpegExtractAudio": "Converting",
    "FFmpegVideoConvertor": "Converting",
    "FFmpegVideoRemuxer": "Converting",
    "Metadata": "Adding title and artist",
    "FFmpegMetadata": "Adding title and artist",
    "EmbedThumbnail": "Adding cover art",
    "SplitChapters": "Splitting into chapters",
    "FFmpegSplitChapters": "Splitting into chapters",
    "FFmpegSubtitlesConvertor": "Converting subtitles",
    "ModifyChapters": "Cutting",
}


def _make_ydl(yt_dlp, args, logger, extra=None):
    parsed = yt_dlp.parse_options(args + ["--", "https://example.invalid/"])
    opts = dict(parsed.ydl_opts)
    opts.update({"logger": logger, "noprogress": True, "quiet": True, "no_warnings": False,
                 "color": {"stdout": "no_color", "stderr": "no_color"}})
    if extra:
        opts.update(extra)
    return yt_dlp.YoutubeDL(opts)


def do_download(yt_dlp, task):
    from .options import download_args, tool_flags
    spec = task["spec"]
    logger = Logger()
    state = {"part": 1, "parts": 1, "fmt": None, "last": 0.0, "files": [], "started": time.time()}

    def hook(d):
        info = d.get("info_dict") or {}
        req = info.get("requested_formats") or []
        if req:
            state["parts"] = len(req)
            fid = info.get("format_id")
            ids = [f.get("format_id") for f in req]
            if fid in ids:
                state["part"] = ids.index(fid) + 1
        if d.get("status") == "downloading":
            now = time.monotonic()
            if now - state["last"] < 0.5:
                return
            state["last"] = now
            emit("progress", done=d.get("downloaded_bytes") or 0,
                 total=d.get("total_bytes") or d.get("total_bytes_estimate") or 0,
                 speed=d.get("speed"), eta=d.get("eta"), part=state["part"], parts=state["parts"],
                 title=info.get("title"))
        elif d.get("status") == "finished":
            emit("progress", done=d.get("total_bytes") or d.get("downloaded_bytes") or 0,
                 total=d.get("total_bytes") or d.get("downloaded_bytes") or 0, speed=None, eta=0,
                 part=state["part"], parts=state["parts"], title=info.get("title"))

    def pp_hook(d):
        if d.get("status") == "started":
            text = STAGE_WORDS.get(d.get("postprocessor") or "")
            if text and text != state.get("stage"):
                state["stage"] = text
                emit("stage", text=text)

    def post_hook(path):
        path = os.path.abspath(path)
        state.setdefault("files", []).append(path)
        emit("file", path=path)

    os.makedirs(spec["dest"], exist_ok=True)
    from . import engine
    from .options import temp_dir
    os.makedirs(temp_dir(spec), exist_ok=True)
    try:
        # Inside the try: an unclosed quote in the extra options is the person's to fix, and must
        # read as that, not as a failure worth updating the engine and retrying for.
        args = download_args(spec, task.get("fragments", 4)) + tool_flags(task.get("fragments", 4))
        ydl = _make_ydl(yt_dlp, args, logger, {"progress_hooks": [hook], "postprocessor_hooks": [pp_hook],
                                                "post_hooks": [post_hook]})
    except (Exception, SystemExit) as exc:  # bad raw flags under More Options; argparse exits
        emit("log", text="BADOPTIONS: %s" % (exc if str(exc) not in ("2", "") else spec.get("extra", "")))
        emit("end", ok=False)
        return
    with ydl:
        info_file = spec.get("info_file")
        # Stream links from most sites last hours; past that, look the link up again.
        fresh = info_file and os.path.exists(info_file) and time.time() - (spec.get("info_time") or 0) < 3 * 3600
        try:
            if fresh:
                code = ydl.download_with_info_file(info_file)
            else:
                code = ydl.download([spec["url"]])
        except yt_dlp.utils.DownloadError:
            code = 1
        except Exception as exc:  # noqa: BLE001
            logger.error("ERROR: %s" % exc)
            code = 1
    if code == 0:
        # Chapter files and subtitles are made beside the main file but never reported by
        # yt-dlp's final hook, so the row and Show in Finder knew only the whole file.
        extra = []
        for path in list(state.get("files", [])):
            folder, base = os.path.split(path)
            stem = os.path.splitext(base)[0]
            try:
                for name in sorted(os.listdir(folder)):
                    full = os.path.join(folder, name)
                    if (full not in state["files"] and full not in extra and name.startswith(stem)
                            and os.path.getmtime(full) >= state["started"] - 1):
                        extra.append(full)
            except OSError:
                pass
        if spec.get("transcript"):
            extra = make_transcripts(extra, keep_srt=bool(spec.get("subtitles")))
        for full in extra:
            emit("file", path=full)
    emit("end", ok=(code == 0))


def make_transcripts(files, keep_srt):
    """A readable .txt beside each caption file. The .srt goes unless subtitles were asked for."""
    from . import words
    out = []
    srts = [f for f in files if f.lower().endswith(".srt")]
    for f in files:
        if f not in srts:
            out.append(f)
    if not srts:
        emit("log", text="NOTRANSCRIPT")
    for srt in srts:
        base = os.path.basename(srt)[:-4]
        title = base.rsplit(".", 1)[0] if "." in base else base  # "Song.en" -> "Song"
        txt = os.path.join(os.path.dirname(srt), title + " - transcript.txt")
        try:
            with open(srt, encoding="utf-8", errors="replace") as fh:
                text = words.srt_to_text(fh.read(), title)
            with open(txt, "w", encoding="utf-8") as fh:
                fh.write(text)
            out.append(txt)
        except OSError:
            keep_srt = True
        if keep_srt:
            out.append(srt)
        else:
            try:
                os.remove(srt)
            except OSError:
                pass
    return out


def podcast_feed(url: str) -> str | None:
    """An Apple Podcasts show page, turned into the show's own RSS feed.

    The engine reads single Apple Podcasts episodes but not a show page, and a show page is
    what people copy. Apple's public directory (the iTunes lookup API, no account) gives the
    feed, which the engine lists like any playlist.
    """
    import re
    import urllib.request
    m = re.match(r"https?://podcasts\.apple\.com/.*?/id(\d+)(?:[/?#]|$)", url)
    if not m or re.search(r"[?&]i=\d+", url):
        return None
    try:
        from .engine import fetch_json
        data = fetch_json("https://itunes.apple.com/lookup?id=%s" % m.group(1))
        return (data.get("results") or [{}])[0].get("feedUrl")
    except Exception:  # noqa: BLE001
        return None


def do_probe(yt_dlp, task):
    """Title, length and chosen stream for one link, or the list of a playlist."""
    from .options import probe_args, tool_flags
    from . import engine, words
    spec = dict(task["spec"])
    spec["url"] = podcast_feed(spec["url"]) or spec["url"]
    logger = Logger()
    try:
        ydl = _make_ydl(yt_dlp, probe_args(spec) + tool_flags(), logger)
        with ydl:
            info = ydl.extract_info(spec["url"], download=False)
    except Exception as exc:  # noqa: BLE001
        logger.error(str(exc))
        info = None
    if not info:
        emit("end", ok=False)
        return
    if info.get("_type") in ("playlist", "multi_video") or info.get("entries") is not None:
        entries = []
        os.makedirs(engine.TEMP, exist_ok=True)
        stamp = "%d-%d" % (os.getpid(), int(time.time() * 1000))
        for k, e in enumerate(info.get("entries") or []):
            if not e:
                continue
            url = e.get("url") or e.get("webpage_url")
            if e.get("ie_key") == "Youtube" and e.get("id"):
                url = "https://www.youtube.com/watch?v=%s" % e["id"]
            if not url:
                continue
            item = {"url": url, "title": e.get("title") or url, "duration": e.get("duration"),
                    "uploader": e.get("uploader") or e.get("channel") or ""}
            if e.get("_type", "video") == "video" and (e.get("formats") or e.get("ext")):
                # Some sites (archive.org) list each item complete, with its file. Keep that,
                # so the download needn't fetch the whole file again just to identify it,
                # which under load earned "HTTP Error 500".
                try:
                    path = os.path.join(engine.TEMP, "info-%s-%d.json" % (stamp, k))
                    with open(path, "w") as fh:
                        json.dump(ydl.sanitize_info(e), fh)
                    item["info_file"] = path
                except Exception:  # noqa: BLE001
                    pass
            entries.append(item)
        emit("playlist", title=info.get("title") or "Playlist", entries=entries,
             uploader=info.get("uploader") or info.get("channel") or "",
             site=info.get("extractor_key") or "")
        emit("end", ok=True)
        return
    path = ""
    try:
        os.makedirs(engine.TEMP, exist_ok=True)
        path = os.path.join(engine.TEMP, "info-%d-%d.json" % (os.getpid(), int(time.time() * 1000)))
        with open(path, "w") as fh:
            json.dump(ydl.sanitize_info(info), fh)
    except Exception:  # noqa: BLE001 - the info file is only a shortcut
        path = ""
    chosen = info.get("requested_formats") or ([info] if info.get("format_id") else [])
    est = sum((f.get("filesize") or f.get("filesize_approx") or 0) for f in chosen)
    emit("info", title=info.get("title") or "", duration=info.get("duration") or 0,
         uploader=info.get("uploader") or info.get("channel") or info.get("artist") or "",
         site=info.get("extractor_key") or "", info_file=path, size=est,
         formats=[{"id": str(f.get("format_id")), "words": words.describe_format(f),
                   "audio_only": not (f.get("vcodec") and f.get("vcodec") != "none")}
                  for f in words.choosable(info)])
    emit("end", ok=True)


def do_search(yt_dlp, task):
    from .options import SEARCH_SITES, tool_flags
    logger = Logger()
    prefix = dict((k, p) for k, _, p in SEARCH_SITES).get(task.get("site"), "ytsearch")
    count = int(task.get("count", 25))
    if prefix.startswith("http"):
        import urllib.parse
        query = prefix % urllib.parse.quote_plus(task["query"])
    else:
        query = "%s%d:%s" % (prefix, count, task["query"])
    try:
        ydl = _make_ydl(yt_dlp, ["--flat-playlist", "--playlist-items", "1-%d" % count] + tool_flags(), logger)
        with ydl:
            info = ydl.extract_info(query, download=False)
    except Exception as exc:  # noqa: BLE001
        logger.error(str(exc))
        info = None
    if not info:
        emit("end", ok=False)
        return
    results = []
    for e in info.get("entries") or []:
        if not e:
            continue
        url = e.get("url") or e.get("webpage_url")
        if e.get("ie_key") == "Youtube" and e.get("id"):
            url = "https://www.youtube.com/watch?v=%s" % e["id"]
        if url:
            results.append({"url": url, "title": e.get("title") or url, "duration": e.get("duration"),
                            "uploader": e.get("uploader") or e.get("channel") or ""})
    emit("results", results=results)
    emit("end", ok=True)


def do_stream(yt_dlp, task):
    """A link this computer's built-in player can play, without downloading.

    The Mac's player (AVFoundation) plays HLS playlists with picture and sound together,
    and M4A, MP3, MP4 and Opus files; Windows' plays MP4 and M4A. YouTube no longer offers
    ready-combined MP4, so video on the Mac takes its HLS playlist, and audio takes the
    M4A stream. Captions come along when there are English ones.
    """
    from .options import tool_flags
    from . import words
    logger = Logger()
    want = task.get("want", "audio")
    mac = sys.platform == "darwin"
    if want == "video":
        # Anything with picture, falling back to sound: a video-only HLS stream is fine on the
        # Mac because its master playlist (below) carries the sound; an audio-only site gives audio.
        fmt = ("best[vcodec!=none][acodec!=none][protocol^=m3u8]/bv*[protocol^=m3u8]/"
               "best[ext=mp4][vcodec!=none][acodec!=none]/best[vcodec!=none][acodec!=none]/" if mac else
               "best[ext=mp4][vcodec^=avc1][acodec!=none]/best[ext=mp4][vcodec!=none][acodec!=none]/")
        fmt += "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio"
    else:
        # On the Mac, HLS first: YouTube's direct M4A is a segmented DASH file the Mac's player
        # often never starts (and reads at twice its length); its HLS audio plays every time.
        fmt = ("bestaudio[protocol^=m3u8]/" if mac else "") + \
            "bestaudio[ext=m4a][protocol!*=dash]/bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio[ext=mp3]/" \
            "best[ext=mp4][acodec!=none]" + ("/bestaudio[acodec=opus][ext!=webm]/bestaudio/best" if mac else "/best")
    if task.get("format"):
        fmt = task["format"]  # an exact stream, such as a video's own described track
    args = ["--no-playlist", "-f", fmt] + tool_flags()
    if task.get("cookies"):
        args += ["--cookies-from-browser", task["cookies"]]
    try:
        ydl = _make_ydl(yt_dlp, args, logger)
        with ydl:
            # First, cheaply: is this a list? Resolving a podcast feed as one item walked every
            # episode first (three minutes, then nothing). A list goes to the player's list path.
            info = ydl.extract_info(task["url"], download=False, process=False)
            if info and info.get("_type") in ("playlist", "multi_video"):
                emit("log", text="ISLIST")
                emit("end", ok=False)
                return
            info = ydl.process_ie_result(info, download=False) if info else None
    except Exception as exc:  # noqa: BLE001
        logger.error(str(exc))
        info = None
    if not info:
        emit("end", ok=False)
        return
    play_url = info.get("url")
    has_video = (info.get("vcodec") or "none") != "none"
    has_audio = (info.get("acodec") or "none") != "none"
    proto = info.get("protocol") or ""
    if has_video and not has_audio:
        # Picture only: the HLS master playlist has the sound too (the Mac plays it). Otherwise
        # there's nothing this player can do with a silent picture stream.
        manifest = info.get("manifest_url") or next(
            (f.get("manifest_url") for f in info.get("formats") or [] if f.get("manifest_url")), None)
        play_url = manifest if (mac and manifest and proto.startswith("m3u8")) else None
    got = "video" if has_video else "audio"
    if not play_url:
        emit("log", text="NOPLAYABLE")
        emit("end", ok=False)
        return
    headers = info.get("http_headers") or {}
    cues = []
    subs = dict(info.get("automatic_captions") or {})
    subs.update(info.get("subtitles") or {})  # real subtitles win over automatic ones
    for lang in ("en", "en-US", "en-GB", "en-orig"):
        tracks = subs.get(lang) or []
        vtt = [t for t in tracks if t.get("ext") in ("vtt", "srt")]
        if vtt:
            try:
                from .engine import fetch
                cues = words.caption_cues(fetch(vtt[0]["url"], timeout=30).decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001 - captions are a bonus
                cues = []
            break
    emit("stream", url=play_url, title=info.get("title") or "", uploader=info.get("uploader") or
         info.get("channel") or "", duration=info.get("duration") or 0, is_live=bool(info.get("is_live")),
         page=info.get("webpage_url") or task["url"], want=got,
         odd_headers=sorted(k for k in headers if k.lower() not in ("user-agent", "accept", "accept-language",
                                                                    "sec-fetch-mode")),
         cues=cues[:20000])
    emit("end", ok=True)


def do_find_description(yt_dlp, task):
    """What audio description exists for a link: its own described track, published described
    versions, and whether one can be made here."""
    from .options import tool_flags
    from . import describe
    logger = Logger()
    info = None
    try:
        ydl = _make_ydl(yt_dlp, ["--no-playlist"] + tool_flags(), logger)
        with ydl:
            info = ydl.extract_info(task["url"], download=False)
    except Exception as exc:  # noqa: BLE001
        logger.error(str(exc))
    title = (info or {}).get("title") or task.get("title") or ""
    track = describe.descriptive_track(info or {})
    emit("about", title=title, duration=(info or {}).get("duration") or 0,
         track=str(track.get("format_id")) if track else "",
         track_words=(track.get("format_note") or "described track") if track else "",
         has_video=any((f.get("vcodec") or "none") != "none" for f in (info or {}).get("formats") or []),
         can_make=bool(describe.claude_path()))
    found = []
    if title:
        try:
            ydl = _make_ydl(yt_dlp, ["--flat-playlist"] + tool_flags(), logger)
            with ydl:
                res = ydl.extract_info("ytsearch10:" + describe.search_query(title), download=False)
            for e in (res or {}).get("entries") or []:
                if e and describe.looks_described(e.get("title") or "") and e.get("id"):
                    found.append({"url": "https://www.youtube.com/watch?v=%s" % e["id"], "title": e.get("title"),
                                  "duration": e.get("duration"), "uploader": e.get("uploader") or e.get("channel")})
        except Exception as exc:  # noqa: BLE001
            logger.warning(str(exc))
    emit("candidates", items=describe.rank_candidates(title, found))
    emit("end", ok=info is not None)


def do_describe(yt_dlp, task):
    """Make audio description: a small copy of the picture, frames at shot changes, Claude."""
    import shutil
    from .options import tool_flags
    from . import describe, engine
    spec = task["spec"]
    claude = describe.claude_path()
    ffmpeg = engine.find_tool("ffmpeg")
    if not claude or not ffmpeg:
        emit("log", text="NODESCRIBE: %s" % ("the Claude command-line tool" if not claude else "ffmpeg"))
        emit("end", ok=False)
        return
    work = describe.new_workdir()
    try:
        video = spec.get("source_path") if spec.get("source_path") and os.path.exists(spec["source_path"]) else None
        title = spec.get("title") or ""
        if not video:
            emit("stage", text="Getting a small copy of the picture")
            logger = Logger()
            args = ["-f", "bv*[height<=480][height>=200]/b[height<=480]/bv*/b", "-P", work, "-o", "video.%(ext)s",
                    "--no-playlist"] + tool_flags()
            got = {}
            ydl = _make_ydl(yt_dlp, args, logger, {"post_hooks": [lambda p: got.__setitem__("path", p)]})
            with ydl:
                info = ydl.extract_info(spec["url"], download=True)
            title = title or (info or {}).get("title") or "Video"
            video = got.get("path") or next((os.path.join(work, f) for f in os.listdir(work)
                                             if f.startswith("video.")), None)
            if not video:
                emit("log", text="ERROR: couldn't get the picture to describe")
                emit("end", ok=False)
                return
        emit("stage", text="Finding the moments to describe")
        frames = describe.sample_frames(video, os.path.join(work, "frames"), ffmpeg)
        if not frames:
            emit("log", text="ERROR: no picture to describe (is it audio only?)")
            emit("end", ok=False)
            return

        def progress(done, total):
            emit("stage", text="Describing, %d of %d moments" % (min(done + describe.BATCH, total), total)
                 if done < total else "Saving the description")
            emit("progress", done=done, total=total, speed=None, eta=None, part=1, parts=1)
        rows = describe.describe_frames(frames, os.path.join(work, "frames"), title, claude, progress)
        if not rows:
            emit("log", text="ERROR: Claude didn't return any description")
            emit("end", ok=False)
            return
        folder = os.path.join(spec["dest"], spec["subfolder"]) if spec.get("subfolder") else spec["dest"]
        for path in describe.write_outputs(rows, folder, title):
            emit("file", path=path)
        emit("described", url=spec["url"], count=len(rows))
        emit("end", ok=True)
    except Exception as exc:  # noqa: BLE001
        emit("log", text="ERROR: %s" % exc)
        emit("end", ok=False)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def do_impersonate_check(yt_dlp, task):
    """How many browsers the engine can pass itself off as. Zero means curl_cffi is missing."""
    try:
        ydl = yt_dlp.YoutubeDL({"quiet": True})
        n = len(list(ydl._get_available_impersonate_targets()))
    except Exception:  # noqa: BLE001
        n = 0
    emit("impersonate", targets=n)
    emit("end", ok=True)


def do_recognise(yt_dlp, task):
    """Which extractor would take this link, offline. Skips the generic one, which takes anything."""
    from yt_dlp.extractor import gen_extractor_classes
    for ie in gen_extractor_classes():
        if ie.IE_NAME.lower().startswith("generic"):
            continue
        try:
            if ie.suitable(task["url"]):
                emit("recognised", name=ie.IE_NAME)
                break
        except Exception:  # noqa: BLE001
            pass
    emit("end", ok=True)


TASKS = {"download": do_download, "probe": do_probe, "search": do_search, "recognise": do_recognise,
         "impersonate": do_impersonate_check, "stream": do_stream, "find_description": do_find_description,
         "describe": do_describe}


def main() -> int:
    global _out
    # yt-dlp and ffmpeg write to stdout in places; only our JSON may go there.
    _out = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    try:
        task = json.loads(sys.stdin.readline())
    except ValueError:
        emit("log", text="The worker was given nothing it could read.")
        emit("end", ok=False)
        return 2
    try:
        from . import engine
        yt_dlp = engine.load_engine()
        emit("engine", version=yt_dlp.version.__version__)
        TASKS[task["task"]](yt_dlp, task)
    except KeyboardInterrupt:
        emit("end", ok=False, stopped=True)
        return 130
    except Exception as exc:  # noqa: BLE001
        import traceback
        emit("log", text="ERROR: %s" % exc)
        emit("log", text=traceback.format_exc()[-800:])
        emit("end", ok=False)
        return 1
    return 0
