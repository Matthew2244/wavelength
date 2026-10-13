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
    assert "Retry Using a Browser's Sign-in" in words.explain_failure("Sign in to confirm you're not a bot")
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
    assert [os.path.basename(f) for f in j.files] == ["one.m4a"]
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


def test_stop_and_retry_hammered_never_strands_a_download(fake):
    """A stopped run finishing late must never touch the next run (a race CI found)."""
    m, _ = fake
    jobs = [m.add(Job(url="https://s%d.com/slow" % i, dest="/tmp")) for i in range(4)]
    for _ in range(6):
        for j in jobs:
            wait(lambda: j.state in ("downloading", "converting", "done"), 5)
            m.stop(j)
            m.retry(j)
    assert wait(lambda: all(j.state == "done" for j in jobs), 40), [j.state for j in jobs]
    assert not m.procs


class _FakeBackend:
    def __init__(self, name, running, said):
        self.name, self._running, self.said = name, running, said

    @property
    def features(self):
        class F:
            is_supported_at_runtime = self._running
            supports_output = True
        return F

    def output(self, text, interrupt=False):
        self.said.append((self.name, text))


def _fake_prism(monkeypatch, running):
    import enum
    import types
    said = []
    ids = enum.IntEnum("BackendId", {n: i + 1 for i, n in enumerate(
        ("SAPI", "ONE_CORE", "NVDA", "JAWS", "ZDSR", "SYSTEM_ACCESS", "ZOOM_TEXT", "SENSE_READER",
         "PC_TALKER", "BOY_PC_READER", "UIA"))})

    class Ctx:
        def exists(self, bid):
            return True

        def acquire(self, bid):
            name = ids(bid).name
            if name not in running and name not in ("UIA", "SAPI", "ONE_CORE"):
                raise RuntimeError("Backend not available")
            return _FakeBackend(name, name in running or name in ("SAPI", "ONE_CORE"), said)
    monkeypatch.setitem(sys.modules, "prism", types.SimpleNamespace(Context=Ctx, BackendId=ids))
    from media_download import system
    monkeypatch.setattr(system, "_win_reader", {"ctx": None, "failed": False})
    return system, said


def test_windows_speech_prefers_the_running_reader(monkeypatch):
    system, said = _fake_prism(monkeypatch, running={"JAWS"})
    assert system._announce_windows("Done: Song.") == "JAWS"
    assert said == [("JAWS", "Done: Song.")]


def test_windows_speech_falls_back_to_narrator_never_plain_tts(monkeypatch):
    system, said = _fake_prism(monkeypatch, running=set())
    assert system._announce_windows("Done: Song.") == "UIA"
    assert said == [("UIA", "Done: Song.")]


def test_release_notes_become_sparkle_html():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import appcast
    out = appcast.notes_html("Windows now speaks.\n\n- One `fix`.\n- Two <b>.")
    assert out == "<p>Windows now speaks.</p>\n<ul><li>One <code>fix</code>.</li><li>Two &lt;b&gt;.</li></ul>"


def test_each_download_gets_its_own_temporary_folder():
    a, b = Job(url="https://x/1", dest="/tmp"), Job(url="https://x/1", dest="/tmp")
    ta = options.download_args(a.spec())
    tb = options.download_args(b.spec())
    temp = lambda args: [v for v in args if v.startswith("temp:")][0]
    assert temp(ta) != temp(tb)
    assert Job.from_dict(a.to_dict()).tmp == a.tmp  # survives a restart, so Retry resumes


def test_a_name_never_makes_a_folder():
    assert options.output_template({"name": "zoo / named: test"}) == "zoo _ named_ test.%(ext)s"


def test_sign_in_and_bad_options_explained():
    assert "signed in" in words.explain_failure("The web client only works when logged-in.", site="vimeo.com")
    assert "More Options" in words.explain_failure("BADOPTIONS: no such option: --x")


def test_dropped_connection_retries_by_itself(fake, monkeypatch, tmp_path):
    m, events = fake
    monkeypatch.setenv("FAKE_STATE", str(tmp_path))
    j = m.add(Job(url="https://net.com/flaky1", dest="/tmp"))
    assert wait(lambda: j.state == "waiting" and j.not_before, 15)
    assert "Waiting to try again" in words.row_text(j)
    assert 10 < j.not_before - time.time() <= 15
    with m.lock:
        j.not_before = time.time()  # skip the 15-second wait
    m.pump()
    assert wait(lambda: j.state == "done", 20)
    assert j.net_retries == 1


def test_slow_down_pauses_the_whole_site(fake, monkeypatch, tmp_path):
    m, events = fake
    monkeypatch.setenv("FAKE_STATE", str(tmp_path))
    j = m.add(Job(url="https://busy.com/busy1", dest="/tmp"))
    assert wait(lambda: j.state == "waiting" and j.not_before, 15)
    other = m.add(Job(url="https://busy.com/two", dest="/tmp"))
    time.sleep(1.5)
    assert other.state in ("waiting", "looking") and other.state != "downloading"
    assert m.site_pause["busy.com"] > time.time() + 200
    assert any(w == "site_paused" for _, w, _ in events)
    assert "asked for fewer downloads" in words.details_text(j)
    m.retry(j)  # by hand: goes now
    assert wait(lambda: j.state == "done", 20)


def test_drm_and_transcripts():
    assert "DRM" in words.explain_failure("ERROR: [generic] The requested site is known to use DRM protection.")
    srt = ("1\n00:00:00,000 --> 00:00:02,000\nhello there\n\n2\n00:00:02,000 --> 00:00:02,010\nhello there\n \n\n"
           "3\n00:00:02,010 --> 00:00:04,000\nhello there\nhow are you\n\n"
           "4\n00:00:09,000 --> 00:00:10,000\n<c>after a pause</c>\n")
    assert words.srt_to_text(srt, "Song") == "Song\n\nhello there how are you\n\nafter a pause\n"


def test_speed_limit_reaches_yt_dlp():
    a = options.download_args(spec(rate_limit="1M"))
    assert a[a.index("--limit-rate") + 1] == "1M"


def test_captions_follow_the_clock():
    cues = words.caption_cues("1\n00:00:01,000 --> 00:00:03,000\nhello\n\n2\n00:00:03,000 --> 00:00:05,000\nhello\nthere\n")
    assert cues == [(1.0, 3.0, "hello"), (3.0, 5.0, "there")]
    assert words.cue_at(cues, 0.5) == ""
    assert words.cue_at(cues, 2) == "hello"
    assert words.cue_at(cues, 4) == "there"
    assert words.cue_at(cues, 20) == ""
    assert words.clock_words(3723) == "1:02:03" and words.clock_words(83) == "1:23"


def test_player_picks_the_whole_file_not_a_chapter(tmp_path):
    pytest.importorskip("wx")
    from media_download.player import playable_file, speed_words
    whole = tmp_path / "Album.mp3"
    chap = tmp_path / "Album - 01 Intro.mp3"
    txt = tmp_path / "Album - transcript.txt"
    for p in (whole, chap, txt):
        p.write_text("x")
    assert playable_file([str(chap), str(whole), str(txt)]) == str(whole)
    assert speed_words(1.0) == "Normal" and speed_words(1.5) == "1.5 times"


def test_description_files_round_trip(tmp_path, monkeypatch):
    from media_download import describe
    monkeypatch.setattr(describe, "_registry", lambda: str(tmp_path / "reg.json"))
    rows = [{"time": 0.0, "text": "A man stands by a fence."}, {"time": 12.0, "text": "He turns to the camera."}]
    srt, txt = describe.write_outputs(rows, str(tmp_path), "Me at the zoo")
    assert os.path.basename(srt) == "Me at the zoo - audio description.srt"
    assert "No person wrote or checked it" in open(txt).read()
    cues = words.caption_cues(open(srt).read())
    assert [c[2] for c in cues] == ["A man stands by a fence.", "He turns to the camera."]
    video = tmp_path / "Me at the zoo.mp4"
    video.write_text("x")
    assert describe.for_item(str(video), None) == srt          # beside a downloaded video
    describe.remember("https://x/v", srt)
    assert describe.for_item(None, "https://x/v") == srt         # for a link never downloaded


def test_described_versions_must_share_a_real_word():
    from media_download import describe
    got = describe.rank_candidates("Wicked - Official Trailer", [
        {"title": "Audio Described Welcome for Edinburgh Playhouse"},
        {"title": "Wicked | Official Trailer | Audio Described"}])
    assert [g["title"] for g in got] == ["Wicked | Official Trailer | Audio Described"]
    assert describe.looks_described("Frozen II (Audio Description)")
    assert not describe.looks_described("Frozen II trailer")


def test_a_description_is_never_taken_for_captions(tmp_path):
    pytest.importorskip("wx")
    from media_download.player import captions_for
    (tmp_path / "Clip.mp4").write_text("x")
    (tmp_path / "Clip - audio description.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nA room.\n")
    assert captions_for(str(tmp_path / "Clip.mp4")) == []
    (tmp_path / "Clip.en.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nhello\n")
    assert captions_for(str(tmp_path / "Clip.mp4")) == [(0.0, 2.0, "hello")]
