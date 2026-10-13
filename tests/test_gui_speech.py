"""What the window says when downloads finish. Needs wxPython, so it is skipped where wx isn't installed."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
wx = pytest.importorskip("wx")

from media_download import gui  # noqa: E402
from media_download.jobs import Job  # noqa: E402


@pytest.fixture(scope="module")
def frame(tmp_path_factory):
    os.environ["MEDIA_DOWNLOAD_TEST_DIR"] = str(tmp_path_factory.mktemp("gui"))
    gui.MainFrame.startup_checks = lambda self: None
    app = wx.App(False)
    f = gui.MainFrame()
    f.timer.Stop()
    yield f
    f.Destroy()
    app.Destroy()


def finish(frame, monkeypatch, jobs, busy, batch_total, counts=None):
    said = []
    frame.mgr.batch_counts = counts or {
        "done": sum(j.state in ("done", "skipped") for j in jobs),
        "failed": sum(j.state == "failed" for j in jobs)}
    monkeypatch.setattr(gui, "announce", lambda t: said.append(t))
    monkeypatch.setattr(gui, "play", lambda k: None)
    monkeypatch.setattr(frame.mgr, "busy", lambda: busy)
    frame.mgr.batch_total = batch_total
    frame.finished_buffer = list(jobs)
    frame._speak_finished()
    return said


def job(state, title, **kw):
    j = Job(url="https://x.com/" + title, dest="/tmp")
    j.state, j.title = state, title
    for k, v in kw.items():
        setattr(j, k, v)
    return j


def test_one_finish_is_named_once(frame, monkeypatch):
    assert finish(frame, monkeypatch, [job("done", "Song")], busy=True, batch_total=2) == ["Done: Song."]


def test_a_note_is_said_with_its_finish(frame, monkeypatch):
    j = job("done", "Song", note="It has no captions, so there's no transcript.")
    assert finish(frame, monkeypatch, [j], busy=True, batch_total=2) == [
        "Done: Song. It has no captions, so there's no transcript."]


def test_two_finishes_counted(frame, monkeypatch):
    said = finish(frame, monkeypatch, [job("done", "A"), job("done", "B")], busy=True, batch_total=3)
    assert said == ["2 downloads finished."]


def test_failure_always_named(frame, monkeypatch):
    j = job("failed", "Clip", reason="That one is private.")
    assert finish(frame, monkeypatch, [j], busy=True, batch_total=40) == ["Failed: Clip. That one is private."]


def test_end_of_batch_left_to_the_summary(frame, monkeypatch):
    assert finish(frame, monkeypatch, [job("done", "A")], busy=False, batch_total=3,
                  counts={"done": 3, "failed": 0}) == []


def test_the_one_that_finished_is_named_when_the_other_was_stopped(frame, monkeypatch):
    # Two added, one stopped: no "All downloads finished" comes, so the finish must be said here.
    assert finish(frame, monkeypatch, [job("done", "Song")], busy=False, batch_total=2) == ["Done: Song."]


def test_editing_keys_in_the_link_field_never_touch_the_list(frame, monkeypatch):
    removed = []
    monkeypatch.setattr(frame.mgr, "remove", lambda j: removed.append(j))
    monkeypatch.setattr(frame, "selected", lambda: job("done", "Keep me"))
    t = frame.link
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: t))
    t.SetValue("https://example.com/one two")
    t.SetInsertionPointEnd()
    frame.on_remove(None)
    assert removed == []
    assert t.GetValue() == ("" if sys.platform == "darwin" else "https://example.com/one ")
    t.SetValue("abc def")
    t.SetInsertionPoint(3)
    frame.on_move(+1)
    assert t.GetSelection() == (3, 7)
    frame.on_open(None)
    assert t.GetInsertionPoint() == 7


def test_describe_window_offers_people_first(frame, monkeypatch):
    from media_download import dialogs
    monkeypatch.setattr(dialogs.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda s: None})())
    dlg = dialogs.DescribeDialog(frame, "https://x/v", "Clip", lambda u: {}, {})
    dlg._found({"about": {"title": "Clip", "track": "251", "track_words": "English descriptive", "has_video": True,
                          "can_make": True},
                "candidates": [{"url": "https://y", "title": "Clip (Audio Described)", "duration": 60}]})
    kinds = [o["kind"] for o in dlg.options]
    assert kinds == ["track", "version", "make"]
    dlg.list.SetSelection(2)
    dlg._buttons()
    assert dlg.make_btn.IsEnabled() and not dlg.play_btn.IsEnabled()
    dlg.Destroy()


def test_unavailable_folder_is_said_and_nothing_added(frame, monkeypatch):
    said, asked = [], []
    monkeypatch.setattr(gui, "announce", lambda t: said.append(t))

    class No:
        def __init__(self, parent, msg, *a, **k):
            asked.append(msg)

        def SetOKCancelLabels(self, *a):
            pass

        def ShowModal(self):
            return wx.ID_CANCEL

        def Destroy(self):
            pass
    monkeypatch.setattr(gui.wx, "MessageDialog", No)
    old = frame.cfg["to"]
    frame.cfg["to"] = "/Volumes/A Drive That Is Not Plugged In/Media"
    try:
        before = len(frame.mgr.jobs)
        assert frame.add_links(["https://x.com/a"]) == 0
        assert len(frame.mgr.jobs) == before
        assert "isn't connected" in asked[0]
        assert said[-1] == "Nothing added: the download folder isn't available."
    finally:
        frame.cfg["to"] = old


def test_default_folder_is_on_this_computer():
    from media_download import engine, words
    d = engine.default_folder()
    assert "CloudDocs" not in d and d.endswith(os.path.join("Downloads", "Media Downloads"))
    assert words.pretty_folder(d) == "Downloads > Media Downloads"


def test_hundredth_download_is_mentioned_in_the_done_sentence(frame, monkeypatch):
    monkeypatch.setattr(gui.engine, "save_settings", lambda cfg: None)
    frame.cfg["app_stats"] = {"count": 99, "bytes": 0, "seconds": 0, "since": "2026-10-13"}
    j = job("done", "Song", bytes_done=5_000_000, length=200)
    frame._count(j)
    said = finish(frame, monkeypatch, [j], busy=True, batch_total=2)
    assert said == ["Done: Song. That's your 100th download."]
    frame._count(job("done", "Next", bytes_done=1, length=1))
    assert frame.milestone == ""  # 101 is not a milestone, and it was said only once


def test_about_tally_reads_naturally(frame):
    frame.cfg["app_stats"] = {"count": 214, "bytes": 18_300_000_000, "seconds": 41 * 3600, "since": "2026-10-13"}
    assert frame.tally() == ("Since October 13, 2026: 214 downloads, 18.3 GB, about 41 hours of listening and "
                             "watching.")
    frame.cfg["app_stats"] = {}
    assert frame.tally() == "Nothing downloaded yet."


def test_whats_happening_names_what_is_downloading(frame, monkeypatch):
    said = []
    monkeypatch.setattr(gui, "announce", lambda t: said.append(t))
    a = job("downloading", "Green Onions", percent=45)
    b = job("waiting", "The Sermon")
    c = job("done", "Turning")
    old = frame.mgr.jobs
    frame.mgr.jobs = [a, b, c]
    try:
        frame.on_whats_happening(None)
    finally:
        frame.mgr.jobs = old
    assert said == ["Downloading Green Onions, 45 percent. 1 waiting, 1 done."]


def test_welcome_uses_the_first_name(frame, monkeypatch):
    monkeypatch.setattr(gui.words, "first_name", lambda: "Matthew")
    assert frame.welcome().startswith("Welcome to Media Download, Matthew.")
    monkeypatch.setattr(gui.words, "first_name", lambda: "")
    assert frame.welcome().startswith("Welcome to Media Download.")


def test_sounds_never_play_on_top_of_each_other(frame, monkeypatch):
    played, later = [], []
    monkeypatch.setattr(gui, "play", lambda k: played.append(k))
    monkeypatch.setattr(gui.wx, "CallLater", lambda ms, fn, *a: later.append((ms, fn, a)))
    frame.next_sound_at = 0.0
    frame._sound("failed")
    frame._sound("done")
    assert played == ["failed"]
    assert len(later) == 1 and 1000 <= later[0][0] <= 1400 and later[0][2] == ("done",)


# ---- Search is an ordinary window, so it can never hold the whole app's keyboard

def _drain():
    for _ in range(5):
        wx.GetApp().ProcessPendingEvents()
        wx.Yield()


def test_search_opens_once_and_closes_for_good(frame, monkeypatch):
    monkeypatch.setattr(gui, "announce", lambda t: None)
    frame.link.SetValue("")
    frame.on_search(None)
    first = frame.search_win
    assert isinstance(first, wx.Frame) and first.GetMenuBar()  # its own menus, never borrowed
    frame.on_search(None)  # Command-F again brings the same one forward
    assert frame.search_win is first
    first.cancel.Command(wx.CommandEvent(wx.wxEVT_BUTTON, wx.ID_CANCEL))  # Close, Escape, Command-W
    assert frame.search_win is None
    _drain()
    assert not [w for w in wx.GetTopLevelWindows() if isinstance(w, gui.dialogs.Search)]


def test_search_download_ticked_adds_rows(frame, monkeypatch):
    added = []
    monkeypatch.setattr(gui, "announce", lambda t: None)
    monkeypatch.setattr(frame.mgr, "add", lambda j: added.append(j))
    monkeypatch.setattr(frame, "folder_ready", lambda: True)
    frame.on_search(None)
    dlg = frame.search_win
    dlg._show("q", "YouTube", [{"url": "https://y.example/1", "title": "One"},
                               {"url": "https://y.example/2", "title": "Two"}])
    dlg.list.Check(1)
    dlg._count()
    dlg.ok.Command(wx.CommandEvent(wx.wxEVT_BUTTON, wx.ID_OK))
    assert [j.title for j in added] == ["Two"]
    assert frame.search_win is None
    _drain()


def test_key_words():
    c = "Command" if sys.platform == "darwin" else "Control"
    assert gui.key_words("Ctrl+Shift+.") == c + "-Shift-Period"
    assert gui.key_words("Ctrl+W") == c + "-W"
    assert gui.key_words("Ctrl+=") == c + "-Plus"


def test_shortcut_list_comes_from_the_menus(frame):
    frame.show_shortcuts()
    text = frame.details.GetValue()
    c = "Command" if sys.platform == "darwin" else "Control"
    for want in (c + "-W: Close Window", c + "-P: Play", c + "-Period: Stop", c + "-2: Go to the Player"):
        assert want in text, want


def test_search_again_keeps_ticks(frame, monkeypatch):
    monkeypatch.setattr(gui, "announce", lambda t: None)
    searched = []
    frame.on_search(None, query="")
    dlg = frame.search_win
    monkeypatch.setattr(dlg, "on_search", lambda e: searched.append(dlg.query.GetValue()))
    dlg.last_query = "piano"
    dlg._show("piano", "YouTube", [{"url": "https://y.example/1", "title": "One"}])
    dlg.list.Check(0)
    dlg._count()
    frame.on_search(None, query="piano")  # Command-F with the same words: keep the ticks
    assert searched == [] and dlg.list.IsChecked(0)
    frame.on_search(None, query="organ")  # new words: search
    assert searched == ["organ"]
    dlg.cancel.Command(wx.CommandEvent(wx.wxEVT_BUTTON, wx.ID_CANCEL))
    _drain()


def test_search_never_clears_a_link_typed_since(frame, monkeypatch):
    monkeypatch.setattr(gui, "announce", lambda t: None)
    added = []
    monkeypatch.setattr(frame.mgr, "add", lambda j: added.append(j))
    monkeypatch.setattr(frame, "folder_ready", lambda: True)
    frame.link.SetValue("some words")
    frame.on_search(None)
    dlg = frame.search_win
    frame.link.SetValue("https://example.com/new")
    dlg._show("q", "YouTube", [{"url": "https://y.example/1", "title": "One"}])
    dlg.list.Check(0)
    dlg._count()
    dlg.ok.Command(wx.CommandEvent(wx.wxEVT_BUTTON, wx.ID_OK))
    assert len(added) == 1 and frame.link.GetValue() == "https://example.com/new"
    _drain()
