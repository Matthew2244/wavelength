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
    gui.dialogs.message_log = []  # a message window would wait for a key press, in front of whoever is here
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
    monkeypatch.setattr(gui, "play", lambda k, *a: None)
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
        assert gui.dialogs.message_log[-1] == ("Nothing added: the download folder isn't available.", "Okay")
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
    assert frame.welcome().startswith("Welcome to Wavelength, Matthew.")
    monkeypatch.setattr(gui.words, "first_name", lambda: "")
    assert frame.welcome().startswith("Welcome to Wavelength.")


def test_sounds_never_play_on_top_of_each_other(frame, monkeypatch):
    played, later = [], []
    monkeypatch.setattr(gui, "play", lambda k, *a: played.append(k))
    monkeypatch.setattr(gui.wx, "CallLater", lambda ms, fn, *a: later.append((ms, fn, a)))
    frame.next_sound_at = 0.0
    frame._sound("failed")
    frame._sound("done")
    assert played == ["failed"]
    assert len(later) == 1 and 1000 <= later[0][0] <= 1400 and later[0][2][0] == "done"


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


def test_search_download_checked_adds_rows(frame, monkeypatch):
    added = []
    monkeypatch.setattr(gui, "announce", lambda t: None)
    monkeypatch.setattr(frame.mgr, "add", lambda j: added.append(j))
    monkeypatch.setattr(frame, "folder_ready", lambda: True)
    frame.on_search(None)
    dlg = frame.search_win
    dlg.searched = ("q", "youtube")
    dlg._show("q", "youtube", "YouTube", 1, [{"url": "https://y.example/1", "title": "One"},
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
    dlg.searched = ("piano", "youtube")
    dlg._show("piano", "youtube", "YouTube", 1, [{"url": "https://y.example/1", "title": "One"}])
    dlg.list.Check(0)
    dlg._count()
    frame.on_search(None, query="piano")  # Command-F with the same words: keep the checks
    assert searched == [] and dlg.list.IsChecked(0)
    frame.on_search(None, query="organ")  # new words: search
    assert searched == ["organ"]
    dlg.cancel.Command(wx.CommandEvent(wx.wxEVT_BUTTON, wx.ID_CANCEL))
    _drain()


def test_search_page_of_repeats_is_not_the_end(frame, monkeypatch):
    """YouTube repeats results across pages. A page of only repeats moves on by itself; the
    next page starts after the positions fetched, not after the count kept."""
    monkeypatch.setattr(gui, "announce", lambda t: None)
    frame.on_search(None, query="")
    dlg = frame.search_win
    page = gui.dialogs.SEARCH_PAGE
    pages = {1: ["a", "b"], page + 1: ["a", "b"], 2 * page + 1: ["c"], 3 * page + 1: []}
    asked = []

    def fake_fetch(q, site_key, site, start):
        asked.append(start)
        wx.CallAfter(dlg._show, q, site_key, site, start,
                     [{"url": "https://y.example/" + u, "title": u} for u in pages[start]])
    monkeypatch.setattr(dlg, "_fetch", fake_fetch)
    dlg.query.SetValue("x")
    dlg.on_search(None)
    _drain()
    dlg.more()
    _drain()
    assert asked == [1, page + 1, 2 * page + 1]
    assert [e["title"] for e in dlg.results] == ["a", "b", "c"] and dlg.has_more
    dlg.more()
    _drain()
    assert not dlg.has_more and "every result" in dlg.status.GetLabel()
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
    dlg.searched = ("q", "youtube")
    dlg._show("q", "youtube", "YouTube", 1, [{"url": "https://y.example/1", "title": "One"}])
    dlg.list.Check(0)
    dlg._count()
    dlg.ok.Command(wx.CommandEvent(wx.wxEVT_BUTTON, wx.ID_OK))
    assert len(added) == 1 and frame.link.GetValue() == "https://example.com/new"
    _drain()


def test_search_pages_have_no_ceiling(frame, monkeypatch):
    """Results come a page at a time, checks survive each new page, and only a page with nothing
    new ends it."""
    monkeypatch.setattr(gui, "announce", lambda t: None)
    monkeypatch.setattr(gui.dialogs, "announce", lambda t: None, raising=False)
    frame.on_search(None, query="")
    dlg = frame.search_win
    page = gui.dialogs.SEARCH_PAGE
    asked = []

    def fake_fetch(q, site_key, site, start):
        asked.append(start)
        total = page * 3 + 4  # the "site" has 79 results
        res = [{"url": "https://y.example/%d" % n, "title": "R%d" % n} for n in range(start, min(total, start + page - 1) + 1)]
        dlg._show(q, site_key, site, start, res)
    monkeypatch.setattr(dlg, "_fetch", fake_fetch)
    dlg.query.SetValue("organ")
    dlg.on_search(None)
    dlg.list.Check(3)
    for _ in range(10):
        dlg.more()
    assert asked == [1, page + 1, 2 * page + 1, 3 * page + 1, 4 * page + 1]
    assert len(dlg.results) == page * 3 + 4 and not dlg.has_more
    assert dlg.list.IsChecked(3) and dlg.list.GetCount() == len(dlg.results)
    assert "every result" in dlg.status.GetLabel()
    dlg.cancel.Command(wx.CommandEvent(wx.wxEVT_BUTTON, wx.ID_CANCEL))
    _drain()


def test_look_further_for_described_versions(frame, monkeypatch):
    """Described versions are searched a page at a time, people's versions stay above Make,
    and Look Further stops only when the search runs out."""
    monkeypatch.setattr(gui, "announce", lambda t: None)
    page = gui.describe.VERSIONS_PAGE
    pages = {page + 1: {"candidates": [{"url": "https://y.example/b", "title": "B described"}], "searched": page},
             2 * page + 1: {"candidates": [], "searched": 0}}
    asked = []

    def run_more(title, start):
        asked.append(start)
        return pages[start]
    first = {"about": {"title": "Film", "can_make": True, "has_video": True},
             "candidates": [{"url": "https://y.example/a", "title": "A described"}], "searched": page}
    dlg = gui.dialogs.DescribeDialog(frame, "https://y.example/film", "Film", lambda u: first, {}, run_more=run_more)
    _drain()
    assert [o["kind"] for o in dlg.options] == ["version", "make"] and dlg.more_btn.IsEnabled()
    monkeypatch.setattr(gui.dialogs.threading, "Thread",
                        lambda target, daemon: type("T", (), {"start": staticmethod(target)})())
    dlg.look_further()
    _drain()
    assert [o.get("title") for o in dlg.options] == ["A described", "B described", None]
    dlg.look_further()
    _drain()
    assert asked == [page + 1, 2 * page + 1] and not dlg.more_btn.IsEnabled()
    assert "end of the search" in dlg.status.GetLabel()
    dlg.Destroy()


def test_list_menu_says_only_what_fits_the_row(frame):
    from media_download import menus
    j = Job(url="https://soundcloud.com/x/y", dest="/tmp")
    j.state, j.title = "failed", "A failed one"
    frame.mgr.jobs.append(j)
    frame.structure_changed = True
    frame.refresh()
    frame.list.SetSelection(frame.list.GetCount() - 1)
    said = menus.labels(frame.list_menu())
    assert "Retry" in said and "Copy Link" in said and "Open the Web Page" in said
    assert "Play" not in said and "Stop" not in said and "Open File" not in said
    frame.mgr.jobs.remove(j)
    frame.structure_changed = True
    frame.refresh()


def test_search_row_menu(frame, monkeypatch):
    from media_download import menus
    monkeypatch.setattr(gui, "announce", lambda t: None)
    frame.on_search(None, query="")
    dlg = frame.search_win
    dlg.searched = ("q", "youtube")
    dlg._show("q", "youtube", "YouTube", 1, [{"url": "https://y.example/1", "title": "One", "uploader": "Kraft Music",
                                              "channel_url": "https://www.youtube.com/@kraftmusic"}])
    dlg.list.SetSelection(0)
    said = menus.labels(gui.dialogs.entry_menu(dlg, dlg.list, dlg.results, frame, play=lambda: None))
    for want in ("Play or Pause", "Check", "Download This One Now", "Look Up Exact Date and Details",
                 "Everything from Kraft Music...", "Search for Kraft Music", "Copy Link",
                 "Check from Here to the End"):
        assert want in said, want
    added = []
    monkeypatch.setattr(frame, "folder_ready", lambda: True)
    monkeypatch.setattr(frame.mgr, "add", lambda job: added.append(job))
    frame.download_now(dlg.results[0])
    assert [j.title for j in added] == ["One"] and frame.search_win is dlg  # Search stays open
    dlg.cancel.Command(wx.CommandEvent(wx.wxEVT_BUTTON, wx.ID_CANCEL))
    _drain()


def test_search_order_keeps_checks(frame, monkeypatch):
    monkeypatch.setattr(gui, "announce", lambda t: None)
    frame.on_search(None, query="")
    dlg = frame.search_win
    dlg.searched = ("q", "youtube")
    dlg._show("q", "youtube", "YouTube", 1, [
        {"url": "u/old", "title": "Old", "uploaded": "20100101", "views": 50, "duration": 300},
        {"url": "u/none", "title": "Undated"},
        {"url": "u/new", "title": "New", "uploaded": "20250101", "views": 9, "duration": 60}])
    dlg.list.Check(0)  # Old
    names = lambda: [e["title"] for e in dlg.results]  # noqa: E731
    for how, want in (("newest", ["New", "Old", "Undated"]), ("oldest", ["Old", "New", "Undated"]),
                      ("views", ["Old", "New", "Undated"]), ("shortest", ["New", "Old", "Undated"]),
                      ("site", ["Old", "Undated", "New"])):
        dlg.order.SetSelection([k for k, _ in gui.dialogs.ORDERS].index(how))
        dlg.reorder(speak=True)
        assert names() == want, how
        assert [dlg.results[i]["title"] for i in dlg.list.GetCheckedItems()] == ["Old"]
        assert dlg.list.GetString(0).startswith("1. " + want[0])
    dlg.cancel.Command(wx.CommandEvent(wx.wxEVT_BUTTON, wx.ID_CANCEL))
    _drain()


def test_sound_picker_choose_hear_and_cancel(frame, monkeypatch):
    played = []
    monkeypatch.setattr(gui.dialogs.wx, "CallLater", lambda ms, fn, *a: (fn(*a), type("T", (), {"Stop": lambda s: None})())[1])
    import media_download.system as system
    monkeypatch.setattr(system, "play", lambda kind, theme, vol, smap=None: played.append((kind, (smap or {}).get(kind, ""))))
    monkeypatch.setattr(system, "announce", lambda t: None)
    dlg = gui.dialogs.SoundPicker(frame, {"added": "none"}, lambda: "pizzicato", lambda: 0.5)
    keys = dlg.keys
    assert dlg.actions.GetString(keys.index("added")) == "Added to the list: No sound"
    dlg.actions.SetSelection(keys.index("done"))
    dlg.on_action()
    specs = [c for c, _ in dlg.choices]
    dlg.sounds.SetSelection(specs.index("kalimba:update"))
    dlg.on_sound()  # moving in the sounds list chooses; nothing plays by itself
    assert played == []
    dlg.play_now()  # Play, or Return
    assert played[-1] == ("done", "kalimba:update")
    assert dlg.actions.GetString(keys.index("done")) == "Downloads finished: Kalimba: An update is ready"
    assert dlg.chosen_map() == {"added": "none", "done": "kalimba:update"}
    dlg.on_reset()
    assert dlg.chosen_map() == {}
    dlg.Destroy()


def test_settings_fit_the_screen_at_big_text(frame):
    from media_download import textsize
    old = textsize.current
    textsize.current = textsize.default * 2
    try:
        dlg = gui.dialogs.Settings(frame, dict(frame.cfg))
        area = wx.Display(0).GetClientArea()
        assert dlg.GetSize().height <= area.height and dlg.GetSize().width <= area.width
        big = [c for p in dlg.pages for c in p.GetChildren() if isinstance(c, wx.StaticText)]
        assert big and all(c.GetFont().GetPointSize() >= textsize.default * 2 - 1 for c in big)
        dlg.Destroy()
    finally:
        textsize.current = old


def test_settings_sections(frame):
    """Every setting lives in exactly one section; Control-Tab moves on and wraps round."""
    dlg = gui.dialogs.Settings(frame, dict(frame.cfg), section="sounds")
    keys = [k for k, _ in gui.dialogs.SETTINGS_SECTIONS]
    assert dlg.sections.GetCount() == len(dlg.pages) == len(keys)
    assert dlg.book.GetSelection() == keys.index("sounds") == dlg.sections.GetSelection()
    for i in range(len(keys)):
        dlg.show_section(i)
        assert dlg.book.GetSelection() == i
    ev = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    ev.SetKeyCode(wx.WXK_TAB)
    ev.SetRawControlDown(True)
    dlg._on_key(ev)  # from the last section, round to the first
    assert dlg.book.GetSelection() == 0
    # Nothing without a help tag: checkboxes, popups, sliders and buttons all explain themselves.
    for p in dlg.pages:
        for c in p.GetChildren():
            if isinstance(c, (wx.CheckBox, wx.Choice, wx.Slider, wx.Button)):
                assert c.GetToolTipText(), c.GetLabel() or c.GetName()
    dlg.Destroy()


def test_player_menu_from_any_window(frame, monkeypatch):
    said = []
    monkeypatch.setattr(gui, "announce", lambda t: said.append(t))
    frame.player = None
    frame.player_do("toggle")
    assert said[-1].startswith("Nothing is in the player")
    bar = frame.GetMenuBar()
    labels = [bar.GetMenuLabelText(i) for i in range(bar.GetMenuCount())]
    assert "Player" in labels
    from media_download import menus
    keys = [it[2] for it in menus.PLAYER_KEYS if it]
    assert len(keys) == len(set(keys))  # one key, one meaning


def test_speeds_quarter_to_three():
    from media_download import player
    assert player.SPEEDS[0] == 0.25 and player.SPEEDS[-1] == 3.0 and player.SPEEDS[player.NORMAL] == 1.0
    assert player.speed_words(2.5) == "2.5 times" and player.speed_words(1.0) == "Normal"


def test_accounts_window(frame, monkeypatch):
    monkeypatch.setattr(gui, "announce", lambda t: None)
    cfg = dict(frame.cfg, app_signin="")
    dlg = gui.dialogs.AccountsDialog(frame, cfg, lambda b: "checked")
    monkeypatch.setattr(dlg, "EndModal", lambda code: None)
    monkeypatch.setattr(gui.engine, "save_settings", lambda c: None)
    dlg.list.SetSelection(0)
    dlg.act("list")
    assert dlg.result is None  # no browser chosen yet: it says so instead
    dlg.browser.SetSelection(dlg.signin_vals.index("safari"))
    dlg.act("play")
    assert dlg.result == ("play", "https://www.youtube.com/playlist?list=LL") and cfg["app_signin"] == "safari"
    dlg.Destroy()
    frame.cfg["app_signin"] = "firefox"
    try:
        assert frame._job_from_ui("https://x.com/a").cookies == "firefox"
    finally:
        frame.cfg["app_signin"] = ""


def test_guide_walks_through_and_keeps_choices(frame, monkeypatch):
    monkeypatch.setattr(gui.engine, "save_settings", lambda c: None)
    cfg = dict(frame.cfg)
    cfg.pop("app_onboarded", None)
    g = gui.dialogs.Guide(frame, cfg, frame, "welcome")
    ended = []
    monkeypatch.setattr(g, "EndModal", lambda code: ended.append(code))
    seen = []
    for _ in range(12):
        seen.append(g.order[g.at])
        assert g.texts[g.order[g.at]].GetValue().startswith("Step ")  # the step is read first
        if g.order[g.at] == "format":
            g.format.SetSelection([k for k, _ in gui.words.FORMAT_LABELS].index("mp3"))
        if ended:
            break
        g.go(+1)
    # "Not now" for accounts skips the browser, permission and services steps
    assert seen[:5] == ["welcome", "folder", "format", "sounds", "accounts"] and seen[-1] == "done"
    assert "browser" not in seen and cfg["format"] == "mp3" and cfg["app_onboarded"] and ended
    g.Destroy()


def test_play_first_list_has_no_default_and_plays_all(frame):
    entries = [{"url": "https://y.example/%d" % i, "title": "T%d" % i} for i in range(3)]
    dlg = gui.dialogs.CheckList(frame, "Liked", "intro", entries, checked=False, mode="play")
    assert dlg.ok.GetLabel() == "Play All" and dlg.GetDefaultItem() is not dlg.ok
    assert [e["title"] for e in dlg.chosen()] == ["T0", "T1", "T2"] and dlg.choice == "play"
    dlg.list.Check(1)
    dlg._count()
    assert dlg.ok.GetLabel() == "Play Checked (1)" and [e["title"] for e in dlg.chosen()] == ["T1"]
    dlg.Destroy()


def test_window_fits_a_small_screen(frame):
    from media_download import geometry
    area = wx.Display(0).GetClientArea()
    cfg = wx.Config("wavelength-test-geometry")
    cfg.Write("w", "%d,%d,%d,%d" % (area.x + 10, area.y + 10, area.width + 900, area.height + 900))
    assert geometry.restore(frame, cfg, "w")
    r = frame.GetRect()
    assert r.width <= area.width and r.height <= area.height and area.Contains(r.GetTopLeft())
    cfg.DeleteAll()


def test_long_lines_rewrap(frame):
    dlg = wx.Dialog(frame, size=(400, 300))
    t = gui.dialogs.WrapText(dlg, "")
    t.SetLabel("word " * 80)
    assert t.GetLabel() == "word " * 80  # the whole text, whatever the wrapping
    dlg.Destroy()


def test_clipboard_offer_says_how_to_reach_the_field_and_never_repeats(frame, monkeypatch):
    said = []
    monkeypatch.setattr(gui, "announce", lambda t: said.append(t))
    monkeypatch.setattr(frame, "IsActive", lambda: True)
    monkeypatch.setattr(frame, "_modal_open", lambda: False)
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: frame.list))
    frame.link.SetValue("")
    frame.offered = ""
    url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    frame._offer(url)
    assert frame.link.GetValue() == url
    assert said[-1].endswith("%s, then %s, to download it." % (gui.key_words("Ctrl+L"), gui.ENTER))
    # Something already added is never offered back; nor is the same link twice.
    started = []
    monkeypatch.setattr(gui.threading, "Thread", lambda *a, **k: started.append(1) or type(
        "T", (), {"start": lambda self: None})())
    monkeypatch.setattr(frame, "_clipboard_text", lambda: url)
    frame.last_clip = ""
    frame._check_clipboard()
    assert started == []
    # An offer left untouched gives way to a newer link.
    other = "https://soundcloud.com/forss/flickermood"
    monkeypatch.setattr(frame, "_clipboard_text", lambda: other)
    frame._check_clipboard()
    assert started == [1]
    frame.link.SetValue("")


def test_a_failed_search_says_why_and_keeps_more_on_offer(frame, monkeypatch):
    said = []
    from media_download import system
    monkeypatch.setattr(system, "announce", lambda t: said.append(t))
    monkeypatch.setattr(system, "cue", lambda k: None)
    page = gui.dialogs.SearchPage()
    page.error = "The site says too many requests."
    dlg = gui.dialogs.Search(frame, "", "youtube", lambda *a: page)
    dlg.searched, dlg.next_start = ("piano", "youtube"), 1
    dlg._show("piano", "youtube", "YouTube", 1, page)
    assert dlg.status.GetLabel().startswith("The search didn't work.")
    assert "Nothing found" not in said[-1] and dlg.next_start == 1
    dlg.on_done = None
    dlg.Destroy()


def test_opening_and_closing_sounds_follow_settings(frame, monkeypatch):
    played = []
    monkeypatch.setattr(gui, "play", lambda k, *a, **kw: played.append((k, kw.get("wait", False))))
    frame.cfg["app_sounds"] = True
    frame._closing_sound()
    assert played == [("closing", True)]
    frame.cfg["app_sounds"] = False
    frame._closing_sound()
    assert played == [("closing", True)]
    frame.cfg["app_sounds"] = True
    from media_download import system
    assert {"opening", "closing"} <= set(system.SOUND_WORDS)
    for theme, _ in system.THEMES:
        if theme != "system":
            assert system.sound_file("opening", theme).endswith(os.path.join(theme, "opening" + system._ext()))


def test_guide_close_keeps_the_page_and_finish_rings(frame, monkeypatch):
    monkeypatch.setattr(gui.engine, "save_settings", lambda c: None)
    from media_download import system
    rung = []
    monkeypatch.setattr(system, "cue", lambda k: rung.append(k))
    cfg = dict(frame.cfg)
    g = gui.dialogs.Guide(frame, cfg, frame, "welcome")
    monkeypatch.setattr(g, "EndModal", lambda code: None)
    while g.order[g.at] != "format":
        g.go(+1)
    g.format.SetSelection([k for k, _ in gui.words.FORMAT_LABELS].index("mp3"))
    g._close_keeping()  # Close, Escape or the close box, straight from the page
    assert cfg["format"] == "mp3" and rung == []
    g.finish()
    assert rung == ["tour_done"]
    g.Destroy()


def test_describe_lookup_failure_says_why(frame, monkeypatch):
    from media_download import dialogs
    monkeypatch.setattr(dialogs.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda s: None})())
    dlg = dialogs.DescribeDialog(frame, "https://x/v", "Clip", lambda u: {}, {})
    dlg._found({"about": {"title": "Clip", "has_video": False, "can_make": True, "looked_up": False},
                "error": "That isn't available."})
    assert dlg.status.GetLabel() == "Couldn't look up Clip. That isn't available."
    dlg._found({"about": {"title": "Clip", "has_video": True, "can_make": False, "looked_up": True,
                          "needs": "ffmpeg (Help, Get Helper Tools)"}})
    assert any("ffmpeg" in o["words"] for o in dlg.options)
    dlg.Destroy()


def test_choosing_a_section_never_moves_focus(frame, monkeypatch):
    """Arrowing, Control-Tab or Control-Shift-Tab in the Sections list keeps focus there; from
    inside a section that's being hidden it lands on the list, never on the new section's first
    control. Focus is tracked here rather than read from a shown window: a test that shows and
    focuses a window takes the keyboard (and VoiceOver) from whoever is using the Mac."""
    dlg = gui.dialogs.Settings(frame, dict(frame.cfg), section="general")
    focused = [dlg.sections]
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: focused[0]))
    monkeypatch.setattr(wx.Window, "SetFocus", lambda self: focused.__setitem__(0, self))

    def page_switch_steals(i):
        # What wx does by itself when the page changes: focus to the new section's first control.
        focused[0] = next(c for c in dlg.pages[i].GetChildren() if c.AcceptsFocus())

    real = dlg.book.ChangeSelection
    monkeypatch.setattr(dlg.book, "ChangeSelection", lambda i: (real(i), page_switch_steals(i)))

    def settle():
        for _ in range(3):
            wx.Yield()
        return focused[0]
    for i in (2, 3, 1):  # as Up and Down Arrow in the list do it
        dlg.sections.SetSelection(i)
        ev = wx.CommandEvent(wx.wxEVT_LISTBOX, dlg.sections.GetId())
        ev.SetInt(i)
        ev.SetEventObject(dlg.sections)
        dlg.sections.GetEventHandler().ProcessEvent(ev)
        assert settle() is dlg.sections and dlg.book.GetSelection() == i

    def key(shift):
        k = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
        k.SetKeyCode(wx.WXK_TAB)
        k.SetRawControlDown(True)
        k.SetShiftDown(shift)
        dlg._on_key(k)
    key(False)  # Control-Tab from the list
    assert settle() is dlg.sections and dlg.book.GetSelection() == 2
    focused[0] = dlg.theme  # inside the Sounds section
    key(False)
    assert settle() is dlg.sections and dlg.book.GetSelection() == 3
    key(True)  # Control-Shift-Tab from the list: one back
    assert settle() is dlg.sections and dlg.book.GetSelection() == 2
    focused[0] = dlg.theme
    key(True)  # and from inside a section
    assert settle() is dlg.sections and dlg.book.GetSelection() == 1
    dlg.show_section(0)
    key(True)  # from the first section, round to the last
    assert settle() is dlg.sections and dlg.book.GetSelection() == len(dlg.pages) - 1
    dlg.Destroy()


def test_control_tab_says_the_section(frame, monkeypatch):
    """Focus stays put on Control-Tab, so the new section is said, or it sounds like nothing happened."""
    from media_download import system
    said = []
    monkeypatch.setattr(system, "announce", lambda t: said.append(t))
    dlg = gui.dialogs.Settings(frame, dict(frame.cfg), section="general")
    k = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    k.SetKeyCode(wx.WXK_TAB)
    k.SetRawControlDown(True)
    dlg._on_key(k)
    total = len(gui.dialogs.SETTINGS_SECTIONS)
    assert said == ["Downloads, section 2 of %d." % total]
    k.SetShiftDown(True)
    dlg._on_key(k)
    dlg._on_key(k)
    assert said[-1] == "%s, section %d of %d." % (gui.dialogs.SETTINGS_SECTIONS[-1][1], total, total)
    dlg.Destroy()


def test_saving_settings_says_so_in_its_own_window(frame, monkeypatch):
    """Settings saved is a small window of its own, read before the main window is, with its
    sound: nothing guesses how long speech takes."""
    monkeypatch.setattr(gui.engine, "save_settings", lambda c: None)

    class Fake:
        def __init__(self, *a, **k):
            pass

        def ShowModal(self):
            return wx.ID_OK

        def Destroy(self):
            pass
    monkeypatch.setattr(gui.dialogs, "Settings", Fake)
    shown, rung = [], []
    monkeypatch.setattr(gui.dialogs, "message", lambda parent, text, title="Wavelength", button="Got It": shown.append((text, button)))
    monkeypatch.setattr(frame, "_sound", lambda k: rung.append(k))
    frame.on_settings(None)
    assert shown == [("Settings saved.", "Great")] and rung == ["settings_saved"]


def test_leaving_the_tour_early_says_so_in_its_own_window(frame, monkeypatch):
    monkeypatch.setattr(gui.engine, "save_settings", lambda c: None)

    class Fake:
        def __init__(self, *a, **k):
            pass

        def ShowModal(self):
            return wx.ID_CANCEL

        def Destroy(self):
            pass
    monkeypatch.setattr(gui.dialogs, "Guide", Fake)
    shown = []
    monkeypatch.setattr(gui.dialogs, "message", lambda parent, text, title="Wavelength", button="Got It": shown.append((text, button)))
    frame.on_guide("welcome")
    assert shown == [(gui.words.TOUR_LEFT, "Got It")]
    frame.on_guide("accounts")  # Set Up Accounts on its own: nothing to say
    assert shown == [(gui.words.TOUR_LEFT, "Got It")]


def test_tour_leave_button_talks_like_a_person(frame, monkeypatch):
    monkeypatch.setattr(gui.engine, "save_settings", lambda c: None)
    g = gui.dialogs.Guide(frame, dict(frame.cfg), frame, "welcome")
    monkeypatch.setattr(g, "EndModal", lambda code: None)
    assert g.close.GetLabel() == "I'll Take It from Here" and g.close.IsShown()
    assert "I'll Take It from Here" in g.texts["welcome"].GetValue()
    while g.order[g.at] != "done":
        g.go(+1)
    assert not g.close.IsShown() and g.next.GetLabel() == "Let's Do This"  # the way out there
    g.Destroy()
    a = gui.dialogs.Guide(frame, dict(frame.cfg), frame, "accounts")
    assert a.close.GetLabel() == "Maybe Later"
    a.Destroy()


def test_mac_key_monitor_moves_section_only_while_settings_is_in_front(frame, monkeypatch):
    """The Mac never delivers Control-Tab to a window; the app-wide key monitor catches it."""
    from media_download import system
    said = []
    monkeypatch.setattr(system, "announce", lambda t: said.append(t))
    dlg = gui.dialogs.Settings(frame, dict(frame.cfg), section="general")
    ctrl, shift = system.MAC_CONTROL, system.MAC_SHIFT
    monkeypatch.setattr(dlg, "IsActive", lambda: False)
    assert dlg._on_mac_key(system.MAC_TAB, ctrl) is False  # another window in front: not ours
    monkeypatch.setattr(dlg, "IsActive", lambda: True)
    assert dlg._on_mac_key(system.MAC_TAB, 0) is False  # plain Tab moves focus as usual
    assert dlg._on_mac_key(system.MAC_TAB, ctrl | system.MAC_COMMAND) is False
    assert dlg._on_mac_key(system.MAC_TAB, ctrl) is True
    for _ in range(3):
        wx.Yield()
    assert dlg.sections.GetSelection() == 1 and said[-1].startswith("Downloads,")
    assert dlg._on_mac_key(system.MAC_TAB, ctrl | shift) is True
    for _ in range(3):
        wx.Yield()
    assert dlg.sections.GetSelection() == 0 and said[-1].startswith("General,")
    mon = dlg._monitor
    dlg.Destroy()
    for _ in range(3):
        wx.Yield()  # a dialog goes once events are handled
    if sys.platform == "darwin":
        assert mon and mon not in system._monitors  # removed with the window


def test_message_window_answers_with_its_own_button(frame, monkeypatch):
    seen = {}

    def fake_show(dlg):
        seen["buttons"] = [c.GetLabel() for c in dlg.GetChildren() if isinstance(c, wx.Button)]
        seen["escape"] = dlg.GetEscapeId()
        texts = [c for c in dlg.GetChildren() if isinstance(c, (wx.TextCtrl, wx.StaticText))]
        seen["text"] = texts[0].GetValue() if isinstance(texts[0], wx.TextCtrl) else texts[0].GetLabel()
        return wx.ID_OK
    monkeypatch.setattr(wx.Dialog, "ShowModal", fake_show)
    monkeypatch.setattr(gui.dialogs, "message_log", None)  # build it for real; ShowModal is faked
    gui.dialogs.message(frame, "Settings saved.", "Settings", "Great")
    assert seen == {"buttons": ["Great"], "escape": wx.ID_OK, "text": "Settings saved."}


def test_last_tour_step_escape_and_close_both_finish(frame, monkeypatch):
    """The leave button is hidden on the last step, so Escape answers with Let's Do This; and
    closing the window there is finishing (the bell), not leaving early."""
    monkeypatch.setattr(gui.engine, "save_settings", lambda c: None)
    from media_download import system
    rung, ended = [], []
    monkeypatch.setattr(system, "cue", lambda k: rung.append(k))
    g = gui.dialogs.Guide(frame, dict(frame.cfg), frame, "welcome")
    monkeypatch.setattr(g, "EndModal", lambda code: ended.append(code))
    assert g.GetEscapeId() == wx.ID_CANCEL
    while g.order[g.at] != "done":
        g.go(+1)
    assert g.GetEscapeId() == g.next.GetId()
    g._close_keeping()  # the close box on the last step
    assert rung == ["tour_done"] and ended == [wx.ID_OK]
    g.go(-1)
    assert g.GetEscapeId() == wx.ID_CANCEL and g.close.IsShown()
    g.Destroy()


def test_words_in_the_link_field_point_to_search(frame, monkeypatch):
    """The main window takes links; searching is the Search window's job (Matthew, 2026-10-14)."""
    said, searched = [], []
    monkeypatch.setattr(gui, "announce", lambda t: said.append(t))
    monkeypatch.setattr(frame, "on_search", lambda *a, **k: searched.append(k))
    frame.link.SetValue("green onions")
    frame.on_download(None)
    frame.on_play_link()
    frame.add_from_text("just some words")
    assert searched == [] and said == [gui.words.NOT_A_LINK] * 3
    assert frame.link.GetValue() == "green onions"  # kept, ready for Search to take
    frame.link.SetValue("")
