import os
import sys
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("MEDIA_DOWNLOAD_TEST_DIR", os.path.join(ROOT, ".test-state"))

from media_download import manager, options, words  # noqa: E402
from media_download.jobs import Job  # noqa: E402


# ---------------------------------------------------------------- words

def test_durations_and_sizes_read_naturally():
    assert words.duration(61) == "1 minute 1 second"
    assert words.duration(3720) == "1 hour 2 minutes"
    assert words.duration(None) == ""
    assert words.size(9_400_000) == "9.4 MB"
    assert words.size(2_000_000_000) == "2 GB"
    assert words.short_time_left(130) == "about 2 minutes left"
    assert words.short_time_left(5) == "a few seconds left"


def test_times_parse_every_way_people_write_them():
    assert words.parse_time("1:30") == 90
    assert words.parse_time("1:02:03") == 3723
    assert words.parse_time("90") == 90
    assert words.parse_time("1m30s") == 90
    assert words.parse_time("") is None
    assert words.parse_time("soon") is None


def test_links_found_in_pasted_text_once_each():
    text = "listen https://youtu.be/abc, and https://example.com/x.mp3. again https://youtu.be/abc"
    assert words.links_in(text) == ["https://youtu.be/abc", "https://example.com/x.mp3"]


def test_site_names():
    assert words.site_name("https://youtu.be/x") == "youtube.com"
    assert words.site_name("https://www.bbc.co.uk/sounds/play/x") == "bbc.co.uk"
    assert words.site_name("https://artist.bandcamp.com/track/y") == "bandcamp.com"
    assert words.site_name("https://music.youtube.com/watch?v=1") == "youtube.com"


def test_failures_explained_in_plain_words():
    assert "members only" in words.explain_failure("ERROR: Join this channel to get access")
    assert "private" in words.explain_failure("ERROR: Private video")
    assert "sign-in" in words.explain_failure("Sign in to confirm you're not a bot")
    assert "too many" in words.explain_failure("HTTP Error 429: Too Many Requests")
    assert words.explain_failure("ERROR: something odd").startswith("That failed. The engine said: something odd")
    assert words.explain_failure("HTTP Error 500: Internal Server Error (caused by <x>)", site="archive.org") \
        == "archive.org had a problem on its end (error 500). Retry in a minute usually works."
    # Blame the right site.
    assert words.explain_failure("HTTP Error 403", site="bandcamp.com").startswith("bandcamp.com")


def test_rows_put_status_before_title():
    j = Job(url="https://youtu.be/x", dest="/tmp")
    j.title = "Song"
    j.state = "downloading"
    j.percent, j.eta = 45, 130
    assert words.row_text(j) == "Downloading, 45 percent, about 2 minutes left: Song"
    j.state, j.files, j.bytes_done = "done", ["/tmp/Song.m4a"], 9_400_000
    assert words.row_text(j) == "Done: Song, 9.4 MB"
    j.state, j.reason = "failed", "That one is private."
    assert words.row_text(j) == "Failed: Song. That one is private."


# ---------------------------------------------------------------- options

def spec(**kw):
    base = {"url": "https://x", "dest": "/tmp/d", "kind": "best"}
    base.update(kw)
    return base


def test_best_keeps_the_source_codec():
    a = options.download_args(spec())
    assert a[a.index("--audio-format") + 1] == "best"


def test_named_stream_is_never_converted():
    a = options.download_args(spec(kind="mp3", format_id="251", format_audio_only=True))
    assert a[a.index("--audio-format") + 1] == "best"
    assert "320K" not in a


def test_subtitles_name_real_tracks_not_a_glob():
    a = options.download_args(spec(subtitles=True))
    assert a[a.index("--sub-langs") + 1] == "en,en-orig,en-US,en-GB"


def test_playlist_items_go_numbered_into_their_folder():
    t = options.output_template({"subfolder": "My: Set/2", "index": 7})
    assert t == "My_ Set_2/007 - %(title)s.%(ext)s"


def test_flags_parse_in_yt_dlp():
    yt_dlp = pytest.importorskip("yt_dlp")
    for s in (spec(), spec(kind="video", max_height=720), spec(kind="mp3", start="1:00", end="2:00"),
              spec(chapters=True, subfolder="Set", index=2), spec(extra="--limit-rate 2M")):
        yt_dlp.parse_options(options.download_args(s) + ["https://x"])


def test_wav_gets_no_cover_art():
    assert "--embed-thumbnail" not in options.download_args(spec(kind="wav"))
    assert "--embed-thumbnail" in options.download_args(spec(kind="mp3"))


# ---------------------------------------------------------------- the scheduler

@pytest.fixture
def fake(monkeypatch, tmp_path):
    here = os.path.dirname(os.path.abspath(__file__))
    monkeypatch.setattr(manager, "worker_command", lambda: [sys.executable, os.path.join(here, "fake_worker.py")])
    events = []
    lock = threading.Lock()

    def listener(job, what, data=None):
        with lock:
            events.append((job.id if job else None, what, data))
    m = manager.Manager({"app_parallel": 2, "app_per_site": 1, "auto_update": False}, listener)
    return m, events


def wait(cond, t=20):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_downloads_finish_and_report_files(fake):
    m, events = fake
    j = m.add(Job(url="https://a.com/one", dest="/tmp"))
    assert wait(lambda: j.state == "done")
    assert j.title == "Title of https://a.com/one"
    assert j.files == ["/tmp/fake/one.m4a"]
    assert wait(lambda: any(w == "all_done" for _, w, _ in events))


def test_limits_hold_per_site_and_overall(fake):
    m, events = fake
    jobs = [m.add(Job(url="https://same.com/slow%d" % i, dest="/tmp")) for i in range(3)]
    others = [m.add(Job(url="https://other%d.com/slow" % i, dest="/tmp")) for i in range(3)]
    peak_site = peak_all = 0
    end = time.time() + 30
    while time.time() < end and not all(j.state == "done" for j in jobs + others):
        running = [j for j in jobs + others if j.state in ("downloading", "converting")]
        peak_site = max(peak_site, sum(1 for j in running if j.site == "same.com" and j.state == "downloading"))
        peak_all = max(peak_all, len(running))
        time.sleep(0.02)
    assert all(j.state == "done" for j in jobs + others)
    assert peak_site == 1
    assert peak_all == 2


def test_failure_is_explained(fake):
    m, _ = fake
    j = m.add(Job(url="https://a.com/fail", dest="/tmp"))
    assert wait(lambda: j.state == "failed")
    assert "isn't available" in j.reason


def test_lookup_failure_is_explained(fake):
    m, _ = fake
    j = m.add(Job(url="https://a.com/badprobe", dest="/tmp"))
    assert wait(lambda: j.state == "failed")
    assert j.reason == "That one is private."


def test_stop_then_retry(fake):
    m, _ = fake
    j = m.add(Job(url="https://a.com/slowstop", dest="/tmp"))
    assert wait(lambda: j.state == "downloading" and j.percent)
    m.stop(j)
    assert j.state == "stopped"
    m.retry(j)
    assert wait(lambda: j.state == "done")


def test_playlist_asks_then_expands_in_order(fake):
    m, events = fake
    j = m.add(Job(url="https://a.com/playlist", dest="/tmp"))
    assert wait(lambda: any(w == "playlist" for _, w, _ in events))
    data = [d for _, w, d in events if w == "playlist"][0]
    items = m.expand(j, data["entries"][:2], data["title"])
    assert [i.index for i in items] == [1, 2]
    assert all(i.subfolder == "Set" for i in items)
    assert j not in m.jobs
    assert wait(lambda: all(i.state == "done" for i in items))


def test_list_survives_a_restart(fake, monkeypatch, tmp_path):
    m, _ = fake
    monkeypatch.setattr(manager.engine, "QUEUE_FILE", str(tmp_path / "q.json"))
    a = m.add(Job(url="https://a.com/one", dest="/tmp"))
    assert wait(lambda: a.state == "done")
    b = Job(url="https://b.com/two", dest="/tmp")
    b.probed = True
    b.state = "downloading"
    m.jobs.append(b)
    m.save()
    m2 = manager.Manager({}, None)
    assert m2.restore() == 1
    states = {j.url: j.state for j in m2.jobs}
    assert states == {"https://a.com/one": "done", "https://b.com/two": "stopped"}


def test_video_prefers_h264_unless_asked_for_more():
    assert "vcodec^=avc1" in options.selector(spec(kind="video"))[1]
    assert "vcodec^=avc1" in options.selector(spec(kind="video", max_height=720))[1]
    assert "avc1" not in options.selector(spec(kind="video", max_height=2160))[1]
    assert options.selector(spec(kind="video", max_height=-1))[1] == "bv*+ba/b"


def test_playlist_items_named_from_the_listing():
    t = options.output_template({"subfolder": "Barton Hall", "index": 2, "item_title": "Lazy Lightning>Supplication"})
    assert t.startswith("Barton Hall/002 - Lazy Lightning")
    assert t.endswith(".%(ext)s")
