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

    args = download_args(spec, task.get("fragments", 4)) + tool_flags(task.get("fragments", 4))
    os.makedirs(spec["dest"], exist_ok=True)
    from . import engine
    from .options import temp_dir
    os.makedirs(temp_dir(spec), exist_ok=True)
    try:
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
        for path in list(state.get("files", [])):
            folder, base = os.path.split(path)
            stem = os.path.splitext(base)[0]
            try:
                for name in sorted(os.listdir(folder)):
                    full = os.path.join(folder, name)
                    if (full not in state["files"] and name.startswith(stem)
                            and os.path.getmtime(full) >= state["started"] - 1):
                        state["files"].append(full)
                        emit("file", path=full)
            except OSError:
                pass
    emit("end", ok=(code == 0))


def do_probe(yt_dlp, task):
    """Title, length and chosen stream for one link, or the list of a playlist."""
    from .options import probe_args, tool_flags
    from . import engine, words
    spec = task["spec"]
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


TASKS = {"download": do_download, "probe": do_probe, "search": do_search, "recognise": do_recognise}


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
