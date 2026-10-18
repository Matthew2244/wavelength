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
    gui.dialogs.Search.PREFETCH = False  # these tests feed pages by hand; one test turns it back on
    gui.manager_mod.SPARE = False  # no waiting worker started by the window's own checks
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
    monkeypatch.setattr(gui, "announce", lambda t, *polite: said.append(t))
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
    monkeypatch.setattr(gui, "announce", lambda t, *polite: said.append(t))

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
    assert words.pretty_folder(d) == "Downloads" + os.sep + "Media Downloads"


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
    monkeypatch.setattr(gui, "announce", lambda t, *polite: said.append(t))
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
    monkeypatch.setattr(frame, "greeting", "")  # greetings switched off in Settings
    assert frame.welcome().startswith("Welcome to Wavelength, Matthew.")
    monkeypatch.setattr(gui.words, "first_name", lambda: "")
    assert frame.welcome().startswith("Welcome to Wavelength.")
    monkeypatch.setattr(frame, "greeting", "Good morning, Matthew.")  # on: today's hello comes first
    assert frame.welcome().startswith("Good morning, Matthew.\n\nWelcome to Wavelength.")


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
    monkeypatch.setattr(gui, "announce", lambda t, *a: None)
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
    monkeypatch.setattr(gui, "announce", lambda t, *a: None)
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
    monkeypatch.setattr(gui, "announce", lambda t, *a: None)
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
    monkeypatch.setattr(gui, "announce", lambda t, *a: None)
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
    monkeypatch.setattr(gui, "announce", lambda t, *a: None)
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
    monkeypatch.setattr(gui, "announce", lambda t, *a: None)
    monkeypatch.setattr(gui.dialogs, "announce", lambda t, *a: None, raising=False)
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
    monkeypatch.setattr(gui, "announce", lambda t, *a: None)
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
    monkeypatch.setattr(gui, "announce", lambda t, *a: None)
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
    monkeypatch.setattr(gui, "announce", lambda t, *a: None)
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
    monkeypatch.setattr(system, "announce", lambda t, *a: None)
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
    monkeypatch.setattr(gui, "announce", lambda t, *polite: said.append(t))
    frame.player = None
    frame.player_do("toggle")
    assert said[-1].startswith("Nothing is in the player")
    bar = frame.GetMenuBar()
    labels = [bar.GetMenuLabelText(i) for i in range(bar.GetMenuCount())]
    assert "Player" in labels
    from media_download import menus
    keys = [it[2] for it in menus.PLAYER_KEYS if it]
    assert len(keys) == len(set(keys))  # one key, one meaning


def test_player_keys_mean_the_same_on_mac_and_windows():
    """A Command-Option key on the Mac and the Control-Alt key on Windows with the same letter must
    do the same thing: Control-Alt-Period was Forward on the Mac and Faster on Windows."""
    from media_download import menus
    mac = {k: a for _, a, k in filter(None, menus.player_keys(False))}
    win = {k: a for _, a, k in filter(None, menus.player_keys(True))}
    assert len(mac) == len(set(mac.values())) and len(win) == len(set(win.values()))
    for key in set(mac) & set(win):
        assert mac[key] == win[key], key


def _menu_keys(win, out):
    def walk(menu):
        for it in menu.GetMenuItems():
            if it.GetSubMenu():
                walk(it.GetSubMenu())
                continue
            label = it.GetItemLabel()
            if "\t" in label:
                name, key = label.split("\t", 1)
                out.setdefault(key, set()).add(name.replace("&", "").rstrip("."))
    bar = win.GetMenuBar()
    for i in range(bar.GetMenuCount()):
        walk(bar.GetMenu(i))


# Keys more than one window has, each meaning the same thing in each (Matthew, 2026-10-14: "there
# needs to be distinction between all keyboard shortcuts"). A key not listed here may have only
# one name in the whole app; a new window reusing a key for something else fails this.
SAME_IN_EVERY_WINDOW = {
    "Ctrl+D": {"Go to Downloads List", "Go to the Results"},
    "Ctrl+L": {"Go to Link Field", "Go to the Search Field"},
    "Ctrl+F": {"Search"},
    "Ctrl+K": {"Actions for the Selected Download", "Actions for the Selected Result",
               "Actions for the Selected Queue Item"},
    "Ctrl+R": {"Show in Finder", "Show in File Explorer", "Show the File"},
    "Ctrl+Return": {"Download Link", "Download Checked", "Download This"},
    "Ctrl+Shift+A": {"Audio Description", "Find or Make Audio Description"},
    "Ctrl+W": {"Close Window", "Close Search", "Close Player"},
    "Ctrl+P": {"Play or Pause", "Play or Pause Selected"},
}


def test_every_shortcut_means_one_thing(frame):
    from media_download import player
    dlg = gui.dialogs.Search(frame, "", "youtube", lambda *a: [])
    pl = player.PlayerFrame(frame)
    try:
        keys = {}
        for w in (frame, dlg, pl):
            _menu_keys(w, keys)
    finally:
        pl.timer.Stop()
        pl.Destroy()
        dlg.on_done = None
        dlg.Destroy()
    for key, names in keys.items():
        if len(names) > 1:
            assert names <= SAME_IN_EVERY_WINDOW.get(key, set()), (key, names)
    # The player keeps none of the main window's list keys for itself
    for key in ("Ctrl+Up", "Ctrl+Down", "Ctrl+Shift+Up", "Ctrl+Shift+Down", "Ctrl+Left", "Ctrl+Right"):
        assert len(keys.get(key, ())) <= 1, key


def test_menu_letters_are_unique_in_each_menu(frame):
    """Windows' Alt letters: two items with one letter in a menu cycle between them instead of
    choosing (Stop All and Play All Finished were both A)."""
    from media_download import player
    dlg = gui.dialogs.Search(frame, "", "youtube", lambda *a: [])
    pl = player.PlayerFrame(frame)

    def check(menu, where):
        seen = {}
        for it in menu.GetMenuItems():
            label = it.GetItemLabel().split("\t")[0]
            if "&" in label:
                letter = label[label.index("&") + 1].lower()
                assert letter not in seen, (where, seen[letter], label)
                seen[letter] = label
            if it.GetSubMenu():
                check(it.GetSubMenu(), where)
    try:
        for w in (frame, dlg, pl):
            bar = w.GetMenuBar()
            for i in range(bar.GetMenuCount()):
                check(bar.GetMenu(i), bar.GetMenuLabelText(i))
    finally:
        pl.timer.Stop()
        pl.Destroy()
        dlg.on_done = None
        dlg.Destroy()


def test_player_arrows_and_page_keys(frame, monkeypatch):
    """Left and Right skip, Up and Down the volume (Shift: small steps), Page Up and Down the item."""
    from media_download import player
    monkeypatch.setattr(player.engine, "save_settings", lambda c: None)
    monkeypatch.setattr(player, "announce", lambda t, *a: None)
    pl = player.PlayerFrame(frame)
    try:
        monkeypatch.setattr(pl, "FindFocus", lambda: pl.play_btn)
        went = []
        monkeypatch.setattr(pl, "go", lambda step: went.append(step))
        pl.set_volume(0.5)
        pl.on_key(_press(wx.WXK_UP))
        assert pl.base_volume == 0.6
        pl.on_key(_press(wx.WXK_DOWN, shift=True))
        assert pl.base_volume == 0.58
        pl.on_key(_press(wx.WXK_PAGEDOWN))
        pl.on_key(_press(wx.WXK_PAGEUP))
        assert went == [1, -1]
        # In the queue list the arrows and Page keys move through the list instead
        monkeypatch.setattr(pl, "FindFocus", lambda: pl.qlist)
        pl.on_key(_press(wx.WXK_UP))
        pl.on_key(_press(wx.WXK_PAGEDOWN))
        assert pl.base_volume == 0.58 and went == [1, -1]
    finally:
        pl.timer.Stop()
        pl.Destroy()


def test_speeds_quarter_to_three():
    from media_download import player
    assert player.SPEEDS[0] == 0.25 and player.SPEEDS[-1] == 3.0 and player.SPEEDS[player.NORMAL] == 1.0
    assert player.speed_words(2.5) == "2.5 times" and player.speed_words(1.0) == "Normal"


def test_accounts_window(frame, monkeypatch):
    monkeypatch.setattr(gui, "announce", lambda t, *a: None)
    monkeypatch.setattr(gui.accounts, "installed", lambda: [("safari", "Safari"), ("chrome", "Google Chrome"),
                                                            ("firefox", "Firefox")])
    cfg = dict(frame.cfg, app_signin="")
    cfg.pop("app_signins", None)
    dlg = gui.dialogs.AccountsDialog(frame, cfg, lambda b: "checked")
    monkeypatch.setattr(dlg, "EndModal", lambda code: None)
    monkeypatch.setattr(gui.engine, "save_settings", lambda c: None)
    monkeypatch.setattr(gui.accounts, "has_own_signin", lambda: False)
    dlg.list.SetSelection(0)
    dlg.act("list")
    assert dlg.result is None  # no browser chosen yet: it says so instead
    assert dlg.status.GetLabel() == gui.dialogs.NOT_SIGNED_IN
    found = [k for k, _ in dlg.choices.found]
    dlg.choices.list.Check(found.index("safari"))
    dlg.choices.list.Check(found.index("chrome"))
    dlg.choices.save()
    dlg.act("play")
    assert dlg.result == ("play", "https://www.youtube.com/playlist?list=LL") and cfg["app_signin"] == "safari"
    assert cfg["app_signins"] == ["safari", "chrome"]  # Safari first, the list's own order
    assert gui.accounts.signin(cfg) == "safari|chrome"
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
    monkeypatch.setattr(gui, "announce", lambda t, *polite: said.append(t))
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
    monkeypatch.setattr(system, "announce", lambda t, *polite: said.append(t))
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
    monkeypatch.setattr(system, "announce", lambda t, *polite: said.append(t))
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
    monkeypatch.setattr(system, "announce", lambda t, *polite: said.append(t))
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
        assert mon and mon not in system._key_handlers  # removed with the window
        assert system._key_monitor  # the native monitor stays: removing it crashed the app


def test_settings_open_and_close_many_times_does_not_crash(frame, monkeypatch):
    """Saving Settings crashed the Mac app (2026-10-14): the key monitor's block was freed while
    macOS still held it. Open and close Settings repeatedly, draining events each time."""
    from media_download import dialogs, system
    for _ in range(6):
        dlg = dialogs.Settings(frame, dict(frame.cfg))
        dlg.Show()
        for _ in range(3):
            wx.Yield()
        dlg.Destroy()
        for _ in range(3):
            wx.Yield()
    if sys.platform == "darwin":
        assert not system._key_handlers


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
    monkeypatch.setattr(gui, "announce", lambda t, *polite: said.append(t))
    monkeypatch.setattr(frame, "on_search", lambda *a, **k: searched.append(k))
    frame.link.SetValue("green onions")
    frame.on_download(None)
    frame.on_play_link()
    frame.add_from_text("just some words")
    assert searched == [] and said == [gui.words.NOT_A_LINK] * 3
    assert frame.link.GetValue() == "green onions"  # kept, ready for Search to take
    frame.link.SetValue("")


@pytest.mark.skipif(sys.platform != "darwin", reason="VoiceOver's view of a Mac table")
def test_check_list_rows_read_once(frame):
    """A checkable row's checkbox carries the row's words and the text beside it says nothing,
    so VoiceOver reads each search result once, not "So What, unchecked checkbox, So What"."""
    from media_download.system import _objc_send, mac_check_list_reads_once
    ctypes, send = _objc_send()
    lst = wx.CheckListBox(frame, choices=["1. So What", "2. All Blues"])
    mac_check_list_reads_once(lst)
    lst.Set(["1. Blue in Green", "2. All Blues"])  # rows are named afresh when the words change
    lst.Check(1)
    table = send(lst.GetHandle(), "documentView")

    def ax(element, name):
        s = send(ctypes.c_void_p(_nsstring_class()), "stringWithUTF8String:", name.encode(),
                 argtypes=(ctypes.c_char_p,))
        return send(element, "accessibilityAttributeValue:", s, argtypes=(ctypes.c_void_p,))

    def text(obj):
        if not obj:
            return None
        return send(send(obj, "description"), "UTF8String", restype=ctypes.c_char_p).decode()

    def _nsstring_class():
        import ctypes.util
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        return objc.objc_getClass(b"NSString")

    rows = ax(table, "AXRows")
    seen = []
    for r in range(send(rows, "count", restype=ctypes.c_ulong)):
        row = send(rows, "objectAtIndex:", r, argtypes=(ctypes.c_ulong,))
        kids = ax(row, "AXChildren")
        cells = [send(kids, "objectAtIndex:", k, argtypes=(ctypes.c_ulong,))
                 for k in range(send(kids, "count", restype=ctypes.c_ulong))]
        seen.append([(text(ax(c, "AXRole")), text(ax(c, "AXDescription")), text(ax(c, "AXValue"))) for c in cells])
    lst.Destroy()
    assert seen == [[("AXCheckBox", "1. Blue in Green", "0"), ("AXTextField", None, "")],
                    [("AXCheckBox", "2. All Blues", "1"), ("AXTextField", None, "")]]


def _press(code=0, uni=0, shift=False, alt=False, cmd=False, ctrl=False):
    k = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    k.SetKeyCode(code)
    k.SetUnicodeKey(uni)
    k.SetShiftDown(shift)
    k.SetAltDown(alt)
    k.SetControlDown(cmd)
    k.SetRawControlDown(ctrl)
    return k


def test_speed_keys_on_any_layout():
    from media_download.player import speed_key
    # US: the bare keys
    assert speed_key(_press(ord("["), ord("["))) == "slower"
    assert speed_key(_press(ord("]"), ord("]"))) == "faster"
    assert speed_key(_press(ord("\\"), ord("\\"))) == "normal"
    assert speed_key(_press(ord("N"), ord("n"))) == "normal"
    # < and >: by character, and by Shift-Comma / Shift-Period when only the key code is known
    assert speed_key(_press(ord(","), ord("<"), shift=True)) == "slower"
    assert speed_key(_press(ord("."), ord(">"), shift=True)) == "faster"
    assert speed_key(_press(ord(","), 0, shift=True)) == "slower"
    assert speed_key(_press(ord("."), 0, shift=True)) == "faster"
    # German Mac: [ is Option-5, < has its own key
    assert speed_key(_press(ord("5"), ord("["), alt=True)) == "slower"
    assert speed_key(_press(ord("<"), ord("<"))) == "slower"
    # Not speed: plain comma and period, Option-N (an accent), and anything with Command or Control
    assert speed_key(_press(ord(","), ord(","))) is None
    assert speed_key(_press(ord("N"), 0, alt=True)) is None
    assert speed_key(_press(ord("]"), ord("]"), cmd=True)) is None
    assert speed_key(_press(ord("N"), ord("n"), ctrl=True)) is None
    assert speed_key(_press(ord("T"), ord("t"))) is None


def test_player_speed_keys_and_ends(frame, monkeypatch):
    from media_download import player
    monkeypatch.setattr(player.engine, "save_settings", lambda c: None)
    said = []
    monkeypatch.setattr(player, "announce", lambda t, *polite: said.append(t))
    pl = player.PlayerFrame(frame)
    try:
        monkeypatch.setattr(pl, "FindFocus", lambda: pl.play_btn)
        pl.set_speed(1.0)
        pl.on_key(_press(ord("]"), ord("]")))
        assert pl.speed == 1.1 and said[-1] == "Speed: 1.1 times."
        pl.on_key(_press(ord(","), ord("<"), shift=True))
        assert pl.speed == 1.0
        pl.on_key(_press(ord("."), ord(">"), shift=True))
        pl.on_key(_press(ord("N"), ord("n")))
        assert pl.speed == 1.0 and said[-1] == "Speed: Normal."
        pl.set_speed(3.0)
        pl.on_key(_press(ord("]"), ord("]")))
        assert pl.speed == 3.0 and said[-1] == "Fastest, 3 times."
        pl.set_speed(0.25)
        pl.on_key(_press(ord("["), ord("[")))
        assert said[-1] == "Slowest, 0.25 times."
        # Typing in a text field is typing, not speed
        field = wx.TextCtrl(pl.panel)
        monkeypatch.setattr(pl, "FindFocus", lambda: field)
        pl.on_key(_press(ord("N"), ord("n")))
        assert pl.speed == 0.25
    finally:
        pl.set_speed(1.0)
        pl.timer.Stop()  # the app's own close stops it; a bare Destroy leaves it firing
        pl.Destroy()


class _FakeMedia:
    def __init__(self, playing):
        self.calls, self._playing = [], playing

    def Play(self):
        self.calls.append("Play")

    def SetPlaybackRate(self, r):
        self.calls.append(("rate", r))

    def GetState(self):
        return wx.media.MEDIASTATE_PLAYING if self._playing else wx.media.MEDIASTATE_PAUSED


def test_player_starts_at_speed_in_one_step(frame, monkeypatch):
    """Play then a rate, back to back, froze the Mac's media clock 7 times in 12; a paused player
    must stay paused when the speed changes (a rate alone starts it on the Mac)."""
    import wx.media  # noqa: F401
    from media_download import player
    monkeypatch.setattr(player.engine, "save_settings", lambda c: None)
    monkeypatch.setattr(player, "announce", lambda t, *a: None)
    pl = player.PlayerFrame(frame)
    real = pl.media
    try:
        for plat, speed, want in [("darwin", 1.5, [("rate", 1.5)]), ("darwin", 1.0, ["Play"]),
                                  ("win32", 1.5, ["Play", ("rate", 1.5)]), ("win32", 1.0, ["Play"])]:
            monkeypatch.setattr(player.sys, "platform", plat)
            pl.media, pl.speed = _FakeMedia(False), speed
            pl._play()
            assert pl.media.calls == want, (plat, speed)
        pl.loaded = True
        pl.media = _FakeMedia(False)
        pl._apply_rate()
        assert pl.media.calls == []  # paused stays paused; Play applies the speed later
        pl.media = _FakeMedia(True)
        pl._apply_rate()
        assert pl.media.calls == [("rate", pl.speed)]
    finally:
        pl.media, pl.loaded = real, False
        pl.timer.Stop()  # the app's own close stops it; a bare Destroy leaves it firing
        pl.Destroy()


def test_search_fetches_the_next_page_ahead(frame, monkeypatch):
    """More is instant: the next page is fetched while the person reads this one."""
    import threading
    monkeypatch.setattr(gui, "announce", lambda t, *a: None)
    monkeypatch.setattr(gui.dialogs.Search, "PREFETCH", True)
    frame.on_search(None, query="")
    dlg = frame.search_win
    page = gui.dialogs.SEARCH_PAGE
    asked, gate = [], threading.Event()

    def fake_search(q, site_key, start, count=page):
        asked.append(start)
        if start == 2 * page + 1:
            gate.wait(5)  # the page after next is still on its way when More is pressed
        return [{"url": "https://y.example/%d" % n, "title": "R%d" % n} for n in range(start, start + page)]
    dlg.run_search = fake_search
    dlg.query.SetValue("organ")
    dlg.on_search(None)
    for _ in range(50):
        _drain()
        if len(asked) >= 2 and getattr(dlg, "ahead", None) and dlg.ahead["done"]:
            break
    assert asked == [1, page + 1] and len(dlg.results) == page  # page 2 fetched, not shown
    dlg.more()
    _drain()
    assert len(dlg.results) == 2 * page and not dlg.loading  # served from what was fetched ahead
    for _ in range(50):
        _drain()
        if 2 * page + 1 in asked:
            break
    dlg.more()  # page 3 is still coming: More waits for it rather than asking twice
    assert dlg.loading
    gate.set()
    for _ in range(100):
        _drain()
        if len(dlg.results) == 3 * page:
            break
    assert len(dlg.results) == 3 * page and asked.count(2 * page + 1) == 1
    dlg.Destroy()
    _drain()


def test_a_waiting_worker_is_used_once_and_only_while_it_matches(monkeypatch):
    from media_download import manager
    started = []

    class FakeProc:
        def __init__(self):
            self.stdin, self.alive, self.got = self, True, []
            started.append(self)

        def write(self, text):
            self.got.append(text)

        def close(self):
            pass

        def poll(self):
            return None if self.alive else 0
    monkeypatch.setattr(manager, "SPARE", True)
    monkeypatch.setattr(manager, "_start_worker", FakeProc)
    monkeypatch.setattr(manager, "_kill", lambda p: setattr(p, "alive", False))
    monkeypatch.setattr(manager, "_spare", {"proc": None, "key": None})
    engines = [("2026.8.19", "/x")]
    monkeypatch.setattr(manager.engine, "installed_engines", lambda: list(engines))
    manager.warm()
    spare = started[0]
    p = manager._popen({"task": "search"})
    assert p is spare and spare.got and len(started) == 2  # used, and the next one started
    engines.insert(0, ("2026.9.1", "/y"))  # the engine updated while the next one waited
    p2 = manager._popen({"task": "probe"})
    assert p2 is not started[1] and not started[1].alive  # the stale one is never used
    monkeypatch.setattr(manager, "SPARE", False)
    manager._drop_spare()


def test_a_last_failure_keeps_its_reason_in_the_summary(frame, monkeypatch):
    """The batch summary used to cut the failure's reason off 0.3 s in: now it carries it."""
    bad = job("failed", "Rehearsal", reason="That one is for members only.")
    said = finish(frame, monkeypatch, [bad], busy=False, batch_total=3, counts={"done": 2, "failed": 1})
    assert said == []  # nothing said yet: the summary says it
    later = []
    monkeypatch.setattr(gui.wx, "CallLater", lambda ms, fn, *a: later.append((fn, a)))
    monkeypatch.setattr(frame, "RequestUserAttention", lambda *a: None)
    frame._all_done({"done": 2, "failed": 1, "took": 1})
    for fn, a in later:
        fn(*a)
    assert said == ["All downloads finished: 2 done, 1 failed. Failed: Rehearsal. That one is for members only."]


def test_your_accounts_is_the_one_way_in(frame, monkeypatch):
    """No browser chosen: the setup steps first, Your Accounts after them only if they finished
    with a browser. File has one accounts item, not two."""
    labels = [i.GetItemLabelText() for i in frame.GetMenuBar().GetMenu(0).GetMenuItems()]
    assert "Your Accounts..." in labels and not any("Set Up Accounts" in l for l in labels)
    opened = []

    class FakeGuide:
        def __init__(self, parent, cfg, main, start, opens_accounts=False):
            assert start == "accounts" and opens_accounts
            self.cfg = cfg

        def ShowModal(self):
            opened.append("guide")
            self.cfg["app_signin"] = choose[0]
            return wx.ID_OK if choose[0] else wx.ID_CANCEL

        def Destroy(self):
            pass

    class FakeAccounts:
        result = None

        def __init__(self, *a, **k):
            opened.append("accounts")

        def ShowModal(self):
            return wx.ID_CANCEL

        def Destroy(self):
            pass
    monkeypatch.setattr(gui.dialogs, "Guide", FakeGuide)
    monkeypatch.setattr(gui.dialogs, "AccountsDialog", FakeAccounts)
    try:
        frame.cfg["app_signin"] = ""
        choose = [""]
        frame.on_accounts()
        assert opened == ["guide"]  # left without a browser: nothing more
        choose[0] = "safari"
        opened.clear()
        frame.on_accounts()
        assert opened == ["guide", "accounts"]
        opened.clear()
        frame.on_accounts()  # set up already: straight to your things
        assert opened == ["accounts"]
    finally:
        frame.cfg["app_signin"] = ""


def test_accounts_setup_says_what_comes_next(frame, monkeypatch):
    monkeypatch.setattr(gui.engine, "save_settings", lambda c: None)
    for opens, expect in ((True, "Your Accounts opens next"), (False, None)):
        g = gui.dialogs.Guide(frame, dict(frame.cfg, app_signin="safari"), frame, "accounts", opens_accounts=opens)
        monkeypatch.setattr(g, "EndModal", lambda code: None)
        g.show(g.order.index("done"))
        text = g.texts["done"].GetValue()
        assert "Safari's sign-in" in text and "Paste a link" not in text  # the tour's tail isn't for here
        assert (expect in text) if expect else ("opens next" not in text)
        g.Destroy()
    g = gui.dialogs.Guide(frame, dict(frame.cfg, app_signin=""), frame, "accounts")
    g.show(g.order.index("done"))
    assert "Your Accounts" in g.texts["done"].GetValue() and "Set Up Accounts" not in g.texts["done"].GetValue()
    g.Destroy()


def test_accounts_window_names_the_browser_and_offers_setup(frame, monkeypatch):
    monkeypatch.setattr(gui.engine, "save_settings", lambda c: None)
    monkeypatch.setattr(gui.accounts, "has_own_signin", lambda: False)
    cfg = dict(frame.cfg, app_signin="safari")
    cfg.pop("app_signins", None)
    dlg = gui.dialogs.AccountsDialog(frame, cfg, lambda b: "checked", main=frame)
    assert dlg.status.GetLabel().startswith("Using Safari's sign-in.") and dlg.setup_b is not None
    assert gui.dialogs.CMD + "-K" in dlg.status.GetLabel()

    class FakeGuide:
        def __init__(self, parent, c, main, start):
            self.c = c

        def ShowModal(self):
            gui.accounts.set_browsers(self.c, ["firefox"])

        def Destroy(self):
            pass
    monkeypatch.setattr(gui.dialogs, "Guide", FakeGuide)
    dlg.on_setup()
    assert dlg._browser() == "firefox" and "Firefox" in dlg.status.GetLabel()
    dlg.Destroy()
    plain = gui.dialogs.AccountsDialog(frame, cfg, lambda b: "x")
    assert plain.setup_b is None  # no main: no setup button
    plain.Destroy()


def test_settings_walk_through_keeps_its_choice(frame, monkeypatch):
    cfg = dict(frame.cfg, app_signin="")
    dlg = gui.dialogs.Settings(frame, cfg)

    class FakeGuide:
        def __init__(self, parent, c, main, start):
            self.c = c

        def ShowModal(self):
            gui.accounts.set_browsers(self.c, ["safari"])

        def Destroy(self):
            pass
    monkeypatch.setattr(gui.dialogs, "Guide", FakeGuide)
    dlg.on_walk_through()
    monkeypatch.setattr(dlg, "EndModal", lambda code: None)
    dlg.on_ok(None)
    assert cfg["app_signin"] == "safari"  # Save never puts the old choice back
    dlg.Destroy()


def test_refused_with_signin_points_at_retry_not_more_options():
    said = gui.words.explain_failure("Sign in to confirm you're not a bot", True, "YouTube")
    assert "Retry Using a Browser's Sign-in" in said and "More Options" not in said and "YouTube" in said


def test_retry_goes_to_the_folder_the_window_shows(frame, monkeypatch, tmp_path):
    monkeypatch.setattr(gui, "announce", lambda t, *a: None)
    retried = []
    monkeypatch.setattr(frame.mgr, "retry", lambda j: retried.append(j.dest))
    j = job("failed", "Gone", dest="/Volumes/Unplugged/Music")
    saved = job("stopped", "Half", dest="/Volumes/Unplugged/Music", files=["/x.mp3"])
    old = frame.cfg["to"]
    frame.cfg["to"] = str(tmp_path)
    try:
        for x in (j, saved):
            monkeypatch.setattr(frame, "selected", lambda x=x: x)
            frame.on_retry(None)
        assert retried == [str(tmp_path), "/Volumes/Unplugged/Music"]  # a row with a file stays with it
    finally:
        frame.cfg["to"] = old


def test_commands_never_answer_with_silence(frame, monkeypatch):
    said = []
    monkeypatch.setattr(frame, "tell", lambda t, *a, **k: said.append(t))
    monkeypatch.setattr(frame, "selected", lambda: None)
    for cmd in (frame.on_stop, frame.on_retry, frame.on_copy_link, frame.on_remove, frame.on_show):
        cmd(None)
    frame.on_move(-1)
    assert said == ["Select a download first."] * 6
    said.clear()
    done = job("done", "Song")
    monkeypatch.setattr(frame, "selected", lambda: done)
    frame.on_stop(None)
    frame.on_retry(None)
    assert said == ["That one isn't downloading.", "That one hasn't failed or stopped, so there's nothing to retry."]
    labels = [i.GetItemLabelText() for i in frame.GetMenuBar().GetMenu(2).GetMenuItems()]
    assert "Find or Make Audio Description..." in labels


def test_a_playlist_can_be_played_instead(frame, monkeypatch):
    monkeypatch.setattr(gui, "announce", lambda t, *a: None)

    class FakePQ(gui.dialogs.PlaylistQuestion):
        def __init__(self, *a, **k):
            pass

        def ShowModal(self):
            return self.PLAY

        def Destroy(self):
            pass
    monkeypatch.setattr(gui.dialogs, "PlaylistQuestion", FakePQ)
    played, removed = [], []
    monkeypatch.setattr(gui.wx, "CallAfter", lambda fn, *a: fn(*a))
    monkeypatch.setattr(frame, "play_links", lambda entries: played.extend(entries))
    monkeypatch.setattr(frame.mgr, "remove", lambda j: removed.append(j))
    j = job("waiting_choice", "Album", cookies="safari")
    frame._ask_playlist(j, {"title": "Album", "entries": [{"url": "https://x.com/1", "title": "One"},
                                                          {"url": "https://x.com/2", "title": "Two"}]})
    assert removed == [j] and [e["title"] for e in played] == ["One", "Two"]
    assert all(e["cookies"] == "safari" for e in played)


def test_advice_outside_a_download_never_points_at_retry():
    logs = ["ERROR: Sign in to confirm you're not a bot", "ERROR: HTTP Error 429: Too Many Requests",
            "ERROR: HTTP Error 503", "ERROR: Login required", "ERROR: [Errno 60] Operation timed out"]
    for log in logs:
        said = gui.words.explain_failure(log, False, "YouTube", for_download=False)
        assert "Retry" not in said, said
    assert "File, Your Accounts" in gui.words.explain_failure(logs[0], False, "YouTube", for_download=False)
    assert "Retry Using" in gui.words.explain_failure(logs[0], False, "YouTube")  # a download keeps it


def test_a_404_in_a_video_id_is_not_a_404():
    said = gui.words.explain_failure("ERROR: [youtube] x404Abcdefg: Some other failure", False, "YouTube")
    assert "isn't available" not in said
    assert "isn't available" in gui.words.explain_failure("ERROR: HTTP Error 404: Not Found", False, "YouTube")
    assert gui.words.worth_updating_for("ERROR: [youtube] geoffrey: Unable to extract player")


def test_streams_are_named_not_coded():
    w = gui.words.describe_format({"vcodec": "avc1.64001F", "acodec": "mp4a.40.2", "height": 720})
    assert w.startswith("Video 720p with sound, H.264, plays everywhere")
    assert "?p" not in gui.words.describe_format({"vcodec": "vp09.00", "acodec": "none"})
    assert "Opus" in gui.words.describe_format({"vcodec": "none", "acodec": "opus", "abr": 130})


def test_a_new_search_keeps_what_was_checked(frame, monkeypatch):
    monkeypatch.setattr(gui, "announce", lambda t, *a: None)
    dlg = gui.dialogs.Search(frame, "", "youtube", lambda *a: [])
    monkeypatch.setattr(dlg, "_fetch", lambda *a: None)
    dlg.searched = ("piano", "youtube")
    dlg._show("piano", "youtube", "YouTube", 1, [{"url": "https://y.example/1", "title": "One"},
                                                 {"url": "https://y.example/2", "title": "Two"}])
    dlg.list.Check(1)
    dlg.query.SetValue("organ")
    dlg.on_search(None)
    assert [e["title"] for e in dlg.chosen()] == ["Two"] and "1 checked result from before is kept" in \
        dlg.status.GetLabel()
    assert dlg.ok.GetLabel() == "Download Checked (1)"
    gui.dialogs._check_range(dlg, dlg.list, 0, dlg.list.GetCount(), False)  # Uncheck All means all
    assert dlg.chosen() == []
    dlg._finish([])
    _drain()


def test_choose_items_can_play_instead(frame, monkeypatch):
    entries = [{"url": "https://y.example/%d" % i, "title": "T%d" % i} for i in range(3)]
    dlg = gui.dialogs.CheckList(frame, "Album", "intro", entries, checked=False)
    monkeypatch.setattr(dlg, "EndModal", lambda code: None)
    monkeypatch.setattr(gui.dialogs, "announce", lambda t, *a: None, raising=False)
    dlg._play_instead()
    assert dlg.choice == "download"  # nothing checked: it says so
    dlg.list.Check(2)
    dlg._play_instead()
    assert dlg.choice == "play" and [e["title"] for e in dlg.chosen()] == ["T2"]
    dlg.Destroy()
    from media_download import system
    assert not system._key_handlers


def test_describe_window_offers_what_you_have_and_make_from_any_row(frame, monkeypatch):
    done = []
    acts = {"make": lambda: done.append("make"), "have_play": lambda: done.append("have")}
    monkeypatch.setattr(gui.dialogs, "in_background", lambda work, ok, bad: None)
    dlg = gui.dialogs.DescribeDialog(frame, "https://y.example/v", "Film", None, acts, have=True)
    monkeypatch.setattr(dlg, "EndModal", lambda code: None)
    dlg._found({"about": {"title": "Film", "has_video": True, "can_make": True},
                "candidates": [{"url": "https://y.example/d", "title": "Film (described)"}]})
    assert dlg.options[0]["kind"] == "have" and dlg.list.GetSelection() == 0
    assert dlg.make_btn.IsEnabled() and dlg.play_btn.IsEnabled()
    dlg._act("play")
    dlg.list.SetSelection(1)  # a published version selected, Make still makes
    dlg._act("make")
    assert done == ["have", "make"]
    dlg.Destroy()


def test_player_live_skip_says_so_and_menu_shows_state(frame, monkeypatch):
    from media_download import player
    monkeypatch.setattr(player.engine, "save_settings", lambda c: None)
    said = []
    monkeypatch.setattr(player, "announce", lambda t, *a: said.append(t))
    pl = player.PlayerFrame(frame)
    try:
        monkeypatch.setattr(pl, "say", lambda t: said.append(t))
        pl.item, pl.loaded = {"url": "https://radio.example/live", "live": True}, True
        pl.skip(10)
        assert said[-1].startswith("This is live")
        pl._update_buttons()
        assert not pl.back_btn.IsEnabled() and not pl.fwd_btn.IsEnabled()
        pl.captions_on = True
        pl.toggle_captions()
        assert not pl.captions_item.IsChecked()
        pl.ad_cues, pl.loaded = [], False
        pl.set_ad("off")
        assert pl.ad_mode == "off" and pl.ad_items["off"].IsChecked()
        pl.sleep_end_of_item = True
        pl.say_levels()
        assert "stops at the end of this item" in said[-1]
    finally:
        pl.sleep_end_of_item = False
        pl.item, pl.loaded = None, False
        pl.timer.Stop()


# ---------------------------------------------------------------- sign-ins (3.11)

def test_guide_with_several_browsers_asks_for_each_and_offers_sign_in_here(frame, monkeypatch):
    monkeypatch.setattr(gui.engine, "save_settings", lambda c: None)
    monkeypatch.setattr(gui.accounts, "installed", lambda: [("safari", "Safari"), ("chrome", "Google Chrome"),
                                                            ("firefox", "Firefox")])
    cfg = dict(frame.cfg, app_signins=["safari", "chrome", "firefox"])
    g = gui.dialogs.Guide(frame, cfg, frame, "accounts")
    monkeypatch.setattr(g, "EndModal", lambda code: None)
    assert g.order[g.at] == "browser"
    text = g.texts["browser"].GetValue()
    if gui.dialogs.SignInChoices.__module__ and g.choices.here is not None:
        assert "Sign In Here in Wavelength" in text and "nothing to allow" in text
    assert g.choices.browsers() == ["safari", "chrome", "firefox"]  # Safari first, as listed
    g.go(+1)
    if sys.platform == "darwin":  # Safari's Full Disk Access and Chrome's keychain, both in one step
        assert g.order[g.at] == "permission"
        body = g.texts["permission"].GetValue()
        assert "For Safari:" in body and "For Google Chrome:" in body and "Firefox:" not in body
        g.go(+1)
    assert g.order[g.at] == "services"
    assert g.svc_browser.IsShown() and g.svc_browser.GetCount() == 3
    g.svc_browser.SetSelection(2)
    assert g._browser() == "firefox"
    g.Destroy()


def test_sign_in_choices_say_checked(frame, monkeypatch):
    said = []
    monkeypatch.setattr(gui.dialogs, "announce", lambda t, *a, **k: said.append(t), raising=False)
    import media_download.system as system
    monkeypatch.setattr(system, "announce", lambda t, *a, **k: said.append(t))
    monkeypatch.setattr(gui.accounts, "installed", lambda: [("safari", "Safari"), ("chrome", "Google Chrome")])
    cfg = dict(frame.cfg, app_signins=[])
    d = wx.Dialog(frame)
    s = wx.BoxSizer(wx.VERTICAL)
    c = gui.dialogs.SignInChoices(d, s, cfg)
    c.list.Check(1)
    ev = wx.CommandEvent(wx.wxEVT_CHECKLISTBOX, c.list.GetId())
    ev.SetInt(1)
    c._checked(ev)
    assert said[-1] == "Google Chrome checked." and cfg["app_signins"] == ["chrome"]
    assert not any("tick" in t.lower() for t in said)
    d.Destroy()


@pytest.mark.skipif(sys.platform != "darwin", reason="the Mac's WKWebView; Windows is covered on CI")
def test_sign_in_window_keeps_httponly_cookies(frame, monkeypatch):
    """The window's cookies come from WKHTTPCookieStore, so a sign-in's HttpOnly cookie is kept."""
    import http.server
    import threading
    import time
    import uuid
    from media_download import signin
    secret = uuid.uuid4().hex  # this run's own: the web view's store outlives a test run

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Set-Cookie", "session=%s; HttpOnly; Path=/; Max-Age=60" % secret)
            self.end_headers()
            self.wfile.write(b"<title>Test sign-in</title><p>signed in</p>")

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    gui.accounts.forget_own()
    kept = []
    w = signin.SignInWindow(frame, url="http://127.0.0.1:%d/" % srv.server_port, keep=kept.append)
    monkeypatch.setattr(w, "EndModal", lambda code: None)
    w.Show()

    def run_until(done, seconds):
        # WebKit loads only in a real event loop: a wx.Yield loop never fetches the page.
        loop = wx.GUIEventLoop()
        end = time.time() + seconds
        timer = wx.Timer()
        timer.Bind(wx.EVT_TIMER, lambda e: (done() or time.time() > end) and loop.Exit())
        timer.Start(50)
        loop.Run()
        timer.Stop()
    def has_secret():
        return any(c["value"] == secret for c in gui.accounts.read_netscape(gui.accounts.own_file()))
    run_until(lambda: has_secret() and "Test" in w.GetTitle(), 20)  # kept after each page
    title = w.GetTitle()
    w.finish()
    run_until(lambda: kept, 10)
    try:
        assert kept == [[]]  # no YouTube or SoundCloud here, but the cookie is kept all the same
        got = {c["name"]: c for c in gui.accounts.read_netscape(gui.accounts.own_file())}
        assert got["session"]["value"] == secret and got["session"]["domain"] == "127.0.0.1"
        assert gui.accounts.signin(frame.cfg).startswith("wavelength")
        assert title == "Sign In: Test sign-in"  # the window says which page it's on
    finally:
        if w:
            w.Destroy()
        srv.shutdown()
        gui.accounts.forget_own()
