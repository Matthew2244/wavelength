"""What has been downloaded where, so the same thing isn't downloaded into the same folder twice
(Matthew, 2026-11-20: "never download something already in the chosen folder").

A download is the same when it's the same source (the site's own id, or the same link) saved the
same way (format, exact stream, section) into the same folder, and its file is still there. A file
that's been moved or deleted doesn't count: then it downloads again, as anyone would expect.
Download Again Anyway sets the job's `force`, which skips this check.
"""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.parse

from . import engine

PATH = os.path.join(engine.SUPPORT, "downloaded.json")
KEEP = 5000
_lock = threading.Lock()


def source_key(url: str) -> str:
    """A link's source, the same however it's written: YouTube's video id under any of its
    addresses, otherwise the link without tracking bits."""
    try:
        u = urllib.parse.urlparse(url.strip())
    except ValueError:
        return url
    host = (u.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    q = urllib.parse.parse_qs(u.query)
    if host in ("youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com"):
        if "v" in q:
            return "youtube:" + q["v"][0]
        m = re.match(r"/(?:shorts|live|embed)/([\w-]{6,})", u.path)
        if m:
            return "youtube:" + m.group(1)
    if host == "youtu.be" and len(u.path) > 1:
        return "youtube:" + u.path.strip("/").split("/")[0]
    keep = [(k, v) for k, vs in sorted(q.items()) for v in vs
            if not k.lower().startswith(("utm_", "si", "feature", "fbclid", "ref"))]
    return "%s%s%s" % (host, u.path.rstrip("/"), ("?" + urllib.parse.urlencode(keep)) if keep else "")


def _keys(job) -> set:
    """Every way this job's source can be named: by its link, and by the site's id once known."""
    keys = {source_key(job.url)}
    sid = getattr(job, "source_id", "")
    if sid:
        keys.add(sid.lower())
    return keys


def _how(job) -> tuple:
    folder = os.path.normcase(os.path.abspath(os.path.join(job.dest or "", job.subfolder or "")))
    return (folder, job.kind or "", job.format_id or "", job.start or "", job.end or "",
            int(job.max_height or 0))


def _load() -> list:
    try:
        with open(PATH) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def remember(job, files: list) -> None:
    """A finished download: its source, how it was saved, and its files."""
    files = [f for f in files if f and os.path.exists(f)]
    if not files or getattr(job, "task", "download") != "download":
        return
    entry = {"keys": sorted(_keys(job)), "how": list(_how(job)), "files": files, "title": job.title or ""}
    with _lock:
        data = [e for e in _load() if not (set(e.get("keys", [])) & set(entry["keys"])
                                            and e.get("how") == entry["how"])]
        data.append(entry)
        data = data[-KEEP:]
        try:
            os.makedirs(os.path.dirname(PATH), exist_ok=True)
            tmp = PATH + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(data, fh)
            os.replace(tmp, PATH)
        except OSError:
            pass


def already(job) -> list:
    """The files of the same download already in this folder, or [] when there are none."""
    if getattr(job, "force", False) or getattr(job, "task", "download") != "download":
        return []
    keys, how = _keys(job), list(_how(job))
    with _lock:
        data = _load()
    for e in reversed(data):
        if e.get("how") == how and set(e.get("keys", [])) & keys:
            there = [f for f in e.get("files", []) if os.path.exists(f)]
            if there:
                return there
    return []
