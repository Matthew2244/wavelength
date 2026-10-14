"""Audio description: find it, or make it.

In order of how far each can be trusted:
1. A described audio track on the video itself (real description; rare, and checked first).
2. A separate described version someone has published (where description actually lives on
   YouTube). Shown as candidates; nothing is assumed to match on title alone.
3. Made here, only when there's nothing else: frames at shot changes, read in order by the
   Claude command-line tool so it has continuity. Labelled as machine-made and unchecked
   wherever it's saved, because a confident wrong description is worse than an honest gap.

Made descriptions are saved beside the downloads as "<title> - audio description.srt" (and a
.txt to read), and the player reads them at their moments.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from . import engine

MIN_GAP = 4.0     # seconds between described moments
STILL_EVERY = 12  # also a moment this often in a long unchanging shot
BATCH = 10        # frames per Claude call: enough for continuity
VERSIONS_PAGE = 50  # search results read per look for described versions; Look Further reads more
SUFFIX = " - audio description"

HEADER = ("This audio description was made automatically by reading frames from the video. "
          "No person wrote or checked it. Treat it as a rough guide.")

PROMPT = """You are writing audio description for a blind listener.

Read these frames from "%s", in order. Each is an image file in the current folder,
labelled with its time in seconds.
%s

Write one description per frame. Rules:
- Present tense. Describe only what is visible.
- Carry continuity: name a person or place once, then refer back ("she", "the same room").
- Do not describe what is said or heard.
- No speculation about meaning, mood or intent. No "appears to", no "seems".
- Read any text on screen that matters (titles, signs, captions burned into the picture).
- If a frame adds nothing over the previous one, write exactly: SKIP
- Under 20 words each: it has to be read in a gap.

Reply with ONLY a JSON array, one object per frame, in order:
[{"time": <seconds>, "text": "<description or SKIP>"}]
No markdown fence, no commentary."""


def claude_path() -> str | None:
    """The Claude command-line tool, also when the app was opened from Finder with a short PATH."""
    home = os.path.expanduser("~")
    for p in (shutil.which("claude"), os.path.join(home, ".local", "bin", "claude"),
              os.path.join(home, ".local", "bin", "claude.exe"),
              os.path.join(home, ".claude", "local", "claude"), "/opt/homebrew/bin/claude",
              "/usr/local/bin/claude", os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd")):
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def descriptive_track(info: dict) -> dict | None:
    """An audio track on this video marked as description, by any of the names sites use."""
    for fmt in info.get("formats") or []:
        if fmt.get("acodec") in (None, "none"):
            continue
        hay = " ".join(str(fmt.get(k) or "") for k in ("format_note", "format", "language"))
        track = fmt.get("audio_track")
        if isinstance(track, dict):
            hay += " " + " ".join(str(v) for v in track.values())
        if re.search(r"descri|\bAD\b|audio.?desc", hay, re.I):
            return fmt
    return None


def looks_described(title: str) -> bool:
    return bool(re.search(r"audio.?desc|described|\bAD\b|\(AD\)|with description", title or "", re.I))


_COMMON = {"official", "trailer", "teaser", "video", "audio", "described", "description", "descriptive",
           "music", "with", "from", "the", "and", "for", "full", "episode", "clip", "version", "film", "movie"}


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9']{3,}", (text or "").lower()) if w not in _COMMON}


def rank_candidates(title: str, found: list) -> list:
    """Only candidates that share a distinctive word with the original, most shared first.

    A search for "Wicked trailer audio described" also returns a theatre's described welcome
    video; a listener shouldn't have to wade through those."""
    want = _words(title)
    scored = [(len(want & _words(c.get("title"))), c) for c in found]
    return [c for score, c in sorted(scored, key=lambda x: -x[0]) if score > 0]


def search_query(title: str) -> str:
    return "%s audio described" % re.sub(r"\s*[|(\[].*$", "", title or "")[:80]


def srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def write_outputs(rows: list, folder: str, title: str, stem: str | None = None) -> list[str]:
    """The .srt the player reads and a .txt anyone can read. Both say they're machine-made.
    `stem` names them after a video file (beside it, as for_item expects); else the title does."""
    from .options import _safe_folder
    base = os.path.join(folder, (stem if stem else _safe_folder(title)[:150]) + SUFFIX)
    os.makedirs(folder, exist_ok=True)
    blocks = ["1\n%s --> %s\n[%s]" % (srt_time(0), srt_time(0.5), HEADER)] if not rows else []
    for i, row in enumerate(rows):
        end = rows[i + 1]["time"] if i + 1 < len(rows) else row["time"] + 5
        blocks.append("%d\n%s --> %s\n%s" % (i + 1, srt_time(row["time"]), srt_time(max(row["time"] + 1, end)),
                                             row["text"]))
    with open(base + ".srt", "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(blocks) + "\n")
    from .words import clock_words
    with open(base + ".txt", "w", encoding="utf-8") as fh:
        fh.write("%s: audio description\n\n%s\n\n" % (title, HEADER))
        for row in rows:
            fh.write("%s  %s\n" % (clock_words(row["time"]), row["text"]))
    return [base + ".srt", base + ".txt"]


def sample_frames(video: str, folder: str, ffmpeg: str) -> list[tuple[str, float]]:
    """Frames where the picture changes, plus one in any long unchanging shot."""
    os.makedirs(folder, exist_ok=True)
    out = subprocess.run([ffmpeg, "-hide_banner", "-i", video, "-vf",
                          "select='eq(n\\,0)+gt(scene\\,0.25)+gte(t-prev_selected_t\\,%d)',scale=768:-2,showinfo"
                          % STILL_EVERY, "-vsync", "vfr", "-q:v", "4", os.path.join(folder, "f%04d.jpg")],
                         capture_output=True, encoding="utf-8", errors="replace", timeout=6 * 3600,
                         **engine.hidden_window())
    times = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", out.stderr or "")]
    frames = sorted(f for f in os.listdir(folder) if f.endswith(".jpg"))
    paired = list(zip(frames, times + [0.0] * len(frames)))[:len(frames)]
    kept, last = [], -MIN_GAP
    for name, when in paired:
        if when - last >= MIN_GAP:
            kept.append((name, when))
            last = when
    return kept  # every moment, however long the video: no cap (Matthew, 2026-10-13)


class ClaudeSignedOut(Exception):
    """Claude answered that it isn't signed in: every other batch would fail the same way."""


def _signed_out(text: str) -> bool:
    low = (text or "").lower()
    return any(w in low for w in ("/login", "not logged in", "please log in", "invalid api key",
                                  "authentication_error", "oauth token has expired", "credit balance is too low"))


def describe_frames(frames, folder, title, claude, progress=lambda done, total: None,
                    gaps: list | None = None) -> list[dict]:
    """Describe the frames in batches. A batch that fails is skipped and its stretch of time goes
    into `gaps` as (from, to) seconds, so the finished description can say where it's silent."""
    rows, carried = [], ""
    gaps = gaps if gaps is not None else []
    for start in range(0, len(frames), BATCH):
        chunk = frames[start:start + BATCH]
        progress(start, len(frames))
        listing = "\n".join("%s  (%.1f s)" % (name, when) for name, when in chunk)
        if carried:
            listing += "\n\nFor continuity, the description so far ended: %s" % carried
        try:
            # The prompt goes in on stdin: on Windows `claude` may be a .cmd wrapper, and cmd.exe
            # would cut a many-line argument at its first line break.
            out = subprocess.run([claude, "-p", "--allowedTools", "Read", "--output-format", "text"],
                                 input=PROMPT % (title, listing), cwd=folder, capture_output=True,
                                 encoding="utf-8", errors="replace", timeout=900, **engine.hidden_window())
        except (OSError, subprocess.TimeoutExpired):
            gaps.append((chunk[0][1], chunk[-1][1]))
            continue
        if out.returncode != 0 and _signed_out((out.stdout or "") + (out.stderr or "")):
            raise ClaudeSignedOut()
        body = re.sub(r"^```(?:json)?|```$", "", (out.stdout or "").strip(), flags=re.M).strip()
        m = re.search(r"\[.*\]", body, re.S)
        if out.returncode != 0 or not m:
            gaps.append((chunk[0][1], chunk[-1][1]))
            continue
        try:
            got = json.loads(m.group(0))
        except ValueError:
            gaps.append((chunk[0][1], chunk[-1][1]))
            continue
        for row, (_, when) in zip(got, chunk):
            text = str(row.get("text", "")).strip()
            if text and text.upper() != "SKIP":
                rows.append({"time": float(when), "text": text})
                carried = text
    progress(len(frames), len(frames))
    rows.sort(key=lambda r: r["time"])
    return rows


def new_workdir() -> str:
    from .engine import TEMP
    os.makedirs(TEMP, exist_ok=True)
    return tempfile.mkdtemp(prefix="describe-", dir=TEMP)


# Where a made description lives for a link that was never downloaded, so the player finds
# it when the link is played.

def _registry() -> str:
    from .engine import SUPPORT
    return os.path.join(SUPPORT, "descriptions.json")


def remember(url: str, srt: str) -> None:
    try:
        with open(_registry()) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    data[url] = srt
    try:  # written whole or not at all; a failure here must never fail a finished description
        os.makedirs(os.path.dirname(_registry()), exist_ok=True)
        tmp = _registry() + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, _registry())
    except OSError:
        pass


def for_item(path: str | None, url: str | None) -> str | None:
    """A made description for this file or link, if there is one."""
    if path:
        folder, base = os.path.split(path)
        stem = os.path.splitext(base)[0]
        cand = os.path.join(folder, stem + SUFFIX + ".srt")
        if os.path.exists(cand):
            return cand
    if url:
        try:
            with open(_registry()) as fh:
                p = json.load(fh).get(url)
            if p and os.path.exists(p):
                return p
        except (OSError, ValueError):
            pass
    return None


if __name__ == "__main__":  # pragma: no cover
    sys.exit("Use Wavelength.")
