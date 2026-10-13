"""Media Download: the window.

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
import sys
import threading
import time
import webbrowser

import wx
import wx.adv

from . import APP_NAME, __version__, dialogs, engine, sparkle, update, winsparkle, words
from .jobs import ACTIVE, Job
from .manager import Manager, run_task
from .system import (announce, dock_badge, mac_accessibility_label, open_path, play, pushover, reveal,
                     taskbar_progress)

def M(label: str) -> str:
    """A label with its Alt-key letter on Windows. On the Mac a button's "&D" also answers
    Command-D, which stole the menu's Go to Downloads List (found with VoiceOver)."""
    return label.replace("&", "") if sys.platform == "darwin" else label


HELP_URL = "https://github.com/Matthew2244/ytdl-accessible#readme"
DAY = 24 * 3600
CMD = "Command" if sys.platform == "darwin" else "Control"
FOLDER_APP = "Finder" if sys.platform == "darwin" else "File Explorer"

MORE_TIP = ("Just part of it, chapters, subtitles, a browser's sign-in, an exact stream, a file name. "
            "For the next download only.")

WELCOME = (
    "Welcome to Media Download.\n\n"
    "Paste a link into the Link field and press Return. It works with about 1,750 sites: "
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
        super().__init__(None, title=APP_NAME, size=(900, 780))
        self.cfg = engine.load_settings()
        self.ui = wx.Config(APP_NAME)
        self.next_opts: dict = {}
        self.rows: list[int] = []
        self.row_text: list[str] = []
        self.dirty = set()
        self.structure_changed = True
        self.finished_buffer: list[Job] = []
        self.last_spoken_progress = 0.0
        self.last_tally = 0.0
        self.last_clip = ""
        self.pending_playlists: list = []
        self.asking = False
        self.update_info = None
        self.player = None
        self.mgr = Manager(self.cfg, self._from_manager)

        self.panel = wx.Panel(self)
        p = self.panel
        s = wx.BoxSizer(wx.VERTICAL)
        self._texts = []

        # link + actions
        row = wx.BoxSizer(wx.HORIZONTAL)
        lab = wx.StaticText(p, label=M("&Link or search words:"))
        self._texts.append(lab)
        self.link = wx.TextCtrl(p, style=wx.TE_PROCESS_ENTER)
        self.link.SetHint("Paste a link, or type words to search")
        self.link.SetToolTip("Paste a link and press Return to download it. Paste several at once and each "
                             "gets its own row. Or type words and press Return to search.")
        mac_accessibility_label(self.link, "Link or search words")
        self.download_btn = wx.Button(p, label=M("&Download"))
        self.download_btn.SetToolTip("Download the link in the Link field (Return).")
        self.search_btn = wx.Button(p, label=M("&Search..."))
        self.play_link_btn = wx.Button(p, label=M("&Play"))
        self.play_link_btn.SetToolTip("Play the link without downloading it. Paste several to play them in turn "
                                      "(%s-Shift-Return)." % CMD)
        self.search_btn.SetToolTip("Search YouTube, SoundCloud or YouTube Music by words (%s-F)." % CMD)
        row.Add(lab, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(self.link, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(self.download_btn, 0, wx.RIGHT, 6)
        row.Add(self.play_link_btn, 0, wx.RIGHT, 6)
        row.Add(self.search_btn, 0)
        s.Add(row, 0, wx.EXPAND | wx.ALL, 10)

        # format, quality, folder
        row = wx.BoxSizer(wx.HORIZONTAL)
        lab = wx.StaticText(p, label=M("&Format:"))
        self._texts.append(lab)
        self.kind = wx.Choice(p, choices=[label for _, label in words.FORMAT_LABELS])
        keys = [k for k, _ in words.FORMAT_LABELS]
        self.kind.SetSelection(keys.index(self.cfg.get("format")) if self.cfg.get("format") in keys else 0)
        self.kind.SetToolTip("What every new download is saved as. \"Best audio\" keeps the sound exactly as "
                             "the site sends it, with no conversion. Remembered.")
        mac_accessibility_label(self.kind, "Format")
        self.height_lab = wx.StaticText(p, label=M("&Video quality:"))
        self._texts.append(self.height_lab)
        self.height = wx.Choice(p, choices=[label for _, label in words.HEIGHTS])
        hv = [h for h, _ in words.HEIGHTS]
        # Its own key: the ytdl command reads max_height and knows nothing of "any codec" (-1).
        h0 = self.cfg.get("app_max_height", self.cfg.get("max_height") or 0) or 0
        self.height.SetSelection(hv.index(h0) if h0 in hv else 0)
        self.height.SetToolTip("The tallest video to download, in lines. Smaller files at lower numbers.")
        mac_accessibility_label(self.height, "Video quality")
        row.Add(lab, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(self.kind, 0, wx.RIGHT, 16)
        row.Add(self.height_lab, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(self.height, 0)
        s.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.folder_text = wx.StaticText(p, label="")
        self._texts.append(self.folder_text)
        self.folder_btn = wx.Button(p, label=M("C&hange Folder..."))
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
        row = wx.BoxSizer(wx.HORIZONTAL)
        lab = wx.StaticText(p, label=M("Do&wnloads:"))
        self._texts.append(lab)
        row.Add(lab, 1, wx.ALIGN_CENTER_VERTICAL)
        flab = wx.StaticText(p, label=M("Filte&r:"))
        self._texts.append(flab)
        self.filter = wx.SearchCtrl(p, size=(260, -1))
        self.filter.ShowCancelButton(True)
        self.filter.SetDescriptiveText("Type to show only some")
        self.filter.SetToolTip("Type part of a title, a site or a status, like Failed or Downloading, to show "
                               "only those rows. Escape or the clear button shows everything again.")
        mac_accessibility_label(self.filter, "Filter the downloads list")
        row.Add(flab, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        row.Add(self.filter, 0, wx.ALIGN_CENTER_VERTICAL)
        s.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.list = wx.ListBox(p, style=wx.LB_SINGLE)
        mac_accessibility_label(self.list, "Downloads")
        self.list.SetToolTip("Select a download to read about it below. Return opens the file; "
                             "Delete removes the row (never the file).")
        s.Add(self.list, 3, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        lab = wx.StaticText(p, label=M("D&etails:"))
        self._texts.append(lab)
        s.Add(lab, 0, wx.LEFT | wx.RIGHT, 10)
        self.details = wx.TextCtrl(p, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        mac_accessibility_label(self.details, "Details")
        s.Add(self.details, 2, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.play_btn = wx.Button(p, label=M("Pla&y"))
        self.play_btn.SetToolTip("Play the selected download here (%s-P)." % CMD)
        self.open_btn = wx.Button(p, label=M("&Open"))
        self.show_btn = wx.Button(p, label="Show in %s" % FOLDER_APP)
        self.stop_btn = wx.Button(p, label=M("S&top"))
        self.retry_btn = wx.Button(p, label=M("&Retry"))
        self.remove_btn = wx.Button(p, label=M("Remove from L&ist"))
        self.open_btn.SetToolTip("Open the downloaded file in its usual app.")
        self.show_btn.SetToolTip("Show the downloaded file in %s." % FOLDER_APP)
        self.stop_btn.SetToolTip("Stop this download. Retry carries on from where it stopped.")
        self.retry_btn.SetToolTip("Try a failed or stopped download again.")
        self.remove_btn.SetToolTip("Take the row off the list. Downloaded files stay where they are.")
        for b in (self.play_btn, self.open_btn, self.show_btn, self.stop_btn, self.retry_btn, self.remove_btn):
            row.Add(b, 0, wx.RIGHT, 6)
        s.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.gauge = wx.Gauge(p, range=1000)
        self.gauge.SetToolTip("Overall progress of everything downloading now.")
        mac_accessibility_label(self.gauge, "Overall progress")
        s.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        p.SetSizer(s)
        self.CreateStatusBar()
        self._menus()

        self._fit_choices()
        self.default_pt = self.list.GetFont().GetPointSize()
        self.text_pt = self.ui.ReadInt("text_size", self.default_pt)
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
        self.open_btn.Bind(wx.EVT_BUTTON, self.on_open)
        self.show_btn.Bind(wx.EVT_BUTTON, self.on_show)
        self.stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        self.retry_btn.Bind(wx.EVT_BUTTON, self.on_retry)
        self.remove_btn.Bind(wx.EVT_BUTTON, self.on_remove)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_ACTIVATE, self.on_activate)
        self.SetDropTarget(Drop(self))
        self.list.SetDropTarget(Drop(self))

        self._update_folder_text()
        self._update_height_enabled()
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_tick, self.timer)
        self.timer.Start(1000)

        unfinished = self.mgr.restore()
        self.structure_changed = True
        self.refresh()
        self.details.SetValue(WELCOME)
        self._update_buttons()
        self.link.SetFocus()
        if unfinished:
            self.tell("%s didn't finish last time. Choose Resume Unfinished in the Downloads menu to carry on."
                      % words.n(unfinished, "download"))
        engine.clean_temp()
        wx.CallLater(800, self.startup_checks)

    # -------------------------------------------------------- menus

    def _menus(self):
        bar = wx.MenuBar()
        f = wx.Menu()
        self._m(f, "&Download Link\tCtrl+Return", self.on_download)
        self._m(f, "&Search...\tCtrl+F", self.on_search)
        self._m(f, "Download &Links from the Clipboard\tCtrl+Shift+V", self.on_paste_links)
        self._m(f, "Download Links from a &Text File...\tCtrl+O", self.on_open_list)
        f.AppendSeparator()
        self._m(f, "&Change Download Folder...", self.on_folder)
        self._m(f, "Open Download &Folder\tCtrl+Shift+O", lambda e: self._open_folder())
        f.AppendSeparator()
        if sys.platform != "darwin":
            self._m(f, "&Settings...\tCtrl+,", self.on_settings)
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

        v = wx.Menu()
        self._m(v, "Go to &Link Field\tCtrl+L", lambda e: self._focus(self.link))
        self._m(v, "Go to &Downloads List\tCtrl+D", lambda e: self._focus(self.list))
        self._m(v, "Go to D&etails\tCtrl+E", lambda e: self._focus(self.details))
        self._m(v, "&Filter the List\tCtrl+Shift+F", lambda e: self._focus(self.filter))
        self._m(v, "&What's Happening?\tCtrl+J", self.on_whats_happening)
        v.AppendSeparator()
        self._m(v, "&Bigger Text\tCtrl+=", lambda e: self._text_size(+2))
        self._m(v, "&Smaller Text\tCtrl+-", lambda e: self._text_size(-2))
        self._m(v, "&Actual Size\tCtrl+0", lambda e: self._text_size(0))

        h = wx.Menu()
        self._m(h, "%s &Help" % APP_NAME, lambda e: self.show_help(), wx.ID_HELP)
        self._m(h, "Keyboard &Shortcuts", lambda e: self.show_shortcuts())
        h.AppendSeparator()
        self._m(h, "Get &Helper Tools...", lambda e: self.get_helpers(ask=False))
        self._m(h, "Update the Download &Engine", self.on_update_engine)
        self._m(h, "Check for App &Updates...", self.on_check_updates)
        self._m(h, "&About %s" % APP_NAME, self.on_about, wx.ID_ABOUT)

        bar.Append(f, "&File")
        bar.Append(ed, "&Edit")
        bar.Append(d, "&Downloads")
        bar.Append(v, "&View")
        bar.Append(h, "&Help")
        self.SetMenuBar(bar)

    def _m(self, menu, label, handler, wid=wx.ID_ANY):
        item = menu.Append(wid, label)
        self.Bind(wx.EVT_MENU, handler, item)
        return item

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
                   cookies=o.get("cookies", ""), name=o.get("name", ""),
                   extra=o.get("extra", ""), cover_art=bool(self.cfg.get("app_cover_art", True)))

    def add_links(self, urls: list[str], source: str = "") -> int:
        if not urls:
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
            self.tell("Already in the list: %s." % (first.title or first.url) if len(dupes) == 1
                      else "All %d are already in the list." % len(dupes))
            return 0
        urls = added
        if self.next_opts:
            self.next_opts = {}
            self._show_opts()
        self.structure_changed = True
        self.refresh()
        if len(urls) == 1:
            self.tell("Added%s: %s. Looking it up." % (" from the " + source if source else "",
                                                      words.site_name(urls[0]) or urls[0]))
        else:
            self.tell("Added %s%s." % (words.n(len(urls), "link"), " from the " + source if source else ""))
        if dupes:
            self.tell("Added %s. %d %s already in the list." % (words.n(len(urls), "link"), len(dupes),
                                                                "was" if len(dupes) == 1 else "were"))
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

    def run_search(self, query, site):
        res = []

        def on(ev):
            if ev.get("ev") == "results":
                res.extend(ev.get("results") or [])
        run_task({"task": "search", "query": query, "site": site, "count": 25}, on, timeout=120)
        return res

    def on_search(self, _, query=None):
        q = query if query is not None else (self.link.GetValue().strip()
                                              if not words.links_in(self.link.GetValue()) else "")
        dlg = dialogs.Search(self, q, self.cfg.get("app_search_site", "youtube"), self.run_search,
                             play=lambda entries: self.play_links(entries), player=lambda: self.player)
        go = dlg.ShowModal() == wx.ID_OK
        chosen = dlg.chosen() if go else []
        self.cfg["app_search_site"] = dlg.site_key()
        engine.save_settings(self.cfg)
        dlg.Destroy()
        if chosen:
            if query is not None or not words.links_in(self.link.GetValue()):
                self.link.SetValue("")
            for e in chosen:
                job = self._job_from_ui(e["url"])
                job.title = e.get("title") or ""
                job.length = e.get("duration") or 0
                job.uploader = e.get("uploader") or ""
                self.mgr.add(job)
            self.next_opts = {}
            self._show_opts()
            self.structure_changed = True
            self.refresh()
            self.tell("Added %s from the search." % words.n(len(chosen), "download"))

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

    def on_folder(self, _):
        with wx.DirDialog(self, "Choose where downloads are saved", self.cfg["to"]) as dlg:
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
            out["error"] = words.explain_failure(out["log"], False, words.site_name(url))
        return out

    def on_settings(self, _):
        dlg = dialogs.Settings(self, self.cfg)
        if dlg.ShowModal() == wx.ID_OK:
            engine.save_settings(self.cfg)
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
            self.tell("%s asked for fewer downloads, so its downloads are paused until %s. They'll carry on "
                      "by themselves." % (data["site"] or "A site", words.clock_time(data["until"])))
        if what in ("added", "removed", "moved", "finished", "changed"):
            self.refresh()

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
        summary_coming = not self.mgr.busy() and self.mgr.batch_total > 1
        bits = []
        if summary_coming:
            done = []
        if done and not big:
            if len(done) == 1:
                j = done[0]
                bits.append(("Already here: %s." if j.state == "skipped" else "Done: %s.") % (j.title or j.url))
                if j.note:
                    bits.append(j.note)
            else:
                bits.append("%s finished." % words.n(len(done), "download"))
        elif done and self.mgr.busy() and time.time() - self.last_tally >= 20:
            self.last_tally = time.time()
            c = self.mgr.batch_counts
            bits.append("%d of %d done." % (c["done"], self.mgr.batch_total))
        if len(failed) == 1:
            bits.append("Failed: %s. %s" % (failed[0].title or failed[0].url, failed[0].reason))
        elif failed and not summary_coming:
            bits.append("%s failed." % words.n(len(failed), "download"))
        if bits:
            self.tell(" ".join(bits))
        if failed and self.cfg.get("app_sounds", True) and self.mgr.busy():
            play("failed")

    def _all_done(self, data):
        done, failed, took = data.get("done", 0), data.get("failed", 0), data.get("took", 0)
        if self.cfg.get("app_sounds", True) and (done or failed):
            play("failed" if failed and not done else "done")
        if took > 5:
            self.RequestUserAttention()
        if done + failed > 1:
            text = "All downloads finished: %d done%s." % (done, ", %d failed" % failed if failed else "")
            wx.CallLater(1800, self.tell, text)
        self.last_tally = 0.0
        if self.cfg.get("notify") and (done or failed):
            if failed:
                pushover("Media Download: %d done, %d failed." % (done, failed), failed=True)
            else:
                pushover("Media Download: %s finished." % words.n(done, "download"))
        if not self.IsActive() and (done or failed):
            try:
                n = wx.adv.NotificationMessage(APP_NAME, "%d done%s." % (done, ", %d failed" % failed
                                                                          if failed else ""), self)
                n.Show()
            except Exception:  # noqa: BLE001
                pass

    # -------------------------------------------------------- playlists

    def _ask_next_playlist(self):
        if self.asking or not self.pending_playlists:
            return
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
            many = len(entries) > 50  # a podcast's 400 episodes: start empty, tick the few you want
            tl = dialogs.TickList(
                self, "Choose Items",
                ("%s: %s, newest usually first. Nothing is ticked yet: tick the ones you want with Space."
                 if many else "%s: %s. Everything starts ticked; untick what you don't want, or Untick All "
                 "and tick the few you do.") % (title, words.n(len(entries), "item")), entries, ticked=not many)
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
            job.url = single
            job.state = "looking"
            job.probed = False
            self.mgr.retry(job)
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
            text = WELCOME if not self.rows else (
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

    def open_player(self, items, start=0):
        from .player import PlayerFrame
        if self.player is None:
            self.player = PlayerFrame(self)
            if self.text_pt != self.default_pt:
                for c in (self.player.qlist, self.player.byline, self.player.pos_label):
                    f = c.GetFont()
                    f.SetPointSize(self.text_pt)
                    c.SetFont(f)
        self.player.set_queue(items, start)
        self.player.Show()
        self.player.Raise()
        self.player.play_btn.SetFocus()

    def _want(self) -> str:
        return "video" if [k for k, _ in words.FORMAT_LABELS][self.kind.GetSelection()] == "video" else "audio"

    def play_links(self, entries):
        """Play links without downloading: [{"url", "title"?, ...}]."""
        items = [{"url": e["url"], "title": e.get("title") or "", "uploader": e.get("uploader") or "",
                  "want": self._want()} for e in entries]
        if items:
            self.open_player(items)

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
                "url": job.url, "duration": job.length if not (job.start or job.end) else 0}

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

    def on_open(self, _):
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
            self.tell("Stopped: %s. Retry carries on from where it stopped." % (job.title or job.url))

    def on_stop_all(self, _):
        k = self.mgr.stop_all()
        self.tell("Stopped %s." % words.n(k, "download") if k else "Nothing is downloading.")

    def on_retry(self, _):
        job = self.selected()
        if job and job.state in ("failed", "stopped"):
            self.mgr.retry(job)
            self.tell("Trying again: %s." % (job.title or job.url))

    def on_retry_signin(self, _):
        """For members-only, age-checked or "not a bot" failures: borrow a browser's sign-in."""
        job = self.selected()
        if not job or job.state not in ("failed", "stopped"):
            self.tell("Select a failed download first.")
            return
        names = [b for b in dialogs.BROWSERS if b[0]]
        keys = [b[0] for b in names]
        dlg = wx.SingleChoiceDialog(
            self, "Which browser are you signed in with? Media Download borrows that sign-in for this "
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
        self.tell("Trying again with %s's sign-in: %s." % (choice.capitalize(), job.title or job.url))

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
        job = self.selected()
        if not job:
            return
        i = self.list.GetSelection()
        self.mgr.remove(job)
        self.structure_changed = True
        self.refresh()
        if self.rows:
            self.list.SetSelection(min(i, len(self.rows) - 1))
            self.show_details()
        self.tell("Removed from the list: %s." % (job.title or job.url))

    def on_clear(self, _):
        k = self.mgr.clear_finished()
        self.structure_changed = True
        self.refresh()
        self.tell("Cleared %s." % words.n(k, "finished download") if k else "Nothing finished to clear.")

    def on_move(self, delta):
        job = self.selected()
        if not job:
            return
        self.mgr.move(job, delta)
        self.structure_changed = True
        self.refresh()
        self.tell("Moved %s." % ("up" if delta < 0 else "down"))

    def on_copy_link(self, _):
        job = self.selected()
        if job and wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(job.url))
            wx.TheClipboard.Close()
            self.last_clip = job.url  # don't offer it straight back
            self.tell("Link copied.")

    def on_whats_happening(self, _):
        c = self.mgr.counts()
        order = [("downloading", "downloading"), ("converting", "finishing"), ("looking", "being looked up"),
                 ("waiting", "waiting"), ("waiting_choice", "waiting for your choice"), ("done", "done"),
                 ("skipped", "already here"), ("failed", "failed"), ("stopped", "stopped")]
        bits = ["%d %s" % (c[k], w) for k, w in order if c.get(k)]
        text = (", ".join(bits) + ".") if bits else "The list is empty."
        if c.get("downloading"):
            text += " " + self.GetTitle().split(": ", 1)[-1].split(", ")[-1] + " overall." \
                if "percent" in self.GetTitle() else ""
        self.tell(text)

    # -------------------------------------------------------- clipboard offer

    def on_activate(self, event):
        event.Skip()
        if not event.GetActive() or not self.cfg.get("app_clipboard", True):
            return
        if self.link.GetValue().strip():
            return
        text = self._clipboard_text().strip()
        urls = words.links_in(text)
        if len(urls) != 1 or urls[0] == self.last_clip or text != urls[0]:
            return
        url = urls[0]
        self.last_clip = url

        def work():
            names = []
            run_task({"task": "recognise", "url": url},
                     lambda ev: names.append(ev.get("name")) if ev.get("ev") == "recognised" else None,
                     timeout=30)
            if names:
                wx.CallAfter(self._offer, url)
        threading.Thread(target=work, daemon=True).start()

    def _offer(self, url):
        if self.link.GetValue().strip():
            return
        self.link.SetValue(url)
        self.link.SelectAll()
        self.tell("Link from the clipboard, %s. Press Return in the Link field to download it."
                  % words.site_name(url))

    # -------------------------------------------------------- text size (low vision)

    def _apply_text_size(self):
        # The popup menus and buttons keep the system size: a bigger font inside a fixed-height
        # Mac control is clipped, and a popup menu drew blank at 22 points.
        for c in [self.list, self.details, self.link] + self._texts:
            f = c.GetFont()
            f.SetPointSize(self.text_pt)
            c.SetFont(f)
        for c in self._texts:
            c.InvalidateBestSize()
            c.SetMinSize(c.GetBestSize())
        self._fit_choices()
        self.panel.Layout()

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
        c = "Command" if sys.platform == "darwin" else "Control"
        lines = [
            "Return in the Link field: download the link, or search if it's words.",
            "%s-F: search." % c,
            "%s-Shift-V: download every link on the clipboard." % c,
            "%s-O: download the links in a text file." % c,
            "%s-L: go to the Link field. %s-D: the Downloads list. %s-E: the details." % (c, c, c),
            "%s-J: what's happening, spoken." % c,
            "In the list: Return opens the file, Delete removes the row.",
            "%s-R: show the file in %s. %s-Period: stop. %s-Shift-R: retry." % (c, FOLDER_APP, c, c),
            "%s-Shift-Up and Down: move a download up or down the queue." % c,
            "%s-Shift-K: clear finished downloads from the list." % c,
            "%s-Plus and Minus: text size. %s-0: back to normal." % (c, c),
            "%s-Comma: Settings." % c,
        ]
        self.details.SetValue("Keyboard shortcuts\n\n" + "\n".join(lines))
        self.details.SetFocus()
        self.details.SetInsertionPoint(0)

    def startup_checks(self):
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
        msg = ("Media Download needs %s:\n\n%s\n\nGet %s now? It's a one-time download of about %d MB, "
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

    def on_about(self, _):
        wx.MessageBox(
            "%s %s\n\nSaves audio and video from about 1,750 sites, and says what it's doing.\n"
            "Download engine: yt-dlp %s.\nFree and open source, MIT license.\n\nBy Matthew Whitaker."
            % (APP_NAME, __version__, engine.engine_version()),
            "About %s" % APP_NAME, wx.OK | wx.ICON_INFORMATION, self)

    # -------------------------------------------------------- closing

    def on_close(self, event):
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
        self.timer.Stop()
        self.mgr.shutdown()
        winsparkle.cleanup()
        event.Skip()

    def _quit_for_update(self):
        """WinSparkle has the new installer ready: close so it can run (unfinished downloads
        come back next time, stopped, like any quit)."""
        self.force_close = True
        self.Close()


class App(wx.App):
    def OnInit(self):
        self.SetAppName(APP_NAME)
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
