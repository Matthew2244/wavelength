"""Wavelength: the window.

wxPython, so every control is the platform's own and VoiceOver, NVDA, JAWS
and Narrator read it natively. Tab order follows the work: the link, Download,
Search, what format, where it goes, then the downloads list and the details of
whichever row is selected, then the buttons that act on it.

Rows are status first ("Downloading, 45 percent, about 2 minutes left: Title")
because a long title is cut off at the end of a row, and the answer should
arrive before that. Finishes and failures are spoken; progress is spoken only
if asked for in Settings. Nothing ever moves focus on its own.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser

import wx
import wx.adv

from . import APP_NAME, __version__, accounts, describe, dialogs, engine, geometry, menus, sparkle, textsize, update, winsparkle, words
from . import system
from .system import sound_map, sound_volume
from .jobs import ACTIVE, Job
from .manager import Manager, run_task
from .system import (announce, dock_badge, keep_awake, mac_accessibility_label, open_path, play, pushover,
                     windows_name, reveal, taskbar_progress)

def M(label: str) -> str:
    """A label with its Alt-key letter on Windows. On the Mac a button's "&D" also answers
    Command-D, which stole the menu's Go to Downloads List (found with VoiceOver)."""
    return label.replace("&", "") if sys.platform == "darwin" else label


HELP_URL = "https://github.com/Matthew2244/wavelength#readme"
DAY = 24 * 3600
CMD = "Command" if sys.platform == "darwin" else "Control"
FOLDER_APP = "Finder" if sys.platform == "darwin" else "File Explorer"
ENTER = "Return" if sys.platform == "darwin" else "Enter"  # what the key is called on each system

MORE_TIP = ("Extras for the next download only: just part of it, chapters, subtitles, a browser's sign-in, "
            "an exact stream or a file name.")

MILESTONES = (100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000)

WELCOME = (
    "Welcome to Wavelength{name}.\n\n"
    "Paste a link into the Link field and press " + ENTER + ". It works with about 1,750 sites: "
    "YouTube, SoundCloud, Bandcamp, Vimeo, the BBC, archive.org and many more. "
    "Or type some words and press Search to find something without visiting the site.\n\n"
    "Downloads appear in the list below, newest at the bottom. Select one to read everything about it here. "
    "Several download at once.\n\n"
    "Everything is in the menus too, with its keyboard shortcut."
)


class Drop(wx.DropTarget):
    """Links or text dropped from a browser, or a text file of links from the desktop."""

    def __init__(self, frame):
        super().__init__()
        self.frame = frame
        self.data = wx.DataObjectComposite()
        self.text = wx.TextDataObject()
        self.files = wx.FileDataObject()
        self.url = wx.URLDataObject() if hasattr(wx, "URLDataObject") else None
        self.data.Add(self.text, True)
        self.data.Add(self.files)
        self.SetDataObject(self.data)

    def OnData(self, x, y, d):
        if not self.GetData():
            return wx.DragNone
        fmt = self.data.GetReceivedFormat()
        if fmt.GetType() in (wx.DF_FILENAME,):
            self.frame.add_from_files(self.files.GetFilenames())
        else:
            self.frame.add_from_text(self.text.GetText(), source="dropped")
        return d


class MainFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title=APP_NAME, size=(900, 680))
        self.cfg = engine.load_settings()
        # Window places and the text size. Kept under the old name on purpose: renaming the store
        # with the app would have quietly reset someone's Bigger Text after the update.
        self.ui = wx.Config("Media Download")
        self.next_opts: dict = {}
        self.rows: list[int] = []
        self.row_text: list[str] = []
        self.dirty = set()
        self.structure_changed = True
        self.finished_buffer: list[Job] = []
        self.last_spoken_progress = 0.0
        self.last_tally = 0.0
        self.next_sound_at = 0.0
        self.last_clip = ""
        self.seen_links = set()  # links already added or offered: the clipboard offer skips them
        self.offered = ""  # the link the offer put in the Link field, while it's still there untouched
        self.pending_playlists: list = []
        self.asking = False
        self.update_info = None
        self.player = None
        self.search_win = None
        self.mgr = Manager(self.cfg, self._from_manager)
        system.cue_handler = lambda kind: wx.CallAfter(self._sound, kind)  # for windows that aren't this one

        self.panel = wx.Panel(self)
        p = self.panel
        s = wx.BoxSizer(wx.VERTICAL)
        self._texts = []

        # link + actions
        row = wx.BoxSizer(wx.HORIZONTAL)
        lab = wx.StaticText(p, label=M("&Link or search words:"))
        self._texts.append(lab)
        self.link = wx.TextCtrl(p, style=wx.TE_PROCESS_ENTER)
        self.link.SetHint("Paste a link, type words to search, or drag links here")
        self.link.SetToolTip("Paste a link and press %s to download it. Paste several at once and each "
                             "gets its own row. Or type words and press %s to search." % (ENTER, ENTER))
        mac_accessibility_label(self.link, "Link or search words")
        self.download_btn = wx.Button(p, label=M("Dow&nload"))
        self.download_btn.SetToolTip("Download the link in the Link field. If it holds words instead, this searches "
                                     "for them. %s in the field does the same." % ENTER)
        self.play_link_btn = wx.Button(p, label=M("&Play Link"))  # made before Search: Tab follows the layout
        self.search_btn = wx.Button(p, label=M("Sear&ch..."))
        self.play_link_btn.SetToolTip("Play the link in the Link field without downloading it. Several links play "
                                      "one after another (%s-Shift-%s)." % (CMD, ENTER))
        self.search_btn.SetToolTip("Open Search to find things by words on YouTube, SoundCloud or YouTube Music, "
                                   "then download or play them (%s-F)." % CMD)
        row.Add(lab, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(self.link, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(self.download_btn, 0, wx.RIGHT, 6)
        row.Add(self.play_link_btn, 0, wx.RIGHT, 6)
        row.Add(self.search_btn, 0)
        s.Add(row, 0, wx.EXPAND | wx.ALL, 10)

        # format, quality, folder
        row = wx.BoxSizer(wx.HORIZONTAL)
        lab = wx.StaticText(p, label=M("Form&at:"))
        self._texts.append(lab)
        self.kind = wx.Choice(p, choices=[label for _, label in words.FORMAT_LABELS])
        keys = [k for k, _ in words.FORMAT_LABELS]
        self.kind.SetSelection(keys.index(self.cfg.get("format")) if self.cfg.get("format") in keys else 0)
        self.kind.SetToolTip("What every new download is saved as. \"Best audio\" keeps the sound exactly as "
                             "the site sends it, with no conversion. Remembered.")
        mac_accessibility_label(self.kind, "Format")
        self.height_lab = wx.StaticText(p, label=M("Video &quality:"))
        self._texts.append(self.height_lab)
        self.height = wx.Choice(p, choices=[label for _, label in words.HEIGHTS])
        hv = [h for h, _ in words.HEIGHTS]
        # Its own key: the ytdl command reads max_height and knows nothing of "any codec" (-1).
        h0 = self.cfg.get("app_max_height", self.cfg.get("max_height") or 0) or 0
        self.height.SetSelection(hv.index(h0) if h0 in hv else 0)
        self.height.SetToolTip("How sharp a video to download, like 1080 or 720; smaller numbers make smaller "
                               "files. \"Best that plays everywhere\" picks one most players can open. Only for "
                               "Video. Remembered.")
        mac_accessibility_label(self.height, "Video quality")
        row.Add(lab, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(self.kind, 0, wx.RIGHT, 16)
        row.Add(self.height_lab, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(self.height, 0)
        s.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.folder_text = wx.StaticText(p, label="")
        self._texts.append(self.folder_text)
        self.folder_btn = wx.Button(p, label=M("Chan&ge Folder..."))
        self.folder_btn.SetToolTip("Choose where downloads are saved. Remembered.")
        row.Add(self.folder_text, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(self.folder_btn, 0)
        s.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.opts_text = wx.StaticText(p, label=dialogs.options_summary({}))
        self._texts.append(self.opts_text)
        self.more_btn = wx.Button(p, label=M("&More Options..."))
        self.more_btn.SetToolTip(dialogs.options_summary({}) + " " + MORE_TIP)
        row.Add(self.opts_text, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(self.more_btn, 0)
        s.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # the list
        # Created filter first, then "Downloads:" straight before the list, though the label sits
        # left of the filter on screen. On Windows a label names, and its Alt key focuses, the next
        # control *created*: made in screen order, the list was nameless and Alt-W went to Filter.
        row = wx.BoxSizer(wx.HORIZONTAL)
        flab = wx.StaticText(p, label=M("F&ilter:"))
        self._texts.append(flab)
        self.filter = wx.SearchCtrl(p, size=(260, -1))
        self.filter.ShowCancelButton(True)
        self.filter.SetDescriptiveText("Type to show only some")
        self.filter.SetToolTip("Type part of a title, a site or a status, like Failed or Downloading, to show "
                               "only those rows. Escape or the clear button shows everything again.")
        mac_accessibility_label(self.filter, "Filter the downloads list")
        lab = wx.StaticText(p, label=M("Do&wnloads:"))
        self._texts.append(lab)
        row.Add(lab, 1, wx.ALIGN_CENTER_VERTICAL)
        row.Add(flab, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        row.Add(self.filter, 0, wx.ALIGN_CENTER_VERTICAL)
        s.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.list = wx.ListBox(p, style=wx.LB_SINGLE)
        mac_accessibility_label(self.list, "Downloads")
        windows_name(self.list, "Downloads")
        self.list.SetToolTip("Select a download to read about it below. " + ENTER + " opens the file; "
                             "Delete removes the row (never the file). %s-K lists everything you can do with it." % CMD)
        s.Add(self.list, 3, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        lab = wx.StaticText(p, label=M("Detail&s:"))
        self._texts.append(lab)
        s.Add(lab, 0, wx.LEFT | wx.RIGHT, 10)
        self.details = wx.TextCtrl(p, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self.details.SetToolTip("Everything known about the selected download: status, where it's saved, its "
                                "link, and the full error if it failed. Read only.")
        mac_accessibility_label(self.details, "Details")
        s.Add(self.details, 2, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.play_btn = wx.Button(p, label=M("Play Selected"))
        self.play_btn.SetToolTip("Play the selected download in the player, or stream it from its link if the file "
                                 "isn't here (%s-P)." % CMD)
        self.open_btn = wx.Button(p, label=M("&Open"))
        self.show_btn = wx.Button(p, label="Show in %s" % FOLDER_APP)
        self.stop_btn = wx.Button(p, label=M("S&top"))
        self.retry_btn = wx.Button(p, label=M("&Retry"))
        self.remove_btn = wx.Button(p, label=M("Remove from List"))
        self.open_btn.SetToolTip("Open the downloaded file in its usual app (%s-Down Arrow)." % CMD)
        self.show_btn.SetToolTip("Show the downloaded file in %s (%s-R)." % (FOLDER_APP, CMD))
        self.stop_btn.SetToolTip("Stop this download (%s-period). Retry carries on from where it stopped." % CMD)
        self.retry_btn.SetToolTip("Try a failed or stopped download again (%s-Shift-R)." % CMD)
        self.remove_btn.SetToolTip("Take the row off the list (%s-%s). Downloaded files stay where they are."
                                   % (CMD, "Delete" if sys.platform == "darwin" else "Backspace"))
        for b in (self.play_btn, self.open_btn, self.show_btn, self.stop_btn, self.retry_btn, self.remove_btn):
            row.Add(b, 0, wx.RIGHT, 6)
        s.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.gauge = wx.Gauge(p, range=1000)
        self.gauge.SetToolTip("Overall progress of everything downloading now.")
        mac_accessibility_label(self.gauge, "Overall progress")
        windows_name(self.gauge, "Overall progress")
        s.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        p.SetSizer(s)
        self.CreateStatusBar()
        self._menus()

        self._fit_choices()
        self.default_pt = self.list.GetFont().GetPointSize()
        self.text_pt = self.ui.ReadInt("text_size", self.default_pt)
        textsize.current, textsize.default = self.text_pt, self.default_pt
        if self.text_pt != self.default_pt:
            self._apply_text_size()

        self.Bind(wx.EVT_BUTTON, self.on_download, self.download_btn)
        self.Bind(wx.EVT_BUTTON, self.on_search, self.search_btn)
        self.Bind(wx.EVT_BUTTON, lambda e: self.on_play_link(), self.play_link_btn)
        self.play_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_play())
        self.link.Bind(wx.EVT_TEXT_ENTER, self.on_download)
        self.link.Bind(wx.EVT_TEXT_PASTE, self.on_paste_into_link)
        self.kind.Bind(wx.EVT_CHOICE, self.on_kind)
        self.height.Bind(wx.EVT_CHOICE, self.on_height)
        self.folder_btn.Bind(wx.EVT_BUTTON, self.on_folder)
        self.more_btn.Bind(wx.EVT_BUTTON, self.on_more)
        self.list.Bind(wx.EVT_LISTBOX, lambda e: self.show_details())
        self.filter.Bind(wx.EVT_TEXT, self.on_filter)
        self.filter.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, lambda e: self.filter.SetValue(""))
        self.filter.Bind(wx.EVT_CHAR_HOOK, self.on_filter_key)
        self.list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_open)
        self.list.Bind(wx.EVT_KEY_DOWN, self.on_list_key)
        menus.attach(self.list, self.list_menu)
        self.open_btn.Bind(wx.EVT_BUTTON, self.on_open)
        self.show_btn.Bind(wx.EVT_BUTTON, self.on_show)
        self.stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        self.retry_btn.Bind(wx.EVT_BUTTON, self.on_retry)
        self.remove_btn.Bind(wx.EVT_BUTTON, self.on_remove)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_ACTIVATE, self.on_activate)
        self.SetDropTarget(Drop(self))
        self.list.SetDropTarget(Drop(self))

        if not geometry.restore(self, self.ui, "window"):
            geometry.fit_on_screen(self)
            self.Centre()
        self.milestone = ""
        self._update_folder_text()
        self._update_height_enabled()
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_tick, self.timer)
        self.timer.Start(1000)

        unfinished = self.mgr.restore()
        self.structure_changed = True
        self.refresh()
        self.details.SetValue(self.welcome())
        self._update_buttons()
        self.link.SetFocus()
        if unfinished:
            self.tell("%s didn't finish last time. Choose Resume Unfinished in the Downloads menu to carry on."
                      % words.n(unfinished, "download"))
        engine.clean_temp()
        self.started = False
        wx.CallLater(800, self.startup_checks)

    # -------------------------------------------------------- menus

    def _menus(self):
        bar = wx.MenuBar()
        f = wx.Menu()
        self._m(f, "&Download Link\tCtrl+Return", self.on_download)
        self._m(f, "&Search...\tCtrl+F", self.on_search)
        self._m(f, "Download &Links from the Clipboard\tCtrl+Shift+V", self.on_paste_links)
        self._m(f, "Download Links from a &Text File...\tCtrl+O", self.on_open_list)
        self._m(f, "Your &Accounts...\tCtrl+U", self.on_accounts)
        self._m(f, "Set &Up Accounts...", lambda e: self.on_guide("accounts"))
        f.AppendSeparator()
        self._m(f, "&Change Download Folder...", self.on_folder)
        self._m(f, "Open Download &Folder\tCtrl+Shift+O", lambda e: self._open_folder())
        f.AppendSeparator()
        if sys.platform != "darwin":
            self._m(f, "&Settings...\tCtrl+,", self.on_settings)
        self._m(f, "Close &Window\tCtrl+W", self.on_close_window)
        self._m(f, "&Quit\tCtrl+Q", lambda e: self.Close(), wx.ID_EXIT)

        ed = wx.Menu()
        ed.Append(wx.ID_UNDO, "&Undo\tCtrl+Z")
        ed.AppendSeparator()
        ed.Append(wx.ID_CUT, "Cu&t\tCtrl+X")
        ed.Append(wx.ID_COPY, "&Copy\tCtrl+C")
        ed.Append(wx.ID_PASTE, "&Paste\tCtrl+V")
        ed.Append(wx.ID_SELECTALL, "Select &All\tCtrl+A")
        ed.AppendSeparator()
        self._m(ed, "Copy &Link of Selected Download\tCtrl+Shift+C", self.on_copy_link)
        if sys.platform == "darwin":
            self._m(ed, "Settings...\tCtrl+,", self.on_settings, wx.ID_PREFERENCES)

        d = wx.Menu()
        self._m(d, "&Play\tCtrl+P", lambda e: self.on_play())
        self._m(d, "Play &All Finished\tCtrl+Shift+P", lambda e: self.on_play_all())
        self._m(d, "Play the Link &Without Downloading\tCtrl+Shift+Return", lambda e: self.on_play_link())
        self._m(d, "Audio &Description...\tCtrl+Shift+A", lambda e: self.on_describe())
        d.AppendSeparator()
        self._m(d, "&Open File\tCtrl+Down", self.on_open)
        self._m(d, "Show in %s\tCtrl+R" % FOLDER_APP, self.on_show)
        self._m(d, "&Stop\tCtrl+.", self.on_stop)
        self._m(d, "Stop &All\tCtrl+Shift+.", self.on_stop_all)
        self._m(d, "&Retry\tCtrl+Shift+R", self.on_retry)
        self._m(d, "Retry Using a &Browser's Sign-in...", self.on_retry_signin)
        self._m(d, "Retry All &Failed", self.on_retry_failed)
        self._m(d, "Resume &Unfinished", self.on_resume)
        d.AppendSeparator()
        self._m(d, "Move &Up\tCtrl+Shift+Up", lambda e: self.on_move(-1))
        self._m(d, "Move Do&wn\tCtrl+Shift+Down", lambda e: self.on_move(+1))
        self._m(d, "Remo&ve from List\tCtrl+Back", self.on_remove)
        self._m(d, "&Clear Finished\tCtrl+Shift+K", self.on_clear)
        d.AppendSeparator()
        self._m(d, "Actions for the Selected Download...\tCtrl+K", lambda e: self.list._context_menu())

        v = wx.Menu()
        self._m(v, "Go to &Link Field\tCtrl+L", lambda e: self._focus(self.link))
        self._m(v, "Go to &Downloads List\tCtrl+D", lambda e: self._focus(self.list))
        self._m(v, "Go to D&etails\tCtrl+E", lambda e: self._focus(self.details))
        self._m(v, "&Filter the List\tCtrl+Shift+F", lambda e: self._focus(self.filter))
        self._m(v, "Go to the &Player\tCtrl+2", self.on_to_player)
        self._m(v, "&What's Happening?\tCtrl+J", self.on_whats_happening)
        v.AppendSeparator()
        self._m(v, "&Bigger Text\tCtrl+=", lambda e: self._text_size(+2))
        self._m(v, "&Smaller Text\tCtrl+-", lambda e: self._text_size(-2))
        self._m(v, "&Actual Size\tCtrl+0", lambda e: self._text_size(0))

        h = wx.Menu()
        self._m(h, "%s &Help" % APP_NAME, lambda e: self.show_help(), wx.ID_HELP)
        self._m(h, "Keyboard &Shortcuts", lambda e: self.show_shortcuts())
        self._m(h, "&Welcome Tour...", lambda e: self.on_guide("welcome"))
        h.AppendSeparator()
        self._m(h, "Get &Helper Tools...", lambda e: self.get_helpers(ask=False))
        self._m(h, "Update the Download &Engine", self.on_update_engine)
        self._m(h, "Check for App &Updates...", self.on_check_updates)
        self._m(h, "&About %s" % APP_NAME, self.on_about, wx.ID_ABOUT)

        bar.Append(f, "&File")
        bar.Append(ed, "&Edit")
        bar.Append(d, "&Downloads")
        bar.Append(v, "&View")
        bar.Append(menus.player_menu(self, self), "Pla&yer")
        bar.Append(h, "&Help")
        self.SetMenuBar(bar)

    def on_close_window(self, _=None):
        """Command-W closes the window in front. On the Mac a window with no menu bar of its own
        (Search) borrows this one, so this must not quit the app from there."""
        top = None
        focus = wx.Window.FindFocus()
        if focus:
            top = wx.GetTopLevelParent(focus)
        top = top or wx.GetActiveWindow()
        if top and top is not self and isinstance(top, wx.TopLevelWindow):
            top.Close()
        else:
            self.Close()

    def _m(self, menu, label, handler, wid=wx.ID_ANY):
        item = menu.Append(wid, label)
        self.Bind(wx.EVT_MENU, handler, item)
        return item

    def on_guide(self, start: str = "welcome"):
        """The welcome tour, or Set Up Accounts on its own; what it sets shows in the window after."""
        dlg = dialogs.Guide(self, self.cfg, self, start)
        dlg.ShowModal()
        dlg.Destroy()
        if start == "welcome" and not self.cfg.get("app_onboarded"):
            # Closed early is still seen: it's offered once, and Help, Welcome Tour has it after.
            self.cfg["app_onboarded"] = True
            engine.save_settings(self.cfg)
        keys = [k for k, _ in words.FORMAT_LABELS]
        if self.cfg.get("format") in keys:
            self.kind.SetSelection(keys.index(self.cfg["format"]))
            self._update_height_enabled()
        self._update_folder_text()
        self.link.SetFocus()

    def on_accounts(self, _=None):
        dlg = dialogs.AccountsDialog(self, self.cfg, self.check_signin)
        dlg.ShowModal()
        result = dlg.result
        dlg.Destroy()
        if not result:
            return
        how, url = result
        # After the window has gone: the player must never open over a modal window.
        if how == "play":
            wx.CallAfter(self.play_links, [{"url": url, "cookies": accounts.signin(self.cfg)}])
        elif how == "browse":
            wx.CallAfter(self.browse_collection, url)
        else:
            wx.CallAfter(self.add_links, [url])

    def browse_collection(self, url: str):
        """Your account's list, to pick what to play; downloading only if asked for."""
        self.tell("Getting the list. A long one takes a moment.")
        browser = accounts.signin(self.cfg)

        def work():
            got = {"log": []}

            def on(ev):
                if ev.get("ev") == "playlist":
                    got["list"] = ev
                elif ev.get("ev") == "log":
                    got["log"].append(ev.get("text", ""))
            run_task({"task": "probe", "spec": {"url": url, "dest": engine.TEMP, "kind": "best", "cookies": browser}},
                     on, timeout=900)
            wx.CallAfter(self._browse, url, browser, got)
        threading.Thread(target=work, daemon=True).start()

    def _browse(self, url, browser, got):
        lst = got.get("list")
        if not lst or not lst.get("entries"):
            log = "\n".join(got["log"])
            self.tell(accounts.explain_signin(log, browser, words.site_name(url)) or
                      (words.explain_failure(log, True, words.site_name(url)) if log else "That list is empty."))
            return
        entries = lst["entries"]
        dlg = dialogs.CheckList(self, lst.get("title") or "Your list",
                                "%s: %s. Check the ones to play with Space, then Play Checked; with nothing "
                                "checked it says Play All. Nothing is downloaded unless you choose Download "
                                "Checked Instead."
                                % (lst.get("title") or "Your list", words.n(len(entries), "item")),
                                entries, checked=False, mode="play")
        go = dlg.ShowModal() == wx.ID_OK
        chosen, how = (dlg.chosen(), dlg.choice) if go else ([], "")
        dlg.Destroy()
        if not chosen:
            return
        if how == "play":
            wx.CallAfter(self.play_links, [dict(e, cookies=browser) for e in chosen])
        elif self.folder_ready():
            fresh, already = self.add_entries(chosen)
            self._sound("added")
            self.tell("Added %s to download." % words.n(len(fresh), "item"))

    def signin_readable(self, browser: str) -> str | None:
        """None if the browser's sign-in can be read; else a sentence saying why not."""
        got = {}
        run_task({"task": "signin_check", "browser": browser}, lambda ev: got.update(ev) if ev.get("ev") == "signin"
                 else None, timeout=120)
        if got.get("ok") and not (got.get("failed") and got["failed"] * 2 >= max(1, got.get("count", 0))):
            return None
        if got.get("ok"):  # read, but most of it locked: Chrome, Edge and Brave on Windows do this now
            return accounts.explain_signin("could not be decrypted", browser)
        return (accounts.explain_signin(got.get("error", ""), browser)
                or "%s's sign-in couldn't be read: %s" % (accounts.spec_words(browser), got.get("error", "no answer")))

    def _signin_result(self, browser: str, said: str | None) -> None:
        """Right after a browser is chosen: a sign-in that can't be read is said once, here,
        instead of failing every download."""
        if not said:
            self._sound("signed_in")
            self.tell("Using %s's sign-in." % accounts.spec_words(browser))
            return
        mac_fda = "Full Disk Access" in said and sys.platform == "darwin"
        dlg = wx.MessageDialog(self, said + ("\n\nOpen that page of System Settings now?" if mac_fda else ""),
                               "Sign-in can't be read", (wx.OK | wx.CANCEL | wx.OK_DEFAULT) if mac_fda else wx.OK)
        if mac_fda:
            dlg.SetOKCancelLabels("&Open System Settings", "Cancel")
        go = dlg.ShowModal() == wx.ID_OK
        dlg.Destroy()
        if go and mac_fda:
            subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"])

    def check_signin(self, browser: str) -> str:
        """Ask YouTube for Liked videos with this browser's sign-in; a sentence for the answer."""
        found = {"log": []}

        def on(ev):
            if ev.get("ev") == "playlist":
                found["n"] = len(ev.get("entries") or [])
            elif ev.get("ev") == "log":
                found["log"].append(ev.get("text", ""))
        unreadable = self.signin_readable(browser)
        if unreadable:
            return unreadable
        run_task({"task": "probe", "spec": {"url": "https://www.youtube.com/playlist?list=LL", "dest": engine.TEMP,
                                            "kind": "best", "cookies": browser}}, on, timeout=300)
        if "n" in found:
            return "Signed in: YouTube answered with your Liked videos, %s." % words.n(found["n"], "video")
        log = "\n".join(found["log"])
        return (accounts.explain_signin(log, browser, "YouTube")
                or words.explain_failure(log, True, "YouTube"))

    def player_do(self, action: str):
        """The Player menu, from any window. Says so when nothing is playing, rather than nothing."""
        pl = self.player
        if pl is None or not pl.IsShown() or not (pl.item or pl.queue):  # closed is closed: nothing plays hidden
            self.tell("Nothing is in the player. Play something first: %s-P plays the selected download."
                      % ("Command" if sys.platform == "darwin" else "Control"))
            return
        step = pl.skip_len()
        do = {"toggle": pl.toggle, "prev": lambda: pl.go(-1), "next": lambda: pl.go(+1),
              "back": lambda: pl.skip(-step), "forward": lambda: pl.skip(step),
              "louder": lambda: pl.set_volume(min(1.0, pl.base_volume + 0.1)),
              "quieter": lambda: pl.set_volume(max(0.0, pl.base_volume - 0.1)),
              "mute": pl.toggle_mute, "faster": lambda: pl.step_speed(+1), "slower": lambda: pl.step_speed(-1),
              "normal": lambda: pl.set_speed(1.0), "time": pl.say_time, "levels": pl.say_levels}.get(action)
        if do:
            do()

    def on_to_main(self, _=None):
        self.Raise()
        self.list.SetFocus()

    def on_to_player(self, _=None):
        if self.player is None or not self.player.IsShown():
            self.tell("The player isn't open. Play something first: %s-P plays the selected download."
                      % ("Command" if sys.platform == "darwin" else "Control"))
            return
        self.player.Raise()
        self.player.play_btn.SetFocus()

    def _focus(self, ctrl):
        ctrl.SetFocus()

    # -------------------------------------------------------- talking

    def tell(self, text: str):
        """A short message: status bar for the eye, VoiceOver for the ear. Focus stays put."""
        self.SetStatusText(text)
        announce(text)

    # -------------------------------------------------------- adding

    def _job_from_ui(self, url: str) -> Job:
        o = self.next_opts
        kind = [k for k, _ in words.FORMAT_LABELS][self.kind.GetSelection()]
        return Job(url=url, dest=self.cfg["to"], kind=kind,
                   max_height=[h for h, _ in words.HEIGHTS][self.height.GetSelection()],
                   format_id=o.get("format_id", ""), format_audio_only=bool(o.get("format_audio_only")),
                   start=o.get("start", ""), end=o.get("end", ""), chapters=bool(o.get("chapters")),
                   subtitles=bool(o.get("subtitles")), transcript=bool(o.get("transcript")),
                   cookies=o.get("cookies", "") or accounts.signin(self.cfg), name=o.get("name", ""),
                   extra=o.get("extra", ""), cover_art=bool(self.cfg.get("app_cover_art", True)))

    def folder_ready(self) -> bool:
        """The download folder can be written. If not (a drive unplugged, a folder deleted or
        locked), say so and offer to choose another, rather than failing every download."""
        to = self.cfg["to"]
        try:
            os.makedirs(to, exist_ok=True)
            ok = os.access(to, os.W_OK)
        except OSError:
            ok = False
        if ok:
            return True
        dlg = wx.MessageDialog(self, "Wavelength can't save to %s. It may be on a drive that isn't connected, "
                               "or a folder that's been moved or locked.\n\nChoose another folder?"
                               % words.pretty_folder(to), "Download folder unavailable",
                               wx.OK | wx.CANCEL | wx.OK_DEFAULT | wx.ICON_WARNING)
        dlg.SetOKCancelLabels("&Choose Folder...", "Cancel")
        go = dlg.ShowModal() == wx.ID_OK
        dlg.Destroy()
        if go:
            self.on_folder(None)
            return self.cfg["to"] != to and os.access(self.cfg["to"], os.W_OK)
        self.tell("Nothing added: the download folder isn't available.")
        return False

    def add_links(self, urls: list[str], source: str = "") -> int:
        if not urls:
            return 0
        self.seen_links.update(urls)  # never offered back from the clipboard once it's been added
        if not self.folder_ready():
            return 0
        if self.next_opts.get("name") and len(urls) > 1:
            self.next_opts.pop("name")  # one name can't fit several files
        # The same link, same choices, already waiting or downloading: a second row would race
        # the first for one file. Point at the first instead.
        with self.mgr.lock:
            pending = {(j.url, j.spec().get("kind"), j.start, j.end, j.format_id): j
                       for j in self.mgr.jobs if j.state in ACTIVE or j.state in ("waiting", "waiting_choice")}
        added, dupes = [], []
        for u in urls:
            job = self._job_from_ui(u)
            key = (job.url, job.kind, job.start, job.end, job.format_id)
            if key in pending:
                dupes.append(pending[key])
                continue
            pending[key] = job
            added.append(u)
            self.mgr.add(job)
        if dupes and not added:
            first = dupes[0]
            self.structure_changed = True
            self.refresh()
            if first.id in self.rows:
                self.list.SetSelection(self.rows.index(first.id))
                self.show_details()
            self.tell("Already in the list: %s." % words.job_name(first) if len(dupes) == 1
                      else "All %d are already in the list." % len(dupes))
            return 0
        urls = added
        if self.next_opts:
            self.next_opts = {}
            self._show_opts()
        self.structure_changed = True
        self.refresh()
        if len(urls) == 1:
            text = "Added%s: %s. Looking it up." % (" from the " + source if source else "",
                                                    words.site_name(urls[0]) or words.short_link(urls[0]))
        else:
            text = "Added %s%s." % (words.n(len(urls), "link"), " from the " + source if source else "")
        if dupes:  # one sentence, not two in a row cutting each other off
            text += " %d %s already in the list." % (len(dupes), "was" if len(dupes) == 1 else "were")
        self.tell(text)
        self._sound("added")
        return len(urls)

    def add_from_text(self, text: str, source: str = ""):
        urls = words.links_in(text)
        if urls:
            self.add_links(urls, source)
        elif text.strip():
            self.on_search(None, query=text.strip())

    def add_from_files(self, paths):
        urls = []
        for p in paths:
            try:
                if p.lower().endswith(".webloc"):
                    import plistlib
                    with open(p, "rb") as fh:
                        urls.append(plistlib.load(fh).get("URL", ""))
                elif os.path.getsize(p) < 2_000_000:
                    with open(p, encoding="utf-8", errors="replace") as fh:
                        urls += words.links_in(fh.read())
            except (OSError, ValueError):
                pass
        urls = [u for u in urls if u]
        if urls:
            self.add_links(urls, "file")
        else:
            self.tell("No links found in that.")

    def on_download(self, _):
        text = self.link.GetValue().strip()
        if not text:
            self.tell("The Link field is empty. Paste a link first.")
            self.link.SetFocus()
            return
        urls = words.links_in(text)
        if not urls and words.looks_like_link(text):
            urls = ["https://" + text]
        if not urls:
            self.on_search(None, query=text)
            return
        self.link.SetValue("")
        self.add_links(urls)

    def on_paste_into_link(self, event):
        """Pasting several links into the field adds them all at once."""
        text = self._clipboard_text()
        urls = words.links_in(text)
        if len(urls) > 1 and not self.link.GetValue().strip():
            self.add_links(urls, "clipboard")
            return
        event.Skip()

    def on_paste_links(self, _):
        text = self._clipboard_text()
        urls = words.links_in(text)
        if not urls:
            self.tell("There's no link on the clipboard.")
            return
        self.add_links(urls, "clipboard")

    def on_open_list(self, _):
        with wx.FileDialog(self, "Choose a text file of links", wildcard="Text files|*.txt;*.webloc|All files|*.*",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.add_from_files(dlg.GetPaths())

    @staticmethod
    def _clipboard_text() -> str:
        text = ""
        if wx.TheClipboard.Open():
            try:
                obj = wx.TextDataObject()
                if wx.TheClipboard.GetData(obj):
                    text = obj.GetText()
            finally:
                wx.TheClipboard.Close()
        return text

    # -------------------------------------------------------- search

    def run_search(self, query, site, start=1, count=dialogs.SEARCH_PAGE):
        """One page of results, starting at result number `start`. There's no last page but the
        site's own: Search asks for the next one whenever the person wants more."""
        res = dialogs.SearchPage()
        log, ended = [], []
        cookies = accounts.signin(self.cfg)

        def on(ev):
            if ev.get("ev") == "results":
                res.extend(ev.get("results") or [])
            elif ev.get("ev") == "log":
                log.append(ev.get("text") or "")
            elif ev.get("ev") == "end":
                ended.append(bool(ev.get("ok")))
        run_task({"task": "search", "query": query, "site": site, "start": start, "count": count,
                  "cookies": cookies}, on, timeout=600)
        if not res and ended != [True]:
            # A failed search must never read as "Nothing found": a network blip, a refused
            # sign-in or a timeout each says what happened, and the next page stays on offer.
            res.error = words.explain_failure("\n".join(log) or "The search timed out.", bool(cookies),
                                              None, cookies)
        return res

    def on_search(self, _, query=None):
        """Open Search, or bring it forward if it's already open. It's an ordinary window, not a
        modal one: a modal Search held the keyboard for the whole app, so with the player raised
        over it (Play Selected) Quit, Close and every shortcut did nothing, and the Search window
        sat unseen behind the others."""
        q = query if query is not None else (self.link.GetValue().strip()
                                              if not words.links_in(self.link.GetValue()) else "")
        if self.search_win:
            self.search_win.show_again(q)
            return
        opened_with = self.link.GetValue()
        self.search_win = dialogs.Search(self, q, self.cfg.get("app_search_site", "youtube"), self.run_search,
                                         play=lambda entries: self.play_links(entries, focus=False),
                                         player=lambda: self.player,
                                         on_done=lambda dlg, chosen: self._search_done(dlg, chosen, opened_with))
        self.search_win.Show()
        self.search_win.Raise()

    def _search_done(self, dlg, chosen, opened_with):
        """Search closed: by Download Checked (chosen) or Close, Escape, Command-W (empty)."""
        self.search_win = None
        self.cfg["app_search_site"] = dlg.site_key()
        engine.save_settings(self.cfg)
        self.Raise()
        if chosen and self.folder_ready():  # the same checks as a pasted link gets
            # Clear the words that started the search, but never a link typed in since: the
            # main window stays usable while Search is open.
            if self.link.GetValue() == opened_with and not words.links_in(opened_with):
                self.link.SetValue("")
            fresh, already = self.add_entries(chosen)
            chosen = fresh
            self.list.SetFocus()
            if chosen:
                self._sound("added")
            # After VoiceOver has read the row the focus landed on, or one cuts the other off.
            wx.CallLater(600, self.tell, ("Added %s from the search." % words.n(len(chosen), "download") if chosen else
                       "Nothing new added from the search.") +
                      (" %d %s already in the list." % (already, "was" if already == 1 else "were")
                       if already else ""))
        else:
            self.link.SetFocus()

    def add_entries(self, entries):
        """Results or list items (dicts with url, title...) into the list, in the format chosen in
        the window, skipping any already waiting or downloading. Returns (added, how many skipped)."""
        with self.mgr.lock:
            pending = {(j.url, j.kind, j.start, j.end, j.format_id) for j in self.mgr.jobs
                       if j.state in ACTIVE or j.state in ("waiting", "waiting_choice")}
        fresh = []
        for e in entries:
            job = self._job_from_ui(e["url"])
            key = (job.url, job.kind, job.start, job.end, job.format_id)
            if key in pending:
                continue
            pending.add(key)
            self.seen_links.add(job.url)
            job.title = e.get("title") or ""
            job.length = e.get("duration") or 0
            job.uploader = e.get("uploader") or ""
            job.take_when(e)
            self.mgr.add(job)
            fresh.append(e)
        if fresh:
            self.next_opts = {}
            self._show_opts()
            self.structure_changed = True
            self.refresh()
        return fresh, len(entries) - len(fresh)

    def download_now(self, entry):
        """Right-click, Download This One Now, from Search or a list: added at once, the window stays."""
        if not self.folder_ready():
            return
        fresh, _ = self.add_entries([entry])
        if fresh:
            self._sound("added")
            announce("Added: %s." % (entry.get("title") or "it"))
        else:
            announce("That one's already in the list.")

    def look_up(self, url, done):
        """The full details of one result, off the main thread; done(info) back on it."""
        threading.Thread(target=lambda: wx.CallAfter(done, self.probe_now(url)), daemon=True).start()

    # -------------------------------------------------------- choices

    def on_kind(self, _):
        self.cfg["format"] = [k for k, _ in words.FORMAT_LABELS][self.kind.GetSelection()]
        engine.save_settings(self.cfg)
        self._update_height_enabled()

    def on_height(self, _):
        self.cfg["app_max_height"] = [h for h, _ in words.HEIGHTS][self.height.GetSelection()]
        engine.save_settings(self.cfg)

    def _update_height_enabled(self):
        video = [k for k, _ in words.FORMAT_LABELS][self.kind.GetSelection()] == "video"
        self.height.Enable(video)
        self.height_lab.Enable(video)

    def _fit_choices(self):
        """A popup menu sizes itself to its first label on the Mac and cuts the rest off."""
        for c in (self.kind, self.height):
            dc = wx.ClientDC(c)
            dc.SetFont(c.GetFont())
            w = max(dc.GetTextExtent(c.GetString(i))[0] for i in range(c.GetCount()))
            c.SetMinSize((w + 60, -1))
        self.panel.Layout()

    def _update_folder_text(self):
        to = self.cfg["to"]
        self.folder_text.SetLabel("Saving to: %s" % words.pretty_folder(to))
        # Tab skips plain text, so the button carries the answer too.
        self.folder_btn.SetToolTip("Saving to %s. Choose another folder. Remembered." % words.pretty_folder(to))
        self.folder_text.SetToolTip(to)
        self.panel.Layout()

    def on_folder(self, _, parent=None):
        # `parent`: the window asking (the welcome tour), so the question sits on top of it
        with wx.DirDialog(parent or self, "Choose where downloads are saved", self.cfg["to"]) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.cfg["to"] = dlg.GetPath()
                engine.save_settings(self.cfg)
                self._update_folder_text()
                self.tell("Downloads now go to %s." % os.path.basename(self.cfg["to"]))

    def _open_folder(self):
        os.makedirs(self.cfg["to"], exist_ok=True)
        open_path(self.cfg["to"])

    def on_more(self, _):
        link = (words.links_in(self.link.GetValue()) or [""])[0]
        dlg = dialogs.MoreOptions(self, self.next_opts, link, self.probe_now)
        if dlg.ShowModal() == wx.ID_OK:
            self.next_opts = {k: v for k, v in dlg.opts.items() if v}
            self._show_opts()
            self.tell(dialogs.options_summary(self.next_opts))
        dlg.Destroy()
        self.link.SetFocus()

    def _show_opts(self):
        text = dialogs.options_summary(self.next_opts)
        self.opts_text.SetLabel(text)
        self.more_btn.SetToolTip(text + " " + MORE_TIP)  # Tab skips plain text; the button says it
        self.panel.Layout()

    def probe_now(self, url):
        out = {}

        def on(ev):
            if ev.get("ev") == "info":
                out.update(ev)
            elif ev.get("ev") == "playlist":
                out["error"] = "That link is a playlist; choose an exact stream for one item at a time."
            elif ev.get("ev") == "log":
                out["log"] = out.get("log", "") + ev.get("text", "") + "\n"
        job = self._job_from_ui(url)
        run_task({"task": "probe", "spec": job.spec()}, on, timeout=180)
        if "log" in out and "formats" not in out:
            out["error"] = words.explain_failure(out["log"], False, words.site_name(url), accounts.signin(self.cfg))
        return out

    def on_settings(self, _):
        before = accounts.signin(self.cfg)
        dlg = dialogs.Settings(self, self.cfg)
        if dlg.ShowModal() == wx.ID_OK:
            engine.save_settings(self.cfg)
            now = accounts.signin(self.cfg)
            if now and now != before:  # test the new browser's sign-in once, off the main thread
                threading.Thread(target=lambda: wx.CallAfter(self._signin_result, now, self.signin_readable(now)),
                                 daemon=True).start()
            if self.player is not None:
                self.player.settings_changed()
            self.tell("Settings saved. Up to %d downloads at once." % self.mgr.parallel())
            self.mgr.pump()
        dlg.Destroy()

    # -------------------------------------------------------- manager events (any thread)

    def _from_manager(self, job, what, data=None):
        wx.CallAfter(self._on_manager, job, what, data)

    def _on_manager(self, job, what, data):
        if not self:
            return
        if what in ("added", "removed", "moved"):
            self.structure_changed = True
        elif job is not None:
            self.dirty.add(job.id)
        if what == "finished":
            self._count(job)
            self.finished_buffer.append(job)
            wx.CallLater(1500, self._speak_finished)
        elif what == "playlist":
            self.pending_playlists.append((job, data))
            self._ask_next_playlist()
        elif what == "all_done":
            self._all_done(data)
        elif what == "engine":
            self.SetStatusText(data.get("text", ""))
        elif what == "site_paused":
            self._sound("waiting")
            self.tell("%s asked for fewer downloads, so its downloads are paused until %s. They'll carry on "
                      "by themselves." % (data["site"] or "A site", words.clock_time(data["until"])))
        if what in ("added", "removed", "moved", "finished", "changed"):
            self.refresh()

    def welcome(self) -> str:
        name = words.first_name()
        return WELCOME.format(name=", " + name if name else "")

    def _count(self, job):
        """The running tally (Help, About), and a quiet word at milestones, folded into the
        sentence that was going to be said anyway, never a message of its own."""
        if job.state != "done" or job.task != "download":
            return
        st = dict(self.cfg.get("app_stats") or {})
        st.setdefault("since", time.strftime("%Y-%m-%d"))
        st["count"] = int(st.get("count", 0)) + 1
        st["bytes"] = int(st.get("bytes", 0)) + int(job.bytes_done or 0)
        st["seconds"] = float(st.get("seconds", 0)) + float(job.length or 0)
        self.cfg["app_stats"] = st
        engine.save_settings(self.cfg)
        if st["count"] in MILESTONES:
            self.milestone = "That's your %s download." % words.ordinal(st["count"])

    def _with_milestone(self, text: str) -> str:
        if self.milestone:
            text, self.milestone = text + " " + self.milestone, ""
            self._sound("milestone")  # after the finished sound, in the queue of long sounds
        return text

    def _speak_finished(self):
        """Say what finished, gathering a burst into one sentence instead of talking over itself.

        In a small batch each finish is named. In a big one (an album, a playlist) naming
        forty songs would talk over everything else, so it becomes a tally at most every
        20 seconds. Failures are always named: bad news shouldn't wait.
        """
        if not self.finished_buffer:
            return
        jobs, self.finished_buffer = self.finished_buffer, []
        done = [j for j in jobs if j.state in ("done", "skipped")]
        failed = [j for j in jobs if j.state == "failed"]
        big = self.mgr.batch_total > 3
        # When the whole batch is over, "All downloads finished" says it; don't say it twice.
        # Counted from what actually finished, not what was added: a stopped or removed download
        # leaves batch_total high, and the one that did finish must still be named.
        c = self.mgr.batch_counts
        summary_coming = not self.mgr.busy() and c["done"] + c["failed"] > 1
        bits = []
        if summary_coming:
            done = []
        if done and not big:
            if len(done) == 1:
                j = done[0]
                bits.append(("Already here: %s." if j.state == "skipped" else "Done: %s.") % words.job_name(j))
                if j.note:
                    bits.append(j.note)
            else:
                bits.append("%s finished." % words.n(len(done), "download"))
        elif done and self.mgr.busy() and time.time() - self.last_tally >= 20:
            self.last_tally = time.time()
            c = self.mgr.batch_counts
            bits.append("%d of %d done." % (c["done"], self.mgr.batch_total))
        if len(failed) == 1:
            bits.append("Failed: %s. %s" % (words.job_name(failed[0]), failed[0].reason))
        elif failed and not summary_coming:
            bits.append("%s failed." % words.n(len(failed), "download"))
        if bits:
            self.tell(self._with_milestone(" ".join(bits)))
        if failed and self.mgr.busy():
            self._sound("failed")
        elif done and self.mgr.busy():
            self._sound("item_done")
        if any(j.state in ("waiting", "looking") and j.wait_reason for j in jobs):
            self._sound("waiting")  # the row says why and when; the sound says it happened

    # The short ones play at once; the others queue so two are never heard on top of each other.
    SOUND_ROOM = {"opening": 1.8, "closing": 1.8, "tour_done": 2.2, "milestone": 1.7}
    SHORT_SOUNDS = ("added", "copied", "item_done", "results", "no_more", "waiting", "stopped")

    def _sound(self, kind: str) -> None:
        """Play one of the app's sounds, if sounds and this one are switched on. The long ones
        (finished, failed, update, end of the queue) never play on top of each other: a failure
        straight followed by the end of the batch was two sounds at once, neither clear."""
        if not self.cfg.get("app_sounds", True):
            return
        theme = self.cfg.get("app_sound_theme", "rhodes")
        vol = sound_volume(self.cfg)
        smap = sound_map(self.cfg)
        if smap.get(kind) == "none" or vol <= 0:
            return
        now = time.time()
        if kind in self.SHORT_SOUNDS:
            if kind == "item_done" and now - getattr(self, "last_item_sound", 0) < 2.0:
                return  # a big batch finishing fast: a sound every two seconds at most
            if kind == "item_done":
                self.last_item_sound = now
            if self.next_sound_at - now > 1.0:
                return  # a long sound is playing; a blip on top would only blur it
            play(kind, theme, vol, smap)
            return
        wait = self.next_sound_at - now
        # The opening and closing tunes and the ear candy run longer; the rest fit in 1.4 s.
        self.next_sound_at = max(now, self.next_sound_at) + self.SOUND_ROOM.get(kind, 1.4)
        if wait > 0:
            wx.CallLater(int(wait * 1000), play, kind, theme, vol, smap)
        else:
            play(kind, theme, vol, smap)

    def _closing_sound(self):
        """Played once the quit is certain (never before a Quit Anyway question), straight away:
        nothing is left to wait for, and the app is about to go."""
        if not self.cfg.get("app_sounds", True):
            return
        vol = sound_volume(self.cfg)
        if vol > 0:
            play("closing", self.cfg.get("app_sound_theme", "rhodes"), vol, sound_map(self.cfg), wait=True)

    def _all_done(self, data):
        done, failed, took = data.get("done", 0), data.get("failed", 0), data.get("took", 0)
        if done or failed:
            self._sound("failed" if failed and not done else "done")
        if took > 5:
            self.RequestUserAttention()
        if done + failed > 1:
            text = "All downloads finished: %d done%s." % (done, ", %d failed" % failed if failed else "")
            wx.CallLater(1800, lambda: self.tell(self._with_milestone(text)))
        self.last_tally = 0.0
        if self.cfg.get("notify") and (done or failed):
            if failed:
                pushover("Wavelength: %d done, %d failed." % (done, failed), failed=True)
            else:
                pushover("Wavelength: %s finished." % words.n(done, "download"))
        if not self.IsActive() and (done or failed):
            try:
                n = wx.adv.NotificationMessage(APP_NAME, "%d done%s." % (done, ", %d failed" % failed
                                                                          if failed else ""), self)
                n.Show()
            except Exception:  # noqa: BLE001
                pass

    # -------------------------------------------------------- playlists

    def _modal_open(self) -> bool:
        return any(isinstance(w, wx.Dialog) and w.IsModal() for w in wx.GetTopLevelWindows())

    def _ask_next_playlist(self):
        if self.asking or not self.pending_playlists:
            return
        if self._modal_open():
            # Never pop a question up over another window someone is in: wait until it closes.
            if not getattr(self, "said_waiting_question", False):
                self.said_waiting_question = True
                self.tell("A playlist needs your answer; it asks when this window closes.")
            wx.CallLater(800, self._ask_next_playlist)
            return
        self.said_waiting_question = False
        self.asking = True
        job, data = self.pending_playlists.pop(0)
        try:
            self._ask_playlist(job, data)
        finally:
            self.asking = False
            if self.pending_playlists:
                wx.CallAfter(self._ask_next_playlist)

    def _ask_playlist(self, job, data):
        entries = data.get("entries") or []
        title = data.get("title") or "This link"
        if not entries:
            job.state = "failed"
            job.reason = "That playlist is empty, or its items couldn't be listed."
            self.dirty.add(job.id)
            self.refresh()
            return
        url = job.url
        can_single = ("v=" in url and "list=" in url) or len(entries) == 1
        dlg = PQ = dialogs.PlaylistQuestion(self, title, len(entries), can_single, job.site or data.get("site"))
        ans = dlg.ShowModal()
        dlg.Destroy()
        if ans == PQ.ALL:
            self.mgr.expand(job, entries, title)
            self.tell("Added all %s from %s." % (words.n(len(entries), "item"), title))
        elif ans == PQ.CHOOSE:
            many = len(entries) > 50  # a podcast's 400 episodes: start empty, check the few you want
            tl = dialogs.CheckList(
                self, "Choose Items",
                ("%s: %s, newest usually first. Nothing is checked yet: check the ones you want with Space."
                 if many else "%s: %s. Everything starts checked; uncheck what you don't want, or Uncheck All "
                 "and check the few you do.") % (title, words.n(len(entries), "item")), entries, checked=not many)
            if tl.ShowModal() == wx.ID_OK and tl.chosen():
                picked = tl.chosen()
                self.mgr.expand(job, picked, title)
                self.tell("Added %s from %s." % (words.n(len(picked), "item"), title))
            else:
                self.mgr.remove(job)
                self.tell("Nothing added from %s." % title)
            tl.Destroy()
        elif ans == PQ.ONE:
            import urllib.parse as up
            q = up.parse_qs(up.urlparse(url).query)
            single = "https://www.youtube.com/watch?v=%s" % q["v"][0] if "v" in q else entries[0]["url"]
            # Not retry(): "looking" counts as active there, so it would return and leave the row
            # stuck on "Looking up". The job is already counted in this batch; just start the lookup.
            with self.mgr.lock:
                job.url = single
                job.site = words.site_name(single)
                job.state = "looking"
                job.probed = False
                self.mgr.dirty = True
            self.mgr.pump()
        else:
            self.mgr.remove(job)
            self.tell("Playlist not added.")
        self.structure_changed = True
        self.refresh()

    # -------------------------------------------------------- the list

    def selected(self) -> Job | None:
        i = self.list.GetSelection()
        if i == wx.NOT_FOUND or i >= len(self.rows):
            return None
        return self.mgr.find(self.rows[i])

    def refresh(self):
        """Redraw only what changed. Rewriting every row each second would make a
        screen reader re-read the list; changing one row's text does not."""
        with self.mgr.lock:
            jobs = [j for j in self.mgr.jobs if self._matches(j)]
        if [j.id for j in jobs] != self.rows:
            self.structure_changed = True  # a row came into or left the filter
        if self.structure_changed:
            self.structure_changed = False
            sel = self.selected()
            self.rows = [j.id for j in jobs]
            self.row_text = [words.row_text(j) for j in jobs]
            self.list.Set(self.row_text)
            if sel and sel.id in self.rows:
                self.list.SetSelection(self.rows.index(sel.id))
            self.dirty.clear()
            self.show_details()
        else:
            for jid in list(self.dirty):
                if jid in self.rows:
                    i = self.rows.index(jid)
                    job = self.mgr.find(jid)
                    if job:
                        t = words.row_text(job)
                        if t != self.row_text[i]:
                            self.row_text[i] = t
                            self.list.SetString(i, t)
            sel = self.selected()
            if sel and sel.id in self.dirty:
                self.show_details(progress_only=True)
            self.dirty.clear()
        self._update_buttons()
        self._update_title()

    def _matches(self, job) -> bool:
        text = self.filter.GetValue().strip().lower() if hasattr(self, "filter") else ""
        if not text:
            return True
        hay = " ".join((words.row_text(job), job.site, job.url, job.uploader)).lower()
        return all(w in hay for w in text.split())

    def on_filter(self, _):
        self.structure_changed = True
        self.refresh()
        if getattr(self, "_filter_call", None):
            self._filter_call.Stop()
        self._filter_call = wx.CallLater(600, self._say_filter)  # once typing pauses, not per letter

    def _say_filter(self):
        total = len(self.mgr.jobs)
        if not self.filter.GetValue().strip():
            self.tell("Showing all %s." % words.n(total, "download"))
        else:
            self.tell("Showing %d of %d." % (len(self.rows), total))

    def on_filter_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE and self.filter.GetValue():
            self.filter.SetValue("")
        else:
            event.Skip()

    def show_details(self, progress_only=False):
        job = self.selected()
        if not job:
            text = self.welcome() if not self.rows else (
                "Select a download in the list to read about it here. %s in the list."
                % words.n(len(self.rows), "download"))
            if self.details.GetValue() != text:
                self.details.SetValue(text)
            return
        text = words.details_text(job)
        # While someone is reading the details, only rewrite them when something real
        # changes (finished, failed), never for a percentage: it would cut the reading off.
        if progress_only and self.FindFocus() is self.details and job.state in ACTIVE:
            return
        if self.details.GetValue() != text:
            self.details.SetValue(text)
            self.details.SetInsertionPoint(0)

    def _update_buttons(self):
        job = self.selected()
        has_file = bool(job and job.files and any(os.path.exists(f) for f in job.files))
        self.open_btn.Enable(has_file)
        self.play_btn.Enable(bool(job))
        self.show_btn.Enable(has_file or bool(job and os.path.isdir(job.folder())))
        self.stop_btn.Enable(bool(job and (job.state in ACTIVE or job.state == "waiting")))
        self.retry_btn.Enable(bool(job and job.state in ("failed", "stopped")))
        self.remove_btn.Enable(bool(job))
        # Stop, Retry and Remove each dim themselves when pressed. Focus left on a dimmed button
        # goes nowhere, so hand it to the list, which then reads the row it landed on.
        f = wx.Window.FindFocus()
        if f in (self.play_btn, self.open_btn, self.show_btn, self.stop_btn, self.retry_btn,
                 self.remove_btn) and not f.IsEnabled():
            self.list.SetFocus()

    def _update_title(self):
        with self.mgr.lock:
            active = [j for j in self.mgr.jobs if j.state in ("downloading", "converting")]
            waiting = sum(1 for j in self.mgr.jobs if j.state in ("waiting", "looking"))
        badge = str(len(active) + waiting) if active or waiting else ""
        if badge != getattr(self, "_badge", None):
            self._badge = badge
            dock_badge(badge)
        if not active and not waiting:
            self.SetTitle(APP_NAME + (" (update available)" if self.update_info else ""))
            self.gauge.SetValue(0)
            taskbar_progress(self, None)
            return
        total = sum(j.bytes_total for j in active if j.bytes_total)
        done = sum(min(j.bytes_done, j.bytes_total) for j in active if j.bytes_total)
        frac = done / total if total else 0
        self.gauge.SetValue(int(frac * 1000))
        taskbar_progress(self, frac)
        bits = []
        if active:
            bits.append("%d downloading" % len(active))
        if waiting:
            bits.append("%d waiting" % waiting)
        if total:
            bits.append("%d percent" % int(frac * 100))
        self.SetTitle("%s: %s" % (APP_NAME, ", ".join(bits)))

    def on_tick(self, _):
        self.refresh()
        keep_awake(bool(self.cfg.get("app_keep_awake", True)) and self.mgr.busy())
        every = int(self.cfg.get("app_announce_progress") or 0)
        if every and time.time() - self.last_spoken_progress >= every:
            with self.mgr.lock:
                active = [j for j in self.mgr.jobs if j.state == "downloading"]
            if active:
                self.last_spoken_progress = time.time()
                if len(active) == 1:
                    j = active[0]
                    announce("%s percent: %s" % (int(j.percent or 0), j.title or j.site))
                else:
                    announce(self.GetTitle().split(": ", 1)[-1])
        if self.mgr.dirty:
            self.mgr.save()

    def on_list_key(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_open(None)
        elif key in (wx.WXK_DELETE, wx.WXK_BACK) and not event.HasModifiers():
            self.on_remove(None)
        else:
            event.Skip()

    # -------------------------------------------------------- acting on a row

    # -------------------------------------------------------- playing

    def open_player(self, items, start=0, focus=True):
        from .player import PlayerFrame
        if self.player is None:
            self.player = PlayerFrame(self)
            textsize.apply(self.player)
        came_from = wx.Window.FindFocus()
        if came_from and wx.GetTopLevelParent(came_from) is not self.player:
            self.player.came_from = came_from  # Escape goes back here, not to some other window
        self.player.set_queue(items, start)
        if focus:
            self.player.Show()
        elif not self.player.IsShown():
            self.player.ShowWithoutActivating()  # a preview from Search: the keyboard stays there
        if focus:
            self.player.Raise()
            self.player.play_btn.SetFocus()

    def _want(self) -> str:
        return "video" if [k for k, _ in words.FORMAT_LABELS][self.kind.GetSelection()] == "video" else "audio"

    def play_links(self, entries, focus=True):
        """Play links without downloading: [{"url", "title"?, ...}]."""
        items = [{"url": e["url"], "title": e.get("title") or "", "uploader": e.get("uploader") or "",
                  "want": self._want(), "cookies": e.get("cookies", ""), **{k: e[k] for k in ("uploaded", "uploaded_ts", "approx", "views") if e.get(k)}} for e in entries]
        if items:
            self.open_player(items, focus=focus)

    def on_play_link(self):
        text = self.link.GetValue().strip()
        urls = words.links_in(text)
        if not urls and text and not words.looks_like_link(text):
            self.on_search(None, query=text)
            return
        if not urls:
            self.tell("Put a link in the Link field to play it.")
            self.link.SetFocus()
            return
        self.play_links([{"url": u} for u in urls])

    def _file_item(self, job):
        from .player import playable_file
        path = playable_file(job.files)
        if not path:
            return None
        return {"path": path, "title": job.title or os.path.basename(path), "uploader": job.uploader,
                "url": job.url, "duration": job.length if not (job.start or job.end) else 0,
                "uploaded": job.upload_date, "uploaded_ts": job.upload_ts, "approx": job.upload_approx,
                "views": job.views}

    def on_play(self):
        job = self.selected()
        if not job:
            self.tell("Select a download first.")
            return
        item = self._file_item(job)
        if item:
            item.pop("url", None)
            self.open_player([item])
        else:
            self.play_links([{"url": job.url, "title": job.title, "uploader": job.uploader}])

    def on_play_all(self):
        with self.mgr.lock:
            jobs = [self.mgr.find(i) for i in self.rows]
        items = []
        for j in jobs:
            it = j and j.state in ("done", "skipped") and self._file_item(j)
            if it:
                it.pop("url", None)
                items.append(it)
        if not items:
            self.tell("Nothing finished to play yet.")
            return
        sel = self.selected()
        start = 0
        if sel:
            from .player import playable_file
            p = playable_file(sel.files) if sel.files else None
            start = next((i for i, it in enumerate(items) if it["path"] == p), 0)
        self.open_player(items, start)

    # -------------------------------------------------------- audio description

    def on_describe(self):
        job = self.selected()
        if job and job.task != "describe":
            from .player import playable_file
            path = playable_file(job.files) if job.files else None
            self.describe_dialog(job.url, job.title, path)
            return
        urls = words.links_in(self.link.GetValue())
        if urls:
            self.describe_dialog(urls[0], "", None)
        else:
            self.tell("Select a download, or put a link in the Link field, then choose Audio Description.")

    def describe_dialog(self, url, title, path):
        def run_find(u):
            res = {}

            def on(ev):
                if ev.get("ev") == "about":
                    res["about"] = ev
                elif ev.get("ev") == "candidates":
                    res["candidates"] = ev.get("items") or []
                    res["searched"] = ev.get("searched") or 0
            run_task({"task": "find_description", "url": u, "title": title, "cookies": accounts.signin(self.cfg)},
                     on, timeout=600)
            return res

        def run_more(t, start):
            res = {}

            def on(ev):
                if ev.get("ev") == "candidates":
                    res["candidates"] = ev.get("items") or []
                    res["searched"] = ev.get("searched") or 0
            run_task({"task": "find_versions", "title": t, "start": start, "count": describe.VERSIONS_PAGE},
                     on, timeout=600)
            return res

        def make():
            video = path if path and os.path.splitext(path)[1].lower() in (".mp4", ".m4v", ".mov", ".mkv", ".webm") \
                else ""
            job = Job(url=url, dest=os.path.dirname(video) if video else self.cfg["to"], task="describe",
                      source_path=video, cookies=accounts.signin(self.cfg))
            job.title = title
            job.probed = True
            self.mgr.add(job)
            self.structure_changed = True
            self.refresh()
            self.tell("Making audio description for %s. It's in the downloads list; when it's done, Play "
                      "reads it as the video plays." % (title or "it"))

        # Playing closes the Audio Description window first and opens the player after it has
        # gone (CallAfter): a player raised over a modal window gets no keys, and the modal
        # holds the whole app's keyboard, Quit included.
        def track_play(fmt):
            wx.CallAfter(self.open_player,
                         [{"url": url, "title": title + " (described)", "want": "audio", "format": fmt}])

        def track_download(fmt):
            job = self._job_from_ui(url)
            job.format_id, job.format_audio_only = fmt, True
            job.name = (title + " (audio described)") if title else ""
            self.mgr.add(job)
            self.tell("Downloading the described track.")

        actions = {"make": make, "track_play": track_play, "track_download": track_download,
                   "version_play": lambda e: wx.CallAfter(self.play_links, [e]),
                   "version_download": lambda e: self.add_links([e["url"]])}
        dlg = dialogs.DescribeDialog(self.player if self.player and self.player.IsActive() else self, url, title,
                                     run_find, actions, run_more=run_more)
        dlg.ShowModal()
        dlg.Destroy()

    def _typing(self):
        """The text field with focus, if any. Four list commands borrow keys that mean editing
        inside a field (Command-Delete, Command-Down, Command-Shift-Up/Down), and menu shortcuts
        are seen before the field gets them, on both systems. So each of those commands checks
        here first and does the editing instead: typing in the Link field must never remove a
        download."""
        w = wx.Window.FindFocus()
        return w if isinstance(w, (wx.TextCtrl, wx.SearchCtrl)) else None

    def on_open(self, _):
        t = self._typing()
        if t:
            t.SetInsertionPointEnd()
            return
        job = self.selected()
        files = [f for f in (job.files if job else []) if os.path.exists(f)]
        if not files:
            self.tell("Nothing to open yet." if job else "Select a download first.")
            return
        open_path(files[0])

    def on_show(self, _):
        job = self.selected()
        if not job:
            self.tell("Select a download first.")
            return
        files = [f for f in job.files if os.path.exists(f)]
        if files:
            reveal(files)
        elif os.path.isdir(job.folder()):
            open_path(job.folder())

    def on_stop(self, _):
        job = self.selected()
        if job and (job.state in ACTIVE or job.state == "waiting"):
            self.mgr.stop(job)
            self._sound("stopped")
            self.tell("Stopped: %s. Retry carries on from where it stopped." % words.job_name(job))

    def on_stop_all(self, _):
        k = self.mgr.stop_all()
        if k:
            self._sound("stopped")
        self.tell("Stopped %s." % words.n(k, "download") if k else "Nothing is downloading.")

    def on_retry(self, _):
        job = self.selected()
        if job and job.state in ("failed", "stopped"):
            self.mgr.retry(job)
            self.tell("Trying again: %s." % words.job_name(job))

    def on_retry_signin(self, _):
        """For members-only, age-checked or "not a bot" failures: borrow a browser's sign-in."""
        job = self.selected()
        if not job or job.state not in ("failed", "stopped"):
            self.tell("Select a failed download first.")
            return
        names = [b for b in dialogs.browser_choices(self.cfg.get("app_signin_browser") or "") if b[0]]
        keys = [b[0] for b in names]
        dlg = wx.SingleChoiceDialog(
            self, "Which browser are you signed in with? Wavelength borrows that sign-in for this "
            "download only. Nothing is sent anywhere else.", "Retry Using a Browser's Sign-in",
            [b[1] for b in names])
        last = self.cfg.get("app_signin_browser") or ""
        if last in keys:
            dlg.SetSelection(keys.index(last))
        go = dlg.ShowModal() == wx.ID_OK
        choice = keys[dlg.GetSelection()] if go else None
        dlg.Destroy()
        if not choice:
            return
        self.cfg["app_signin_browser"] = choice
        engine.save_settings(self.cfg)
        job.cookies = choice
        job.engine_retry = False
        self.mgr.retry(job)
        self.tell("Trying again with %s's sign-in: %s." % (accounts.spec_words(choice), words.job_name(job)))

    def on_retry_failed(self, _):
        with self.mgr.lock:
            failed = [j for j in self.mgr.jobs if j.state == "failed"]
        for j in failed:
            self.mgr.retry(j)
        self.tell("Trying %s again." % words.n(len(failed), "download") if failed else "Nothing has failed.")

    def on_resume(self, _):
        k = self.mgr.resume_unfinished()
        self.tell("Resuming %s." % words.n(k, "download") if k else "Nothing is waiting to be resumed.")

    def on_remove(self, _):
        t = self._typing()
        if t:
            if not t.IsEditable():
                return
            a, b = t.GetSelection()
            if a == b:
                text, pos = t.GetValue(), t.GetInsertionPoint()
                if sys.platform == "darwin":
                    a = text.rfind("\n", 0, pos) + 1        # Command-Delete: back to the line start
                else:
                    a = pos                                 # Ctrl-Backspace: back one word
                    while a > 0 and text[a - 1].isspace():
                        a -= 1
                    while a > 0 and not text[a - 1].isspace():
                        a -= 1
                b = pos
            if a != b:
                t.Remove(a, b)
            return
        job = self.selected()
        if not job:
            return
        if job.state in ACTIVE and not self._modal_open():
            # Removing a running download throws away what it has fetched so far, and a stray
            # Delete in the list is easy: ask first, only for these.
            name = words.job_name(job)
            dlg = wx.MessageDialog(self, "%s is still going. Remove it and throw away what's downloaded so far?"
                                   % (name[:1].upper() + name[1:]), "Remove a running download?",
                                   wx.OK | wx.CANCEL | wx.CANCEL_DEFAULT)
            dlg.SetOKCancelLabels("&Remove", "Cancel")
            go = dlg.ShowModal() == wx.ID_OK
            dlg.Destroy()
            if not go:
                return
        i = self.list.GetSelection()
        self.mgr.remove(job)
        self.structure_changed = True
        self.refresh()
        if self.rows:
            self.list.SetSelection(min(i, len(self.rows) - 1))
            self.show_details()
        self.tell("Removed from the list: %s." % words.job_name(job))

    def on_clear(self, _):
        k = self.mgr.clear_finished()
        self.structure_changed = True
        self.refresh()
        self.tell("Cleared %s." % words.n(k, "finished download") if k else "Nothing finished to clear.")

    def on_move(self, delta):
        t = self._typing()
        if t:
            # Shift-Command-Up/Down: select to the start or end of the text.
            pos = t.GetInsertionPoint()
            if delta < 0:
                t.SetSelection(0, pos)
            else:
                t.SetSelection(pos, t.GetLastPosition())
            return
        job = self.selected()
        if not job:
            return
        self.mgr.move(job, delta)
        self.structure_changed = True
        self.refresh()
        self.tell("Moved %s." % ("up" if delta < 0 else "down"))

    def list_menu(self):
        """The downloads list's right-click menu, for the selected row."""
        job = self.selected()
        if not job:
            return [menus.item("Download Links from the Clipboard", lambda: self.on_paste_links(None),
                               keys="Ctrl+Shift+V"),
                    menus.item("Search...", lambda: self.on_search(None), keys="Ctrl+F")]
        has_file = bool(job.files) and job.state in ("done", "skipped")
        active = job.state in ("downloading", "converting", "looking", "waiting")
        again = [menus.item(label, lambda k=k: self.download_again(job, k)) for k, label in words.FORMAT_LABELS]
        return [
            menus.item("Play", self.on_play, has_file, "Ctrl+P"),
            menus.item("Open File", lambda: self.on_open(None), has_file, "Ctrl+Down"),
            menus.item("Show in %s" % FOLDER_APP, lambda: self.on_show(None), has_file, "Ctrl+R"),
            menus.item("Play the Link Without Downloading", lambda: self.play_links([{
                "url": job.url, "title": job.title, "uploader": job.uploader, "uploaded": job.upload_date,
                "uploaded_ts": job.upload_ts, "approx": job.upload_approx}]), job.url.startswith("http")),
            menus.item("Audio Description...", self.on_describe, keys="Ctrl+Shift+A"),
            menus.SEP,
            menus.item("Stop", lambda: self.on_stop(None), active, "Ctrl+."),
            menus.item("Retry", lambda: self.on_retry(None), job.state in ("failed", "stopped"), "Ctrl+Shift+R"),
            menus.item("Retry Using a Browser's Sign-in...", lambda: self.on_retry_signin(None),
                       job.state in ("failed", "stopped")),
            menus.item("Download Again As", again, job.url.startswith("http")),
            menus.SEP,
            menus.item("Open the Web Page", lambda: self.open_page(job.url), job.url.startswith("http")),
            menus.item("Copy Link", lambda: self.on_copy_link(None), True, "Ctrl+Shift+C"),
            menus.item("Copy Title", lambda: self.copy(job.title or words.job_name(job), "Title copied.")),
            menus.item("Read the Details", lambda: self._focus(self.details), keys="Ctrl+E"),
            menus.SEP,
            menus.item("Move Up", lambda: self.on_move(-1), True, "Ctrl+Shift+Up"),
            menus.item("Move Down", lambda: self.on_move(+1), True, "Ctrl+Shift+Down"),
            menus.item("Remove from List", lambda: self.on_remove(None), True, "Ctrl+Back"),
        ]

    def download_again(self, job, kind: str):
        """The same link once more, in another format: a WAV of something saved as MP3, say."""
        if not self.folder_ready():
            return
        new = self._job_from_ui(job.url)
        new.kind = kind
        new.title, new.uploader, new.length = job.title, job.uploader, job.length
        new.upload_date, new.upload_ts, new.upload_approx, new.views = (job.upload_date, job.upload_ts,
                                                                      job.upload_approx, job.views)
        self.mgr.add(new)
        self.structure_changed = True
        self.refresh()
        self.tell("Added %s again, as %s." % (job.title or "it", words.FORMAT_SHORT.get(kind, kind)))
        self._sound("added")

    def open_page(self, url: str):
        if menus.open_web(url):
            self.tell("Opening the web page.")
        else:
            self.tell("That one has no web page.")

    def copy(self, text: str, said: str = "Copied."):
        if menus.copy_text(text):
            self.last_clip = text  # don't offer it straight back as a link to download
            self.tell(said)
            self._sound("copied")

    def on_copy_link(self, _):
        job = self.selected()
        if job:
            self.copy(job.url, "Link copied.")

    def on_whats_happening(self, _):
        c = self.mgr.counts()
        order = [("downloading", "downloading"), ("converting", "finishing"), ("looking", "being looked up"),
                 ("waiting", "waiting"), ("waiting_choice", "waiting for your choice"), ("done", "done"),
                 ("skipped", "already here"), ("failed", "failed"), ("stopped", "stopped")]
        with self.mgr.lock:
            active = [j for j in self.mgr.jobs if j.state in ("downloading", "converting")]
        named = []
        for j in active[:2]:
            how = ("%d percent" % int(j.percent)) if j.state == "downloading" and j.percent is not None \
                else (j.stage or "finishing").lower()
            named.append("%s, %s" % (j.title or j.site or "one", how))
        bits = []
        if named:
            bits.append("Downloading %s%s." % ("; ".join(named),
                                              "; and %d more" % (len(active) - 2) if len(active) > 2 else ""))
        rest = [(k, w) for k, w in order if k not in ("downloading", "converting")]
        tail = ["%d %s" % (c[k], w) for k, w in rest if c.get(k)]
        if tail:
            bits.append(", ".join(tail).capitalize() + ".")
        self.tell(" ".join(bits) if bits else "The list is empty.")

    # -------------------------------------------------------- clipboard offer

    def on_activate(self, event):
        event.Skip()
        if not event.GetActive() or not self.cfg.get("app_clipboard", True):
            return
        if not getattr(self, "started", False) or self._modal_open():
            return  # not over the welcome tour or the first questions
        wx.CallLater(800, self._check_clipboard)  # after VoiceOver has read the window coming forward

    def _check_clipboard(self):
        if not self or not self.IsActive() or self._modal_open():
            return
        if not self._link_free():
            return
        text = self._clipboard_text().strip()
        urls = words.links_in(text)
        if len(urls) != 1 or urls[0] == self.last_clip or text != urls[0] or urls[0] in self.seen_links:
            return
        url = urls[0]
        self.last_clip = url
        with self.mgr.lock:
            if any(j.url == url for j in self.mgr.jobs):
                return  # already in the list, finished or not

        def work():
            names = []
            run_task({"task": "recognise", "url": url},
                     lambda ev: names.append(ev.get("name")) if ev.get("ev") == "recognised" else None,
                     timeout=30)
            if names:
                wx.CallAfter(self._offer, url)
        threading.Thread(target=work, daemon=True).start()

    def _link_free(self) -> bool:
        """The Link field is empty, or still holds an earlier offer nobody touched."""
        v = self.link.GetValue().strip()
        return not v or v == self.offered

    def _offer(self, url):
        # The lookup can take a while: if the person has gone elsewhere since, say nothing.
        if not self or not self.IsActive() or self._modal_open() or not self._link_free():
            return
        self.link.SetValue(url)
        self.link.SelectAll()
        self.offered = url
        self.seen_links.add(url)
        in_field = wx.Window.FindFocus() is self.link
        how = ("Press %s to download it." % ENTER if in_field else
               "%s, then %s, to download it." % (key_words("Ctrl+L"), ENTER))
        self.tell("Link from the clipboard, %s, in the Link field. %s" % (words.site_name(url), how))

    # -------------------------------------------------------- text size (low vision)

    def _apply_text_size(self):
        # The popup menus and buttons keep the system size: a bigger font inside a fixed-height
        # Mac control is clipped, and a popup menu drew blank at 22 points.
        textsize.current = self.text_pt
        for w in (self.player, self.search_win):  # every other open window too, not only this one
            if w:
                textsize.apply(w)
        sb = self.GetStatusBar()
        if sb:  # the status bar is the only place tell() shows for the eye: big enough to read
            f = sb.GetFont()
            f.SetPointSize(self.text_pt)
            sb.SetFont(f)
            sb.SetMinHeight(int(sb.GetCharHeight() * 1.6))
            self.SendSizeEvent()
        for c in [self.list, self.details, self.link] + self._texts:
            f = c.GetFont()
            f.SetPointSize(self.text_pt)
            c.SetFont(f)
        for c in self._texts:
            c.InvalidateBestSize()
            if c in (getattr(self, "folder_text", None), getattr(self, "opts_text", None)):
                # These change with the folder and the options: pinned to today's width, a longer one
                # tomorrow was cut off and pushed the buttons beside them off the window.
                c.SetMinSize((60, c.GetBestSize().height))
            else:
                c.SetMinSize(c.GetBestSize())
        if sys.platform == "win32":
            # Windows draws its buttons, popups and checkboxes at any size, as every other window
            # here already grows them; only the Mac's fixed-height controls must keep the system size.
            for c in self.panel.GetChildren():
                if isinstance(c, (wx.Button, wx.CheckBox, wx.Choice, wx.SearchCtrl)):
                    f = c.GetFont()
                    f.SetPointSize(self.text_pt)
                    c.SetFont(f)
                    c.InvalidateBestSize()
        self._fit_choices()
        self.panel.Layout()
        # Grow the window, up to the screen, so long labels at big sizes don't push buttons off the
        # right edge; never shrink it (the player does the same).
        need = self.panel.GetBestSize()
        have = self.GetClientSize()
        idx = wx.Display.GetFromWindow(self)
        area = wx.Display(idx if idx != wx.NOT_FOUND else 0).GetClientArea()
        w = min(max(have.width, need.width), area.width - 20)
        h = min(max(have.height, need.height), area.height - 60)
        if (w, h) != (have.width, have.height):
            self.SetClientSize((w, h))

    def _text_size(self, step: int):
        self.text_pt = self.default_pt if step == 0 else max(10, min(48, self.text_pt + step))
        self.ui.WriteInt("text_size", self.text_pt)
        self.ui.Flush()
        self._apply_text_size()
        self.tell("Text size %d points." % self.text_pt)

    # -------------------------------------------------------- help, tools, updates

    def show_help(self):
        webbrowser.open(HELP_URL)

    def show_shortcuts(self):
        """Read from the menus themselves, so the list can't fall behind them (it had: Play,
        Remove, Close Window and a dozen more were missing)."""
        lines = ["%s in the Link field: download the link, or search if it's words." % ENTER,
                 "In the list: %s opens the file, Delete removes the row." % ENTER,
                 "On any list, its right-click menu: %s-K, or %s." % (
                     "Command" if sys.platform == "darwin" else "Control",
                     "VO-Shift-M with VoiceOver" if sys.platform == "darwin" else "Shift-F10 or the Menu key"), ""]
        bar = self.GetMenuBar()
        for i in range(bar.GetMenuCount()):
            found = []
            for item in bar.GetMenu(i).GetMenuItems():
                if item.GetId() in (wx.ID_UNDO, wx.ID_CUT, wx.ID_COPY, wx.ID_PASTE, wx.ID_SELECTALL):
                    continue  # the same in every app; not worth hearing
                acc = item.GetAccel()
                if acc and acc.IsOk():
                    name = item.GetItemLabelText().rstrip(".")
                    found.append("%s: %s%s" % (key_words(acc.ToString()), name, "" if name.endswith("?") else "."))
            if found:
                lines.append(bar.GetMenuLabelText(i) + " menu")
                lines.extend(found)
                lines.append("")
        lines.append("In the player: Space plays and pauses, Left and Right skip, Shift with them a minute, "
                     "T says the time, C captions, D audio description, [ and ] speed, Escape closes. "
                     "%s goes back to the downloads window, and %s from there to the player."
                     % (key_words("Ctrl+1"), key_words("Ctrl+2")))
        self.details.SetValue("Keyboard shortcuts\n\n" + "\n".join(lines).strip())
        self.details.SetFocus()
        self.details.SetInsertionPoint(0)

    def startup_checks(self):
        self._sound("opening")
        # Someone new gets the welcome tour once; anyone who has downloaded before never does.
        if not self.cfg.get("app_onboarded"):
            if (self.cfg.get("app_stats") or {}).get("count"):
                self.cfg["app_onboarded"] = True
                engine.save_settings(self.cfg)
            else:
                self.on_guide("welcome")
        missing = engine.missing_tools()
        if missing:
            self.get_helpers(ask=True, missing=missing)
        if self.cfg.get("auto_update", True) and engine.engine_check_due():
            def work():
                outcome, sentence = engine.update_engine()
                if outcome == "updated":
                    wx.CallAfter(self.SetStatusText, sentence)
            threading.Thread(target=work, daemon=True).start()
        self.quiet_update_check()
        self.started = True
        # A link copied before opening the app is offered too, the commonest way in.
        if self.cfg.get("app_clipboard", True) and self.IsActive() and not self._modal_open():
            wx.CallLater(800, self._check_clipboard)

    def get_helpers(self, ask=True, missing=None):
        missing = missing if missing is not None else engine.missing_tools()
        if not missing:
            r = engine.tool_report()
            self.details.SetValue("Helper tools: all present.\n\n" + "\n".join(
                "%s: %s" % (k, v) for k, v in r.items()) + "\n\nDownload engine (yt-dlp): %s"
                % engine.engine_version())
            self.tell("All the helper tools are here.")
            return
        names = [engine.TOOL_WORDS[m] for m in missing]
        if not engine.tool_sources():
            wx.MessageBox("Some helper tools are missing: %s. Install them with this system's package manager."
                          % "; ".join(names), "Helper tools", wx.OK | wx.ICON_INFORMATION, self)
            return
        msg = ("Wavelength needs %s:\n\n%s\n\nGet %s now? It's a one-time download of about %d MB, "
               "kept in the app's own folder." % ("a helper tool" if len(names) == 1 else "some helper tools",
                                                  "\n".join(names), "it" if len(names) == 1 else "them",
                                                  40 * len(names)))
        dlg = wx.MessageDialog(self, msg, "Helper tools", wx.OK | wx.CANCEL | wx.OK_DEFAULT | wx.ICON_INFORMATION)
        dlg.SetOKCancelLabels("&Get Them", "Cancel")
        go = dlg.ShowModal() == wx.ID_OK
        dlg.Destroy()
        if not go:
            self.tell("Not now. Help, Get Helper Tools, whenever you're ready.")
            return
        prog = wx.ProgressDialog("Getting helper tools", "Starting...", 100, self,
                                 wx.PD_APP_MODAL | wx.PD_AUTO_HIDE)
        state = {"text": "Starting...", "pct": 0, "done": False, "failed": []}

        def say(t):
            state["text"] = t
            announce(t)

        def progress(got, total):
            if total:
                state["pct"] = int(99 * got / total)

        def work():
            state["failed"] = engine.get_tools(missing, say, progress)
            state["done"] = True
        threading.Thread(target=work, daemon=True).start()
        while not state["done"]:
            prog.Update(min(99, state["pct"]), state["text"])
            wx.MilliSleep(200)
            wx.Yield()
        prog.Destroy()
        if state["failed"]:
            text = "Some helper tools didn't install:\n" + "\n".join(state["failed"])
        else:
            text = "Helper tools installed. Everything is ready."
        self.details.SetValue(text)
        self.tell(text.split("\n")[0])

    def on_update_engine(self, _):
        self.tell("Checking for a newer download engine. You have %s." % engine.engine_version())

        def work():
            outcome, sentence = engine.update_engine(lambda t: wx.CallAfter(self.tell, t))
            wx.CallAfter(self.tell, sentence)
        threading.Thread(target=work, daemon=True).start()

    def quiet_update_check(self):
        if sparkle.start():
            return  # Sparkle checks daily on its own and shows its own window
        if winsparkle.start(lambda: wx.CallAfter(self._quit_for_update)):
            return  # the same on Windows, for an installed copy
        if time.time() - self.ui.ReadFloat("last_update_check", 0) < DAY:
            return
        self.ui.WriteFloat("last_update_check", time.time())

        def work():
            info = update.latest()
            if update.newer(info):
                wx.CallAfter(self._announce_update, info)
        threading.Thread(target=work, daemon=True).start()

    def _announce_update(self, info):
        self.update_info = info
        self._update_title()
        self._sound("update")
        self.SetStatusText("Version %s is available. Help, Check for App Updates installs it." % info["version"])

    def on_check_updates(self, _):
        if sparkle.check() or winsparkle.check():
            return  # Sparkle's (or WinSparkle's) window says what it found
        self.tell("Checking for a newer version. You have %s." % update.current_version())
        wx.Yield()
        info = update.latest()
        if info is None:
            self.tell("Couldn't reach GitHub to check. Check the internet connection and try again.")
            return
        if not update.newer(info):
            self.tell("You have the latest version, %s." % update.current_version())
            return
        if not update.installed_app():
            self.tell("Version %s is available. This copy runs from Python: %s"
                      % (info["version"], update.how_to_update_source()))
            return
        busy = self.mgr.busy()
        dlg = wx.MessageDialog(
            self, "Version %s is available. You have %s.\n\nInstall it now? The app downloads it, checks it, "
            "then closes and opens the new version.%s" % (
                info["version"], update.current_version(),
                " Downloads in progress stop and can be resumed after." if busy else ""),
            "Update available", wx.OK | wx.CANCEL | wx.OK_DEFAULT | wx.ICON_INFORMATION)
        # Exactly "Cancel": macOS gives Escape only to a button with that title.
        dlg.SetOKCancelLabels("&Install", "Cancel")
        go = dlg.ShowModal() == wx.ID_OK
        dlg.Destroy()
        if not go:
            self.tell("Not installed. It stays available in Help, Check for App Updates.")
            return
        self.tell("Downloading version %s." % info["version"])
        wx.Yield()
        try:
            said = update.install(info)
        except update.UpdateError as e:
            self.tell("The update didn't install: %s." % e)
            return
        self.tell(said + " Closing now.")
        self.force_close = True
        wx.CallLater(1500, self.Close)

    def tally(self) -> str:
        st = self.cfg.get("app_stats") or {}
        if not st.get("count"):
            return "Nothing downloaded yet."
        since = st.get("since", "")
        try:
            since = time.strftime("%B %-d, %Y", time.strptime(since, "%Y-%m-%d")) if sys.platform != "win32" \
                else time.strftime("%B %d, %Y", time.strptime(since, "%Y-%m-%d"))
        except ValueError:
            pass
        hours = float(st.get("seconds", 0)) / 3600
        return "Since %s: %s, %s%s." % (
            since, words.n(int(st["count"]), "download"), words.size(st.get("bytes", 0)) or "0 bytes",
            ", about %s of listening and watching" % (words.n(round(hours), "hour") if hours >= 1
                                                      else words.duration(st.get("seconds", 0))) if st.get("seconds") else "")

    def on_about(self, _):
        wx.MessageBox(
            "%s %s\n\nSaves audio and video from about 1,750 sites, and says what it's doing.\n\n%s\n\n"
            "Download engine: yt-dlp %s.\nFree and open source, MIT license.\n\nBy Matthew Whitaker."
            % (APP_NAME, __version__, self.tally(), engine.engine_version()),
            "About %s" % APP_NAME, wx.OK | wx.ICON_INFORMATION, self)

    # -------------------------------------------------------- closing

    def on_close(self, event):
        playing = self.player is not None and self.player.loaded and self.player.playing()
        if playing and not self.mgr.busy() and event.CanVeto() and not getattr(self, "force_close", False):
            dlg = wx.MessageDialog(self, "Something is playing. Quit Wavelength anyway?", "Quit while playing?",
                                   wx.OK | wx.CANCEL | wx.CANCEL_DEFAULT)
            dlg.SetOKCancelLabels("&Quit", "Cancel")
            go = dlg.ShowModal() == wx.ID_OK
            dlg.Destroy()
            if not go:
                event.Veto()
                return
        if self.mgr.busy() and event.CanVeto() and not getattr(self, "force_close", False):
            c = self.mgr.counts()
            k = sum(c.get(s, 0) for s in ("downloading", "converting", "looking", "waiting"))
            dlg = wx.MessageDialog(self, "%s still going. Quit anyway? They come back next time, stopped, "
                                   "and Resume Unfinished carries on from where they were." % words.n(k, "download"),
                                   "Quit while downloading?", wx.OK | wx.CANCEL | wx.CANCEL_DEFAULT)
            dlg.SetOKCancelLabels("&Quit", "Cancel")
            go = dlg.ShowModal() == wx.ID_OK
            dlg.Destroy()
            if not go:
                event.Veto()
                return
        if self.search_win:
            self.search_win.on_done = None
            self.cfg["app_search_site"] = self.search_win.site_key()
            engine.save_settings(self.cfg)
            self.search_win.Destroy()
            self.search_win = None
        geometry.save(self, self.ui, "window")
        self._closing_sound()
        self.timer.Stop()
        keep_awake(False)
        self.mgr.shutdown()
        if self.player is not None:
            self.player.shutdown()
            self.player.Destroy()
            self.player = None
        winsparkle.cleanup()
        update.rename_old_bundle()
        event.Skip()

    def _quit_for_update(self):
        """WinSparkle has the new installer ready: close so it can run (unfinished downloads
        come back next time, stopped, like any quit)."""
        self.force_close = True
        self.Close()


def key_words(accel: str) -> str:
    """wx's "Ctrl+Shift+." as a person says it: "Command-Shift-Period" on the Mac."""
    names = {"CTRL": "Command" if sys.platform == "darwin" else "Control", "RAWCTRL": "Control",
             "SHIFT": "Shift", "ALT": "Option" if sys.platform == "darwin" else "Alt",
             "RETURN": "Return" if sys.platform == "darwin" else "Enter",
             "ENTER": "Return" if sys.platform == "darwin" else "Enter",
             "BACK": "Delete" if sys.platform == "darwin" else "Backspace",
             "BACKSPACE": "Delete" if sys.platform == "darwin" else "Backspace", "DELETE": "Forward Delete"
             if sys.platform == "darwin" else "Delete", "UP": "Up Arrow", "DOWN": "Down Arrow",
             "LEFT": "Left Arrow", "RIGHT": "Right Arrow", ".": "Period", ",": "Comma",
             "=": "Plus", "-": "Minus"}
    parts = accel.split("+")
    if accel.endswith("++"):
        parts = parts[:-2] + ["+"]
    return "-".join(names.get(p.upper(), p.upper() if len(p) == 1 else p) for p in parts if p)


class App(wx.App):
    def OnInit(self):
        self.SetAppName(APP_NAME)
        if sys.platform == "win32":  # follow Windows' dark mode, as the Mac already does by itself
            try:
                self.MSWEnableDarkMode()
            except Exception:  # noqa: BLE001 - older Windows: stay light
                pass
        self.frame = MainFrame()
        self.frame.Show()
        urls = [a for a in sys.argv[1:] if a.startswith("http")]
        if urls:
            self.frame.add_links(urls)
        return True

    def MacOpenURL(self, url):
        self.frame.add_links([url])

    def MacOpenFiles(self, filenames):
        self.frame.add_from_files(list(filenames))


def main(argv=None) -> int:
    App(False).MainLoop()
    return 0
