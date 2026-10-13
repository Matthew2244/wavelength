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


def finish(frame, monkeypatch, jobs, busy, batch_total):
    said = []
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
    assert finish(frame, monkeypatch, [job("done", "A")], busy=False, batch_total=3) == []


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
