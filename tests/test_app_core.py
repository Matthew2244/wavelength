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
    assert wait(lambda: all(j.state == "done" for j in jobs), 40), [(j.state, j.reason) for j in jobs]
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
    assert cues[0][2].startswith("[")  # the machine-made line comes first
    assert [c[2] for c in cues[1:]] == ["A man stands by a fence.", "He turns to the camera."]
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


def test_too_big_for_the_disk_fails_before_starting(fake, monkeypatch):
    import collections
    m, _ = fake
    usage = collections.namedtuple("usage", "total used free")
    monkeypatch.setattr(manager.shutil if hasattr(manager, "shutil") else __import__("shutil"), "disk_usage",
                        lambda p: usage(10**12, 10**12 - 300_000_000, 300_000_000))
    j = Job(url="https://a.com/one", dest="/tmp")
    j.bytes_total = 2_000_000_000
    with m.lock:
        assert m._no_room(j)
    assert "isn't room" in j.reason and "2 GB" in j.reason
    j.bytes_total = 1_000
    with m.lock:
        assert not m._no_room(j)


def test_own_sounds_ship_and_unknown_kinds_have_none():
    from media_download import system
    for kind in ("done", "failed"):
        path = system.sound_file(kind)
        assert path and os.path.getsize(path) > 10_000
    assert system.sound_file("nonsense") is None


def test_a_download_without_a_title_is_never_read_out_as_a_whole_address():
    j = Job(url="https://www.vimeo.com/76979871/", dest="/tmp")
    assert words.job_name(j) == "a vimeo.com link"
    assert words.row_text(j).endswith(": vimeo.com/76979871")
    assert words.job_name(Job(url="https://example.org/music/My%20Song.mp3", dest="/tmp")) == "My Song.mp3"
    j.title = "Real title"
    assert words.job_name(j) == "Real title" and words.row_text(j).endswith("Real title")


def test_extra_options_keep_windows_paths_and_refuse_an_open_quote(monkeypatch):
    assert options.split_extra('--embed-metadata -o "%(title)s.%(ext)s"') == [
        "--embed-metadata", "-o", "%(title)s.%(ext)s"]
    monkeypatch.setattr(options.sys, "platform", "win32")
    assert options.split_extra(r'--ffmpeg-location C:\tools "--paths" "D:\My Music"') == [
        "--ffmpeg-location", r"C:\tools", "--paths", r"D:\My Music"]
    monkeypatch.setattr(options.sys, "platform", "darwin")
    with pytest.raises(ValueError):
        options.split_extra('--title "unclosed')


def test_playlist_folders_are_found_where_they_are_really_made(monkeypatch):
    j = Job(url="https://x.com/a", dest="/tmp", subfolder="Live: 1977")
    assert j.folder() == os.path.join("/tmp", options.safe_folder("Live: 1977"))
    assert not options.safe_folder("x" * 119 + " .").endswith((" ", "."))
    monkeypatch.setattr(options.sys, "platform", "win32")
    assert options.safe_folder("CON") == "CON_" and options.safe_folder("Concert") == "Concert"
    short = options.name_budget({"dest": "C:\\Users\\a\\Downloads", "tmp": "job-1"})
    deep = options.name_budget({"dest": "D:\\" + "x" * 150, "tmp": "job-1"})
    assert 60 <= deep < short <= 150


def test_a_killed_lookup_never_fails_its_retry(fake, monkeypatch):
    """Stop then Retry during a lookup puts the row back to "looking" before the killed lookup's
    thread finishes; that thread must see it's stale, not call the retry a failure."""
    m, _ = fake
    j = m.add(Job(url="https://k.com/slowprobe", dest="/tmp"))
    assert wait(lambda: j.id in m.procs and m.procs[j.id][1] is not None, 5)
    pump = m.pump
    monkeypatch.setattr(m, "pump", lambda: None)  # hold the retry at "looking", as a busy queue does
    m.stop(j)
    m.retry(j)
    time.sleep(1.5)  # the killed lookup reports back
    assert j.state == "looking", (j.state, j.reason)
    monkeypatch.setattr(m, "pump", pump)
    m.pump()
    assert wait(lambda: j.state == "done", 20), (j.state, j.reason)


def test_upload_dates_said_plainly():
    import time as _t
    now = _t.mktime((2026, 10, 13, 12, 0, 0, 0, 0, -1))
    assert words.uploaded({"uploaded": "20240304"}, now) == "uploaded March 4, 2024"
    assert words.uploaded({"uploaded": "20261013"}, now) == "uploaded today"
    assert words.uploaded({"uploaded": "20261012"}, now) == "uploaded yesterday"
    day = 86400
    assert words.uploaded({"uploaded_ts": now - 2 * 365 * day, "approx": True}, now) == "uploaded about 2 years ago"
    assert words.uploaded({"uploaded_ts": now - 3 * day, "approx": True}, now) == "uploaded 3 days ago"
    assert words.uploaded({"uploaded_ts": now - 21 * day, "approx": True}, now) == "uploaded about 3 weeks ago"
    assert words.uploaded({"uploaded_ts": now - 60 * day}, now).startswith("uploaded August 1")  # exact
    assert words.uploaded({}, now) == ""
    assert words.views(402321) == "402 thousand views"
    assert words.views(1) == "1 view"
    assert words.views(1234) == "1,234 views"
    assert words.views(1_250_000) == "1.2 million views" or words.views(1_250_000) == "1.3 million views"
    assert words.views(3_000_000) == "3 million views"


def test_job_takes_exact_date_over_approximate():
    j = Job(url="https://x.com/a", dest="/tmp")
    j.take_when({"uploaded_ts": 1700000000, "approx": True, "views": 5})
    assert j.upload_approx and j.views == 5
    j.take_when({"uploaded": "20231114"})
    assert j.upload_date == "20231114" and not j.upload_approx
    j.take_when({"uploaded_ts": 1, "approx": True})  # a later guess never replaces a real date
    assert j.upload_date == "20231114"
    assert "Uploaded November 14, 2023." in words.details_text(j)


def test_every_sound_set_is_complete():
    """Each set in Settings has every sound, for the Mac (MP3) and Windows (WAV), and its credits."""
    from media_download import system
    root = os.path.join(ROOT, "assets", "sounds")
    credits = open(os.path.join(root, "CREDITS.md")).read().lower()
    for key, _ in system.THEMES:
        if key == "system":
            continue
        for kind, _, _ in system.SOUNDS:
            for ext in (".mp3", ".wav"):
                path = os.path.join(root, "shared" if kind in system.SHARED else key, kind + ext)
                assert os.path.getsize(path) > 1000, path
                assert system.sound_file(kind, key) is not None
        assert key in credits, key
    assert "shared" in credits


def test_each_action_can_have_any_sound_or_none(tmp_path, monkeypatch):
    from media_download import system
    monkeypatch.setattr(system, "custom_dir", lambda: str(tmp_path))
    assert system.resolve("done", "pizzicato")[1].endswith(os.path.join("pizzicato", "done" + system._ext()))
    assert system.resolve("done", "pizzicato", {"done": "none"}) is None
    assert system.resolve("done", "pizzicato", {"done": "kalimba:added"})[1].endswith(
        os.path.join("kalimba", "added" + system._ext()))
    (tmp_path / "bell.wav").write_bytes(b"x" * 200)
    assert system.resolve("copied", "rhodes", {"copied": "custom:bell.wav"}) == ("file", str(tmp_path / "bell.wav"))
    # an imported sound that was deleted falls back to the set, never to silence
    assert system.resolve("copied", "rhodes", {"copied": "custom:gone.wav"})[1].endswith(
        os.path.join("rhodes", "copied" + system._ext()))
    assert ("custom:bell.wav", "Your sound: bell") in system.sound_choices()
    assert system.sound_map({"app_sounds_off": ["added"]}) == {"added": "none"}
    assert system.sound_volume({"app_sound_volume": 0}) == 0.0


def test_quieter_wav_for_windows(tmp_path, monkeypatch):
    import array
    import wave
    from media_download import engine, system
    monkeypatch.setattr(engine, "CACHE", str(tmp_path / "cache"))
    src = tmp_path / "s.wav"
    with wave.open(str(src), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(array.array("h", [10000, -10000, 20000]).tobytes())
    out = system._scaled_wav(str(src), 0.5)
    with wave.open(out, "rb") as r:
        assert list(array.array("h", r.readframes(3))) == [5000, -5000, 10000]


def test_import_any_sound_file(tmp_path, monkeypatch):
    from media_download import engine, system
    if not engine.find_tool("ffmpeg"):
        pytest.skip("needs ffmpeg")
    monkeypatch.setattr(system, "custom_dir", lambda: str(tmp_path / "sounds"))
    src = tmp_path / "Door Bell!.mp3"
    import subprocess
    subprocess.run([engine.find_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "sine=f=660:d=0.3", str(src)],
                   check=True)
    name, said = system.import_sound(str(src))
    assert name == "Door Bell.wav" and said == "Imported Door Bell."
    name2, _ = system.import_sound(str(src))
    assert name2 == "Door Bell 2.wav"  # never overwrites one already there
    bad = tmp_path / "notes.txt"
    bad.write_text("hello")
    assert system.import_sound(str(bad))[0] is None


def test_when_finished_said_plainly():
    import time as _t
    now = _t.mktime((2026, 10, 13, 18, 0, 0, 0, 0, -1))
    assert words.when_words(now - 3600, now).startswith("at 5:00 PM today")
    assert words.when_words(now - 86400, now) == "yesterday at 6:00 PM"
    assert words.when_words(_t.mktime((2026, 10, 2, 20, 0, 0, 0, 0, -1)), now) == "on October 2 at 8:00 PM"
    assert words.when_words(_t.mktime((2025, 1, 5, 9, 5, 0, 0, 0, -1)), now) == "on January 5, 2025 at 9:05 AM"


def test_accounts_addresses_and_sign_in_words():
    from media_download import accounts
    cfg = {}
    assert accounts.address("youtube_liked", cfg) == "https://www.youtube.com/playlist?list=LL"
    assert accounts.address("soundcloud_likes", cfg) is None  # needs a profile name first
    assert "asks for your profile name" in accounts.row_words("soundcloud_likes", cfg)
    cfg["app_profile_soundcloud"] = accounts.profile_name("https://soundcloud.com/forss/likes", "soundcloud")
    assert accounts.address("soundcloud_likes", cfg) == "https://soundcloud.com/forss/likes"
    assert accounts.profile_name("@forss", "soundcloud") == "forss"
    said = accounts.explain_signin("ERROR: Login details are needed to download this content", "safari", "YouTube")
    assert said.startswith("Safari isn't signed in to YouTube") and "password" in said
    said = accounts.explain_signin("PermissionError: [Errno 1] Operation not permitted: 'Cookies.binarycookies'",
                                   "safari")
    assert "Full Disk Access" in said
    assert accounts.explain_signin("HTTP Error 404", "safari") is None
    # a failed download with a borrowed sign-in says which browser, and what to do
    assert words.explain_failure("Sign in to confirm you're not a bot", True, "YouTube", "chrome").startswith(
        "Google Chrome isn't signed in to YouTube")


def test_downloads_borrow_the_sign_in_when_chosen():
    from media_download import accounts
    assert accounts.signin({"app_signin": "safari"}) == "safari" and accounts.signin({}) == ""
    assert "--cookies-from-browser" in options.download_args(spec(cookies="safari"))


def test_old_folders_move_to_the_new_name(tmp_path, monkeypatch):
    from media_download import engine
    old_s, old_c = tmp_path / "Media Download", tmp_path / "Caches" / "Media Download"
    old_s.mkdir()
    old_c.mkdir(parents=True)
    (old_s / "downloads.json").write_text("{}")
    monkeypatch.setattr(engine, "SUPPORT", str(tmp_path / "Wavelength"))
    monkeypatch.setattr(engine, "CACHE", str(tmp_path / "Caches" / "Wavelength"))
    engine._move_old_folders()
    assert (tmp_path / "Wavelength" / "downloads.json").exists() and not old_s.exists()
    assert (tmp_path / "Caches" / "Wavelength").is_dir()
    # A move that failed once left a fresh new folder: bring over what's missing, never overwrite.
    old_s.mkdir()
    (old_s / "downloads.json").write_text('{"old": 1}')
    (old_s / "sounds").mkdir()
    engine._move_old_folders()
    assert (tmp_path / "Wavelength" / "downloads.json").read_text() == "{}"  # the new one kept
    assert (tmp_path / "Wavelength" / "sounds").is_dir() and (old_s / "downloads.json").exists()


def test_app_never_undoes_a_change_made_by_the_command(tmp_path, monkeypatch):
    import json as _json
    from media_download import engine
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(_json.dumps({"format": "best", "notify": False}))
    monkeypatch.setattr(engine, "CONFIG", str(cfg_file))
    cfg = engine.load_settings()
    cfg_file.write_text(_json.dumps({"format": "mp3", "notify": False}))  # `ytdl --set format=mp3` meanwhile
    cfg["app_volume"] = 0.5  # the app changes only this
    engine.save_settings(cfg)
    saved = _json.loads(cfg_file.read_text())
    assert saved["format"] == "mp3" and saved["app_volume"] == 0.5


def test_a_quit_is_counted_and_resumed_but_a_stop_by_hand_is_not(fake, monkeypatch, tmp_path):
    m, _ = fake
    monkeypatch.setattr(manager.engine, "QUEUE_FILE", str(tmp_path / "q.json"))
    cut = Job(url="https://a.com/cut", dest="/tmp")
    cut.state = "downloading"
    mine = Job(url="https://b.com/mine", dest="/tmp")
    mine.state, mine.reason = "stopped", "Stopped by you."
    m.jobs.extend([cut, mine])
    m.shutdown()  # an ordinary quit, not a crash
    m2 = manager.Manager({}, None)
    assert m2.restore() == 1  # "1 download didn't finish last time" is said after a normal quit too
    resumed = []
    monkeypatch.setattr(m2, "retry", lambda j: resumed.append(j.url))
    assert m2.resume_unfinished() == 1 and resumed == ["https://a.com/cut"]


def test_an_unwritable_folder_is_explained_and_never_waits_on_an_engine_update():
    for err in ("ERROR: [Errno 13] Permission denied: '/Volumes/Music/x.part'",
                "ERROR: [WinError 3] The system cannot find the path specified: 'E:\\\\Music'",
                "ERROR: [Errno 30] Read-only file system: '/Volumes/Card/x'"):
        assert not words.worth_updating_for(err)
        assert "download folder" in words.explain_failure(err)


def test_an_unreadable_sign_in_is_skipped_once_and_said(fake, monkeypatch, tmp_path):
    m, _ = fake
    monkeypatch.setenv("FAKE_STATE", str(tmp_path))
    j = m.add(Job(url="https://ex.com/lockedcookies", dest="/tmp", cookies="chrome"))
    assert wait(lambda: j.state == "done")
    assert j.cookies == "" and j.cookie_fallback == "chrome"
    assert "still open" in j.note and j.note.endswith("It came without the sign-in.")
    m.retry(j)  # by hand: the sign-in comes back, in case Chrome is closed now
    assert j.cookies == "chrome" and not j.note
    assert wait(lambda: j.state == "done")


def test_unreadable_sign_in_is_told_apart_from_other_trouble():
    assert words.cookie_store_unreadable("ERROR: Could not copy Chrome cookie database.")
    assert words.cookie_store_unreadable("PermissionError: [Errno 1] Operation not permitted: "
                                         "'/Users/x/Library/Containers/com.apple.Safari/Data/Library/Cookies/"
                                         "Cookies.binarycookies'")
    assert not words.cookie_store_unreadable("ERROR: [Errno 13] Permission denied: '/Volumes/Music/Song.m4a.part'")
    assert not words.cookie_store_unreadable("ERROR: [youtube] abc: Private video")
    from media_download import accounts
    assert accounts.explain_signin("ERROR: [Errno 13] Permission denied: '/Volumes/Music/x.part'", "firefox") is None


def test_sha256_from_reads_both_deno_layouts():
    from media_download import engine
    h = "a0c3101b4158d1dfb7d6a78a7bf0f3de80c96bb423c152beec8beb22786f2238"
    assert engine.sha256_from(h + "  deno-aarch64-apple-darwin.zip\n") == h
    win = ("\r\nAlgorithm : SHA256\r\nHash      : " + h.upper() +
           "\r\nPath      : C:\\a\\deno\\deno-x86_64-pc-windows-msvc.zip\r\n\r\n")
    assert engine.sha256_from(win) == h
    assert engine.sha256_from("Not Found") is None


def _fake_tool(folder, name):
    os.makedirs(folder, exist_ok=True)
    p = os.path.join(folder, name + (".exe" if sys.platform == "win32" else ""))
    with open(p, "w") as fh:
        fh.write("#!/bin/sh\n")
    os.chmod(p, 0o755)


def test_ffmpeg_and_ffprobe_are_found_as_a_pair(tmp_path, monkeypatch):
    from media_download import engine
    lone, both = str(tmp_path / "lone"), str(tmp_path / "both")
    _fake_tool(lone, "ffmpeg")  # ffmpeg with no ffprobe beside it: yt-dlp couldn't find ffprobe
    _fake_tool(both, "ffmpeg")
    _fake_tool(both, "ffprobe")
    monkeypatch.setattr(engine, "SEARCH_DIRS", [lone, both])
    monkeypatch.setattr(engine.shutil, "which", lambda name: None)
    assert os.path.dirname(engine.find_tool("ffmpeg")) == both
    assert os.path.dirname(engine.find_tool("ffprobe")) == both
    monkeypatch.setattr(engine, "SEARCH_DIRS", [lone])
    monkeypatch.setattr(engine, "TOOLS", str(tmp_path / "empty"))
    assert engine.find_tool("ffmpeg") is None and engine.find_tool("ffprobe") is None


def test_an_interrupted_engine_update_is_never_used(tmp_path, monkeypatch):
    from media_download import engine
    monkeypatch.setattr(engine, "ENGINES", str(tmp_path))
    for name in (".new-x5555abc", "2026.8.19"):
        os.makedirs(tmp_path / name / "yt_dlp")
        (tmp_path / name / "yt_dlp" / "__init__.py").write_text("")
    assert [v for v, _ in engine.installed_engines()] == ["2026.8.19"]


@pytest.mark.skipif(sys.platform != "win32", reason="the swap script is Windows's")
def test_windows_swap_handles_accented_paths_with_spaces(tmp_path):
    import subprocess
    from media_download import update
    root = tmp_path / "José Q"
    new_app, target, work = root / "new app", root / "Wavelength", root / "work dir"
    for d in (new_app, target, work):
        d.mkdir(parents=True)
    (new_app / "Wavelength.exe").write_text("new")
    (target / "Wavelength.exe").write_text("old")
    (target / "stale.dll").write_text("gone after the mirror")
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    script, command = update.windows_swap(str(work), gone.pid, str(new_app), str(target), False)
    text = open(script, encoding="ascii").read()  # plain ASCII, whatever the paths
    with open(script, "w", encoding="ascii", newline="") as fh:  # robocopy's report, for a failure
        fh.write(text.replace(" /NFL /NDL /NJH /NJS >nul", ""))
    run = subprocess.run(command, timeout=120, capture_output=True, text=True,
                         encoding="oem", errors="replace")
    print(command, run.returncode, run.stdout, run.stderr, sep="\n")
    assert (target / "Wavelength.exe").read_text() == "new", run.stdout + run.stderr
    assert not (target / "stale.dll").exists()
    assert not work.exists()


def test_player_keys_that_altgr_can_type_on_are_known():
    from media_download import keyboard
    assert keyboard.vk_of("Ctrl+Alt+N") == ord("N") and keyboard.vk_of("Ctrl+Alt+.") == 0xBE
    assert keyboard.vk_of("Ctrl+Alt+PageUp") is None and keyboard.vk_of("Ctrl+Alt+Home") is None


@pytest.mark.skipif(sys.platform != "win32", reason="AltGr is Control-Alt only on Windows")
def test_altgr_letters_are_read_from_the_layout():
    import ctypes
    from media_download import keyboard
    load = ctypes.windll.user32.LoadKeyboardLayoutW
    load.restype = ctypes.c_void_p
    polish = load("00000415", 0x80)     # Polish (Programmers): AltGr+N is ń
    hungarian = load("0000040E", 0x80)  # AltGr+V is @
    us = load("00000409", 0x80)         # AltGr types nothing
    assert keyboard.altgr_char(ord("N"), polish) == "ń"
    assert keyboard.altgr_char(ord("V"), hungarian) == "@"
    assert keyboard.altgr_char(ord("N"), us) == ""


@pytest.mark.skipif(sys.platform != "win32", reason="MCI is Windows's")
def test_windows_sounds_play_through_their_own_device_without_raising(tmp_path):
    import wave
    from media_download import system
    path = str(tmp_path / "beep é.wav")
    with wave.open(path, "wb") as w:
        w.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
        w.writeframes(b"\x00\x10" * 2205)  # a tenth of a second
    system._play_windows(path)  # no sound card on CI: MCI or its fallback must not raise
    system._play_windows(path)


def test_every_made_description_srt_says_it_was_machine_made(tmp_path):
    from media_download import describe, words
    out = describe.write_outputs([{"time": 2, "text": "A man walks."}], str(tmp_path), "T")
    cues = words.caption_cues(open([p for p in out if p.endswith(".srt")][0], encoding="utf-8").read())
    assert cues[0][2].startswith("[") and describe.HEADER in cues[0][2]
    assert cues[1][2] == "A man walks."


def test_captions_belong_only_to_their_own_file(tmp_path):
    pytest.importorskip("wx")
    from media_download import player
    for name in ("Intro.m4a", "Intro (Live).en.srt", "Song.m4a", "Song 2.en.srt", "Song 2.m4a"):
        (tmp_path / name).write_text("1\n00:00:01,000 --> 00:00:02,000\n%s\n" % name, encoding="utf-8")
    assert player.captions_for(str(tmp_path / "Intro.m4a")) == []
    assert player.captions_for(str(tmp_path / "Song.m4a")) == []
    assert player.captions_for(str(tmp_path / "Song 2.m4a"))[0][2] == "Song 2.en.srt"


# ---------------------------------------------------------------- a worker that won't start

class _Pipe:
    def __init__(self, broken=False):
        self.broken, self.text, self.closed = broken, "", False

    def write(self, s):
        if self.broken:
            raise BrokenPipeError(32, "Broken pipe")
        self.text += s

    def close(self):
        self.closed = True


class _Proc:
    def __init__(self, broken=False):
        self.stdin = _Pipe(broken)


def test_a_dead_spare_worker_falls_back_to_a_fresh_one(monkeypatch):
    dead, fresh, killed = _Proc(broken=True), _Proc(), []
    monkeypatch.setattr(manager, "_take_spare", lambda: dead)
    monkeypatch.setattr(manager, "_start_worker", lambda: fresh)
    monkeypatch.setattr(manager, "_kill", killed.append)
    monkeypatch.setattr(manager, "warm", lambda: None)
    assert manager._popen({"task": "search"}) is fresh
    assert killed == [dead] and '"search"' in fresh.stdin.text and fresh.stdin.closed


def test_a_worker_that_cannot_start_raises_one_clear_error(monkeypatch):
    def nope():
        raise FileNotFoundError(2, "No such file or directory")
    monkeypatch.setattr(manager, "_take_spare", lambda: None)
    monkeypatch.setattr(manager, "_start_worker", nope)
    monkeypatch.setattr(manager, "warm", lambda: None)
    with pytest.raises(manager.WorkerError) as got:
        manager.run_task({"task": "search"})
    assert isinstance(got.value, OSError)  # the download path's `except` still catches it
    assert got.value.said().startswith("Wavelength's worker couldn't start: ")
    assert "reinstall" in got.value.said()


def test_failing_a_job_from_outside_finishes_it_like_a_worker_failure():
    events = []
    m = manager.Manager({"app_parallel": 2}, lambda job, what, data=None: events.append(what))
    j = Job(url="https://a.com/list", dest="/tmp")
    j.state = "waiting_choice"
    m.jobs.append(j)
    m.batch_started, m.batch_total = time.time(), 1
    m.fail(j, "That playlist is empty, or its items couldn't be listed.")
    assert j.state == "failed" and j.finished and j.reason.startswith("That playlist is empty")
    assert events[0] == "finished" and events[-1] == "all_done"  # said, and the batch closed
    assert m.batch_started is None


# ---------------------------------------------------------------- windows (need wx)

def test_a_finished_lookup_finds_its_row_again_after_a_re_sort():
    pytest.importorskip("wx")
    from media_download import dialogs
    a, b = {"url": "a"}, {"url": "b"}
    win = type("W", (), {})()
    win.results = [b, a]  # re-sorted while the lookup ran: a new list, a moved row
    assert dialogs.row_of(a, dialogs.current_rows(win, [a, b])) == 1
    win.results = [{"url": "a"}]  # searched again: an equal dict is not the same row
    assert dialogs.row_of(a, dialogs.current_rows(win, [a, b])) is None
    assert dialogs.current_rows(object(), [a]) == [a]


def test_a_lookup_that_could_not_run_still_says_why():
    pytest.importorskip("wx")
    from media_download import dialogs
    page = dialogs.failed_page(manager.WorkerError("Broken pipe"))
    assert page == [] and page.error.startswith("Wavelength's worker couldn't start: Broken pipe.")
    assert dialogs.failed_result(RuntimeError("boom")) == {"error": "That didn't work: boom. Try again."}


def test_one_off_options_never_spread_across_many_results():
    pytest.importorskip("wx")
    import types
    from media_download import gui
    added = []
    me = types.SimpleNamespace(
        next_opts={"name": "My Song", "format_id": "251", "format_words": "opus", "start": "1:00",
                   "end": "2:00", "subtitles": True},
        cfg={"to": "/tmp"}, PER_LINK=gui.MainFrame.PER_LINK, seen_links=set(),
        mgr=types.SimpleNamespace(lock=threading.RLock(), jobs=[], add=added.append),
        _picks=lambda: ("best", 0), _show_opts=lambda: None, refresh=lambda: None)
    me._job_from_ui = lambda url, per_link=True, picks=None: gui.MainFrame._job_from_ui(me, url, per_link, picks)
    fresh, skipped = gui.MainFrame.add_entries(me, [{"url": "https://a.com/1"}, {"url": "https://a.com/2"}])
    assert len(fresh) == 2 and skipped == 0
    assert all(j.name == "" and j.format_id == "" and j.start == "" and j.end == "" for j in added)
    assert all(j.subtitles for j in added)  # the rest of More Options applies, once
    assert me.next_opts == {"name": "My Song", "format_id": "251", "format_words": "opus", "start": "1:00",
                            "end": "2:00"}  # kept for the next single link


def test_a_file_in_use_on_windows_is_not_blamed_on_the_folder():
    from media_download import words
    line = "ERROR: Unable to rename file: [WinError 32] The process cannot access the file"
    assert "another program" in words.explain_failure(line, False, "YouTube", "").lower()
    assert words.worth_updating_for("ERROR: [WinError 3] The system cannot find the path") is False
    assert "folder" in words.explain_failure("ERROR: [WinError 3] The system cannot find the path", False, "YouTube", "")


def test_a_wav_source_with_cover_art_never_asks_for_an_engine_update():
    from media_download import words
    assert words.worth_updating_for("ERROR: Postprocessing: Supported filetypes for thumbnail embedding are: mp3") is False


def test_a_retried_failure_leaves_the_batch_tally(monkeypatch):
    import json as _json
    from media_download import manager as M
    from media_download.jobs import Job

    class Proc:
        def __init__(self, lines):
            self.stdout, self.pid = iter(lines), 0

        def wait(self):
            return 0

        def poll(self):
            return 0
    plan = {"a": [False, True], "b": [True]}
    retried = threading.Event()

    def held(lines):  # b keeps running until a has been retried, so both are in one batch
        retried.wait(10)
        yield from lines

    def fake(task):
        url = task["spec"]["url"]
        if task["task"] == "probe":
            return Proc([_json.dumps({"ev": "info", "title": url}), _json.dumps({"ev": "end", "ok": True})])
        if url == "b":
            plan[url].pop(0)
            return Proc(held([_json.dumps({"ev": "end", "ok": True})]))
        if plan[url].pop(0):
            return Proc([_json.dumps({"ev": "end", "ok": True})])
        return Proc([_json.dumps({"ev": "log", "text": "ERROR: Private video"}), _json.dumps({"ev": "end", "ok": False})])
    monkeypatch.setattr(M, "_popen", fake)
    ends = []
    m = M.Manager({"app_parallel": 2}, lambda j, w, d=None: ends.append(d) if w == "all_done" else None)
    dest = os.environ["MEDIA_DOWNLOAD_TEST_DIR"]
    b = m.add(Job(url="b", dest=dest))
    deadline = time.time() + 10
    while b.state != "downloading" and time.time() < deadline:
        time.sleep(0.05)
    a = m.add(Job(url="a", dest=dest))
    while a.state != "failed" and time.time() < deadline:
        time.sleep(0.05)
    m.retry(a)  # while b is still running: one batch, the failure already counted
    retried.set()
    deadline = time.time() + 10
    while not ends and time.time() < deadline:
        time.sleep(0.05)
    assert ends and ends[-1]["done"] == 2 and ends[-1]["failed"] == 0


class _FakeConfig:
    def __init__(self):
        self.d = {}

    def Read(self, k, default=""):
        return self.d.get(k, default)

    def Write(self, k, v):
        self.d[k] = v

    def Flush(self):
        pass


def _update_frame(modal=False):
    import types
    f = types.SimpleNamespace(update_info=None, notices=[], ui=_FakeConfig(), said=[], sounds=[])
    f._update_title = lambda: None
    f._modal_open = lambda: modal
    f._sound = f.sounds.append
    f.tell = f.said.append
    return f


def test_a_new_version_is_told_once_with_the_update_sound(monkeypatch):
    wx = pytest.importorskip("wx")
    from media_download import gui
    monkeypatch.setattr(wx, "GetApp", lambda: type("A", (), {"IsActive": lambda self: True})())
    f = _update_frame()
    gui.MainFrame._found_update(f, {"version": "9.9.9"})
    gui.MainFrame._found_update(f, {"version": "9.9.9"})  # the next look, four hours on
    assert len(f.notices) == 1 and f.update_info["version"] == "9.9.9"
    gui.MainFrame._deliver_notice(f)
    assert f.sounds == ["update"] and "9.9.9 is out" in f.said[0]


def test_a_notice_waits_for_a_dialog_to_close_and_for_the_app_to_be_in_front(monkeypatch):
    wx = pytest.importorskip("wx")
    from media_download import gui
    active = {"yes": False}
    monkeypatch.setattr(wx, "GetApp", lambda: type("A", (), {"IsActive": lambda self: active["yes"]})())
    f = _update_frame(modal=False)
    f.notices.append(("update", "Updated the download engine to 2099.1.1."))
    gui.MainFrame._deliver_notice(f)  # another app in front: nothing said into it
    assert f.said == [] and f.sounds == []
    active["yes"] = True
    f._modal_open = lambda: True
    gui.MainFrame._deliver_notice(f)  # a question open: it waits
    assert f.said == []
    f._modal_open = lambda: False
    gui.MainFrame._deliver_notice(f)
    assert f.sounds == ["update"] and f.said == ["Updated the download engine to 2099.1.1."]


def test_greetings_fit_the_time_of_day_and_never_repeat_in_a_row():
    import datetime
    import random
    from media_download import words
    assert [words.day_part(h) for h in (2, 5, 9, 12, 15, 19, 22)] == \
        ["late", "early", "morning", "midday", "afternoon", "evening", "night"]
    tue_9am = datetime.datetime(2026, 10, 13, 9, 0)
    rng = random.Random(1)
    last = ""
    for _ in range(30):
        g = words.greeting(tue_9am, "Matthew", last, rng)
        assert g != last and "Matthew" in g
        assert g in [x.format(n=", Matthew") for x in words.GREETINGS["morning"]]
        last = g
    assert ", ," not in words.greeting(tue_9am, "", "", rng) and "{n}" not in words.greeting(tue_9am, "", "", rng)
    friday_night = datetime.datetime(2026, 10, 16, 20, 30)
    seen = {words.greeting(friday_night, "", "", random.Random(i)) for i in range(200)}
    assert "Happy Friday. The weekend starts now." in seen
    assert words.greeting(datetime.datetime(2027, 1, 1, 10), "", "", random.Random(3)) or True
