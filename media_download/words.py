"""Everything the app says, in one place.

The rule: a sentence a listener can stop after. Status first, then the name,
because a long title gets cut off at the end of a row and the answer must
arrive before that. No "(s)" plurals, no symbols read as punctuation.
"""
from __future__ import annotations

import re
import urllib.parse


def n(count: int, word: str, plural: str | None = None) -> str:
    return "%d %s" % (count, word if count == 1 else (plural or word + "s"))


def duration(seconds) -> str:
    """'3 minutes 20 seconds', '1 hour 4 minutes'. Empty when unknown."""
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return ""
    if total < 0:
        return ""
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return n(hours, "hour") + (" " + n(minutes, "minute") if minutes else "")
    if minutes:
        return n(minutes, "minute") + (" " + n(secs, "second") if secs else "")
    return n(secs, "second")


def short_time_left(seconds) -> str:
    """Coarse on purpose: 'about 3 minutes left', never a ticking second count."""
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return ""
    if s < 0:
        return ""
    if s < 10:
        return "a few seconds left"
    if s < 60:
        return "under a minute left"
    if s < 3600:
        return "about %s left" % n(int(round(s / 60)), "minute")
    return "about %s left" % duration(round(s / 300) * 300)


def size(num_bytes) -> str:
    try:
        b = float(num_bytes)
    except (TypeError, ValueError):
        return ""
    if b <= 0:
        return ""
    for unit, scale in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if b >= scale:
            value = b / scale
            return ("%.1f %s" % (value, unit)).replace(".0 ", " ")
    return "%d bytes" % b


def speed(bps) -> str:
    s = size(bps)
    return s + " a second" if s else ""


def clock(seconds) -> str:
    """For yt-dlp: H:MM:SS."""
    total = int(seconds)
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return "%d:%02d:%02d" % (h, m, s)


def parse_time(text) -> float | None:
    """'90', '1:30', '1:02:03' or '1m30s' to seconds. None when empty or unreadable."""
    if text is None:
        return None
    t = str(text).strip().lower()
    if not t:
        return None
    m = re.fullmatch(r"(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+(?:\.\d+)?)s)?", t)
    if m and any(m.groups()):
        h, mi, s = m.groups()
        return int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0)
    parts = t.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if len(nums) > 3 or any(x < 0 for x in nums):
        return None
    total = 0.0
    for x in nums:
        total = total * 60 + x
    return total


def site_name(url: str) -> str:
    """'youtube.com' from any link, for rows and per-site limits."""
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return ""
    host = host.lower()
    for prefix in ("www.", "m.", "music.", "mobile."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    if host in ("youtu.be", "youtube-nocookie.com"):
        return "youtube.com"
    parts = host.split(".")
    # Keep two labels, or three for the likes of bbc.co.uk.
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in ("co", "com", "org", "net", "ac", "gov"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


def links_in(text: str) -> list[str]:
    """Every http(s) link in some pasted or dropped text, in order, once each."""
    seen, out = set(), []
    for m in URL_RE.finditer(text or ""):
        url = m.group(0).rstrip(".,;)]}>")
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def looks_like_link(text: str) -> bool:
    t = (text or "").strip()
    return bool(URL_RE.fullmatch(t)) or (" " not in t and "." in t and "/" in t)


FORMAT_LABELS = [
    ("best", "Best audio, as the site sends it"),
    ("mp3", "MP3 audio"),
    ("m4a", "M4A audio (AAC)"),
    ("opus", "Opus audio"),
    ("wav", "WAV audio, uncompressed"),
    ("flac", "FLAC audio, lossless"),
    ("video", "Video (MP4)"),
]
FORMAT_SHORT = {"best": "best audio", "mp3": "MP3", "m4a": "M4A", "opus": "Opus",
                "wav": "WAV", "flac": "FLAC", "video": "video"}

HEIGHTS = [(0, "Best that plays everywhere"), (-1, "Highest available, any codec"), (2160, "4K (2160)"),
           (1440, "1440"), (1080, "1080"), (720, "720"), (480, "480"), (360, "360")]


def describe_format(fmt: dict) -> str:
    """One plain sentence for a stream, the way you would say it out loud."""
    acodec, vcodec = fmt.get("acodec"), fmt.get("vcodec")
    has_audio = acodec and acodec != "none"
    has_video = vcodec and vcodec != "none"
    sz = size(fmt.get("filesize") or fmt.get("filesize_approx"))
    if has_video and has_audio:
        what = "Video %sp with sound, %s" % (fmt.get("height") or "?", (vcodec or "").split(".")[0])
    elif has_video:
        what = "Video %sp, %s, sound added separately" % (fmt.get("height") or "?", (vcodec or "").split(".")[0])
    else:
        abr = fmt.get("abr")
        what = "Audio, %s%s" % ((acodec or "unknown").split(".")[0],
                                ", %d kbps" % round(abr) if abr else "")
    return what + (", about %s" % sz if sz else "")


def choosable(info: dict) -> list[dict]:
    """Streams worth offering: the best audio per codec and one video per height.

    A normal video reports forty-odd formats; reading forty near-identical
    lines aloud is useless, so they collapse to the ones that are a real choice.
    """
    best_audio, best_video = {}, {}
    for fmt in info.get("formats") or []:
        acodec, vcodec = fmt.get("acodec"), fmt.get("vcodec")
        if fmt.get("format_note") == "storyboard" or fmt.get("ext") == "mhtml":
            continue
        if vcodec and vcodec != "none":
            key = fmt.get("height") or 0
            if key and (key not in best_video or (fmt.get("tbr") or 0) > (best_video[key].get("tbr") or 0)):
                best_video[key] = fmt
        elif acodec and acodec != "none":
            key = acodec.split(".")[0]
            if key not in best_audio or (fmt.get("abr") or 0) > (best_audio[key].get("abr") or 0):
                best_audio[key] = fmt
    audio = sorted(best_audio.values(), key=lambda f: -(f.get("abr") or 0))
    video = sorted(best_video.values(), key=lambda f: -(f.get("height") or 0))
    return audio + video


def is_rate_limited(text: str) -> bool:
    t = (text or "").lower()
    return "http error 429" in t or "too many requests" in t or "rate-limit" in t or "rate limit" in t


def is_transient(text: str) -> bool:
    """Network trouble that's likely gone in a minute: worth trying again by itself."""
    t = (text or "").lower()
    return any(k in t for k in ("timed out", "timeout", "connection reset", "connection aborted",
                                "temporarily unavailable", "network is unreachable", "incompleteread",
                                "remote end closed", "name resolution", "nodename nor servname",
                                "eof occurred", "connection refused", "broken pipe")) \
        or bool(re.search(r"http error 5\d\d", t))


def clock_time(ts: float) -> str:
    """'2:15 AM', for saying when something will happen."""
    import time as _t
    return _t.strftime("%I:%M %p", _t.localtime(ts)).lstrip("0")


def worth_updating_for(text: str) -> bool:
    """Would a newer yt-dlp plausibly fix this failure? Private, removed and
    members-only fail the same on every version, so updating for them is waste."""
    lowered = (text or "").lower()
    hopeless = ("private", "unavailable", "removed", "members-only", "join this channel",
                "does not exist", "no space left", "not a valid url", "unsupported url",
                "geo", "copyright", "stopped by you")
    return not any(word in lowered for word in hopeless)


def explain_failure(text: str, cookies_used: bool = False, site: str | None = None) -> str:
    """The useful sentence, not yt-dlp's error, whenever we recognise it.

    `site` keeps the wording honest: blaming YouTube for a Bandcamp failure is
    both wrong and confusing.
    """
    lowered = (text or "").lower()
    who = site or "The site"
    if "confirm you" in lowered or "not a bot" in lowered or "http error 403" in lowered \
            or "sign in to confirm" in lowered:
        if cookies_used:
            return ("%s refused it even with your browser's sign-in. Try a different browser "
                    "in More Options." % who)
        return ("%s wants a signed-in browser for this one. Choose Retry Using a Browser's Sign-in in the "
                "Downloads menu." % who)
    if "http error 429" in lowered or "too many requests" in lowered:
        return ("%s says too many requests. Wait a few minutes, then Retry. Fewer downloads at once "
                "in Settings helps too." % who)
    if "drm" in lowered:
        return ("That's protected by DRM, the copy protection that Spotify, Apple Music, Netflix and others use, "
                "so it can't be downloaded. Nothing to fix on your side.")
    if cookies_used and ("operation not permitted" in lowered or "full disk access" in lowered) \
            and "safari" in lowered:
        return ("Reading Safari's sign-in needs Full Disk Access for Media Download: System Settings, Privacy "
                "and Security, Full Disk Access. Or choose another browser.")
    if "badoptions:" in lowered or "no such option" in lowered:
        return ("The extra yt-dlp options in More Options weren't understood. Check them, or clear them "
                "and Retry.")
    if ("logged-in" in lowered or "login required" in lowered or "provide account credentials" in lowered
            or "sign in to view" in lowered or "requires authentication" in lowered):
        return ("%s wants you signed in for this one. Choose Retry Using a Browser's Sign-in in the Downloads "
                "menu." % who)
    m = re.search(r"http error (5\d\d)", lowered)
    if m:
        return ("%s had a problem on its end (error %s). Retry in a minute usually works."
                % (site or "The site", m.group(1)))
    if "unsupported url" in lowered or "no video formats" in lowered or "not a valid url" in lowered:
        return "That link isn't one the download engine knows how to read."
    if "private video" in lowered or "is private" in lowered:
        return "That one is private."
    if "members-only" in lowered or "join this channel" in lowered:
        return "That one is for members only."
    if "geo" in lowered and "restrict" in lowered or "not available in your country" in lowered:
        return "That is blocked in this country."
    if "unavailable" in lowered or "removed" in lowered or "does not exist" in lowered or "404" in lowered:
        return "That isn't available. It may have been removed, made private, or blocked here."
    if "no space left" in lowered:
        return "The disk is full."
    if "ffmpeg" in lowered and ("not found" in lowered or "not installed" in lowered):
        return "The converter (ffmpeg) is missing. Choose Get Helper Tools in the Help menu."
    if "timed out" in lowered or "connection" in lowered and ("refused" in lowered or "reset" in lowered) \
            or "network is unreachable" in lowered or "nodename nor servname" in lowered:
        return "Couldn't reach %s. Check the internet connection, then Retry." % (site or "the site")
    if "permission denied" in lowered or "operation not permitted" in lowered:
        return "Couldn't write to the download folder. Choose another folder in Settings."
    last = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    detail = last[-1] if last else ""
    detail = re.sub(r"^ERROR:\s*", "", detail)
    detail = re.sub(r"^\[[^\]]+\]\s*[\w-]+:\s*", "", detail)
    detail = re.sub(r"\s*\(caused by .*\)\s*$", "", detail)
    return "That failed." + (" The engine said: " + detail if detail else "")


# ---------------------------------------------------------------- rows

STATE_WORDS = {
    "waiting": "Waiting",
    "looking": "Looking up",
    "downloading": "Downloading",
    "converting": "Converting",
    "done": "Done",
    "failed": "Failed",
    "stopped": "Stopped",
    "skipped": "Already here",
    "waiting_choice": "Needs your choice",
}


def row_text(job) -> str:
    """One list row, status first: 'Downloading, 45 percent, about 2 minutes left: Title'."""
    title = job.title or job.url
    st = job.state
    if st == "downloading":
        bits = ["Downloading"]
        if job.part_count > 1:
            bits.append("part %d of %d" % (job.part, job.part_count))
        if job.percent is not None:
            bits.append("%d percent" % int(job.percent))
        tl = short_time_left(job.eta)
        if tl:
            bits.append(tl)
        return ", ".join(bits) + ": " + title
    if st == "converting":
        return "%s: %s" % (job.stage or "Converting", title)
    if st == "done":
        extra = []
        if len(job.files) > 1:
            extra.append(n(len(job.files), "file"))
        elif job.bytes_done:
            extra.append(size(job.bytes_done))
        return "Done: " + title + (", " + ", ".join(extra) if extra else "")
    if st == "skipped":
        return "Already here: " + title
    if st == "failed":
        return "Failed: %s. %s" % (title, job.reason or "")
    if st in ("waiting", "looking") and job.not_before:
        import time as _t
        left = job.not_before - _t.time()
        when = "in a moment" if left < 5 else ("in about %s" % duration(round(left / 5) * 5) if left < 120
                                              else "at %s" % clock_time(job.not_before))
        return "Waiting to try again %s: %s" % (when, title)
    if st == "stopped":
        return "Stopped: " + title
    return "%s: %s" % (STATE_WORDS.get(st, st.capitalize()), title)


def pretty_folder(path: str) -> str:
    """'iCloud Drive > Media Downloads' rather than a Library path nobody recognises."""
    import os
    home = os.path.expanduser("~")
    icloud = os.path.join(home, "Library", "Mobile Documents", "com~apple~CloudDocs")
    if path.startswith(icloud):
        return "iCloud Drive" + path[len(icloud):].replace(os.sep, " > ")
    if path.startswith(home + os.sep):
        return "your home folder" + path[len(home):].replace(os.sep, " > ")
    return path


def details_text(job) -> str:
    """Everything known about one download, one fact per line."""
    lines = [job.title or job.url]
    lines.append("Status: " + row_text(job).split(": ", 1)[0] + ".")
    if job.state == "failed" and job.reason:
        lines.append(job.reason)
    if job.state in ("waiting", "looking") and job.wait_reason:
        lines.append(job.wait_reason)
    if job.note:
        lines.append(job.note)
    if job.uploader:
        lines.append("By: " + job.uploader)
    if job.length:
        lines.append("Length: " + duration(job.length))
    lines.append("Format: " + job.format_words())
    if job.site:
        lines.append("Site: " + job.site)
    if job.state == "downloading":
        if job.bytes_total:
            lines.append("Received %s of %s." % (size(job.bytes_done) or "0 bytes", size(job.bytes_total)))
        sp = speed(job.speed)
        if sp:
            lines.append("Speed: " + sp + ".")
    for f in job.files[:20]:
        lines.append("Saved as: " + f)
    if len(job.files) > 20:
        lines.append("And %s more." % n(len(job.files) - 20, "file"))
    if not job.files:
        lines.append("Saving to: " + pretty_folder(job.folder()))
    lines.append("Link: " + job.url)
    if job.state == "failed" and job.log_tail:
        lines.append("")
        lines.append("What the download engine said:")
        lines += job.log_tail[-6:]
    return "\n".join(lines)


# ---------------------------------------------------------------- transcripts

_TIME = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d+)\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d+)")


def srt_to_text(srt: str, title: str = "", gap: float = 2.5, para_words: int = 70) -> str:
    """Captions to readable paragraphs.

    YouTube's automatic captions scroll: each line appears in two or three cues
    in a row, so read straight through every line comes out two or three times,
    like a stutter. A line is kept only when it isn't one of the last few kept.
    A new paragraph starts at a pause longer than `gap` seconds, or after about
    `para_words` words, so the text can be moved through by paragraph.
    """
    out_paras, para, recent = [], [], []
    last_end, words_in_para = None, 0
    for block in re.split(r"\n\s*\n", srt.replace("\r", "")):
        lines = block.strip().split("\n")
        start = end = None
        text_lines = []
        for ln in lines:
            m = _TIME.search(ln)
            if m:
                g = [int(x) for x in m.groups()]
                start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
            elif ln.strip().isdigit() and not text_lines and start is None:
                continue
            elif start is not None:
                clean = re.sub(r"<[^>]+>", "", ln).strip()
                clean = re.sub(r"\{\\[^}]*\}", "", clean)  # styling codes
                if clean:
                    text_lines.append(clean)
        if start is None:
            continue
        new = [t for t in text_lines if t not in recent]
        if not new:
            last_end = max(last_end or 0, end or 0)
            continue
        if para and (last_end is not None and start - last_end > gap or words_in_para >= para_words):
            out_paras.append(" ".join(para))
            para, words_in_para = [], 0
        for t in new:
            para.append(t)
            words_in_para += len(t.split())
            recent.append(t)
            del recent[:-4]
        last_end = end
    if para:
        out_paras.append(" ".join(para))
    head = [title, ""] if title else []
    return "\n".join(head + ["\n\n".join(out_paras)]).strip() + "\n"


def caption_cues(text: str) -> list:
    """Captions (SRT or WebVTT) as [(start, end, line)], each line once, for showing under a video.

    Rolling automatic captions repeat each line in two or three cues; a cue keeps only the
    lines that are new, the same rule as srt_to_text.
    """
    cues, recent = [], []
    for block in re.split(r"\n\s*\n", (text or "").replace("\r", "")):
        start = end = None
        lines = []
        for ln in block.strip().split("\n"):
            m = _TIME.search(ln)
            if m:
                g = [int(x) for x in m.groups()]
                start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
            elif start is not None:
                clean = re.sub(r"<[^>]+>", "", ln).strip()
                if clean:
                    lines.append(clean)
        if start is None:
            continue
        new = [t for t in lines if t not in recent]
        for t in new:
            recent.append(t)
            del recent[:-4]
        if new:
            cues.append((start, end, " ".join(new)))
    return cues


def cue_at(cues: list, t: float) -> str:
    """The caption showing at t seconds: the last cue that has started, until the next one."""
    lo, hi, best = 0, len(cues) - 1, ""
    while lo <= hi:
        mid = (lo + hi) // 2
        if cues[mid][0] <= t:
            best = cues[mid][2] if t <= cues[mid][1] + 3 else ""
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def clock_words(seconds) -> str:
    """'1:23' or '1:02:03', for showing; duration() is for saying."""
    try:
        total = max(0, int(seconds))
    except (TypeError, ValueError):
        return "0:00"
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%d:%02d" % (m, s)
