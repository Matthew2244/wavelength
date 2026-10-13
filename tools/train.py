"""Real-world training run: python tools/train.py WORKDIR [--only NAME ...]

Downloads a matrix of real links with real options through the same scheduler the
window uses, all at once, then checks every result: the file exists, its type and
length make sense, and failures are explained in words. Needs the internet. Not part
of the test suite; run it after anything that touches downloading, and add a case
whenever a site or option misbehaves.
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
work = os.path.abspath(sys.argv[1])
only = set(sys.argv[3:]) if sys.argv[2:3] == ["--only"] else set()
os.environ["MEDIA_DOWNLOAD_TEST_DIR"] = os.path.join(work, "state")

from media_download import manager, words  # noqa: E402
from media_download.jobs import Job  # noqa: E402

ZOO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
# name, url, options, what a good result looks like
CASES = [
    ("yt-best", ZOO, {}, {"ext": (".opus", ".m4a"), "audio": True}),
    ("yt-mp3", ZOO, {"kind": "mp3"}, {"ext": (".mp3",)}),
    ("yt-flac", ZOO, {"kind": "flac"}, {"ext": (".flac",)}),
    ("yt-video-720", ZOO, {"kind": "video", "max_height": 720}, {"ext": (".mp4",), "vcodec": "h264"}),
    ("yt-section", ZOO, {"kind": "wav", "start": "0:03", "end": "0:08"}, {"ext": (".wav",), "length": (4.5, 5.5)}),
    ("yt-subtitles", "https://www.youtube.com/watch?v=jNQXAC9IVRw", {"subtitles": True},
     {"extra_ext": ".srt", "min_files": 2}),
    ("yt-short-link", "https://youtu.be/jNQXAC9IVRw", {"kind": "m4a"}, {"ext": (".m4a",)}),
    ("yt-music-link", "https://music.youtube.com/watch?v=jNQXAC9IVRw", {"kind": "mp3"}, {"ext": (".mp3",)}),
    ("yt-exact-stream", ZOO, {"format_id": "140", "format_audio_only": True}, {"ext": (".m4a",)}),
    ("yt-named", ZOO, {"name": "zoo / named: test"}, {"name_has": "zoo"}),
    ("yt-chapters", "https://www.youtube.com/watch?v=gcANcHGf6LQ", {"chapters": True, "kind": "mp3"},
     {"min_files": 9}),  # 8 chapters plus the whole
    ("soundcloud", "https://soundcloud.com/forss/flickermood", {"kind": "best"}, {"audio": True}),
    ("needs-sign-in", "https://vimeo.com/76979871", {"kind": "video", "max_height": 360},
     {"fails_with": "wants you signed in"}),
    ("bandcamp", "https://diskotopia.bandcamp.com/track/safehouse", {"kind": "mp3"}, {"ext": (".mp3",)}),
    ("archive-file", "https://archive.org/download/gd1977-05-08.shure57.stevenson.29303.flac16/"
                     "gd1977-05-08d01t01.flac", {"kind": "mp3"}, {"ext": (".mp3",)}),
    ("direct-mp3", "https://www.learningcontainer.com/wp-content/uploads/2020/02/Kalimba.mp3", {}, {"audio": True}),
    ("yt-transcript", "https://www.youtube.com/watch?v=gcANcHGf6LQ", {"transcript": True, "kind": "m4a"},
     {"extra_ext": ".txt", "no_ext": ".srt"}),
    ("podcast-rss", "https://feeds.npr.org/510289/podcast.xml", {"kind": "best"}, {"playlist": True}),
    ("apple-podcast", "https://podcasts.apple.com/us/podcast/planet-money/id290783428", {}, {"playlist_or_done": True}),
    ("spotify-drm", "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC", {}, {"fails_with": "DRM"}),
    ("dead-link", "https://www.youtube.com/watch?v=xxxxxxxxxxx", {}, {"fails_with": "isn't available"}),
    ("not-media", "https://example.com/", {}, {"fails": True}),
    ("bad-extra-flag", ZOO, {"extra": "--no-such-flag"}, {"fails_with": "extra yt-dlp options"}),
]


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name",
                          "-of", "json", path], capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except ValueError:
        return {}


def main():
    cases = [c for c in CASES if not only or c[0] in only]
    m = manager.Manager({"auto_update": False, "app_per_site": 3}, lambda j, w, d=None: None)
    jobs = {}
    t0 = time.time()
    for name, url, opts, _ in cases:
        dest = os.path.join(work, "out", name)
        jobs[name] = m.add(Job(url=url, dest=dest, **opts))
    playlists = {}
    m.listener = lambda j, w, d=None: playlists.__setitem__(j.id, d) if w == "playlist" else None
    while m.busy() and time.time() - t0 < 900:
        for name, j in list(jobs.items()):
            if j.state == "waiting_choice" and j.id in playlists:
                d = playlists.pop(j.id)
                # A playlist: take its first item, the way a person checking one would.
                items = m.expand(j, d["entries"][:1], d["title"])
                jobs[name] = items[0] if items else j
                jobs[name].from_playlist = len(d["entries"])
        time.sleep(0.3)
    took = time.time() - t0
    bad = 0
    for name, url, opts, want in cases:
        j = jobs[name]
        files = [f for f in j.files if os.path.exists(f)]
        problems = []
        if want.get("fails") or want.get("fails_with"):
            if j.state != "failed":
                problems.append("should have failed, was %s" % j.state)
            elif want.get("fails_with") and want["fails_with"] not in j.reason:
                problems.append("reason was: %s" % j.reason)
        else:
            if j.state != "done":
                problems.append("%s: %s" % (j.state, j.reason))
            elif not files:
                problems.append("no file reported")
            for f in files:
                info = probe(f) if not f.endswith(".srt") else {}
                streams = {s.get("codec_type"): s.get("codec_name") for s in info.get("streams", [])}
                if want.get("ext") and not any(f.endswith(e) for e in want["ext"]) and not f.endswith(".srt"):
                    problems.append("got %s" % os.path.basename(f))
                if want.get("audio") and "audio" not in streams and not f.endswith(".srt"):
                    problems.append("no audio in %s" % os.path.basename(f))
                if want.get("vcodec") and streams.get("video") != want["vcodec"]:
                    problems.append("video is %s" % streams.get("video"))
                if want.get("length"):
                    d = float(info.get("format", {}).get("duration") or 0)
                    lo, hi = want["length"]
                    if not lo <= d <= hi:
                        problems.append("length %.2f s" % d)
            if want.get("extra_ext"):
                folder = os.path.join(work, "out", name)
                if not any(fn.endswith(want["extra_ext"]) for fn in os.listdir(folder) if os.path.isdir(folder)):
                    problems.append("no %s beside it" % want["extra_ext"])
            if want.get("no_ext"):
                folder = os.path.join(work, "out", name)
                if any(fn.endswith(want["no_ext"]) for fn in os.listdir(folder)):
                    problems.append("a %s was left behind" % want["no_ext"])
            if want.get("playlist") and not getattr(j, "from_playlist", 0):
                problems.append("wasn't treated as a playlist")
            if want.get("min_files") and len(files) < want["min_files"]:
                problems.append("only %d files" % len(files))
            if want.get("name_has") and not any(want["name_has"] in os.path.basename(f) for f in files):
                problems.append("named %s" % [os.path.basename(f) for f in files])
        bad += bool(problems)
        if getattr(j, "from_playlist", 0) and not problems:
            problems = []
        print("%-16s %-4s %s" % (name, "ok" if not problems else "FAIL",
                                 "; ".join(problems) if problems else words.row_text(j)[:90]))
    print("\n%d of %d as expected, %.0f s" % (len(cases) - bad, len(cases), took))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
