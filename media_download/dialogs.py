"""The app's dialogs. Each one states every current value in its controls,
names its buttons in plain words, and closes with Escape."""
from __future__ import annotations

import os
import sys
import threading

import wx

from . import engine, words
from .options import SEARCH_SITES
from .system import mac_accessibility_label

BROWSERS = [("", "Don't use a browser's sign-in"), ("chrome", "Chrome"), ("safari", "Safari"),
            ("firefox", "Firefox"), ("edge", "Edge"), ("brave", "Brave"), ("vivaldi", "Vivaldi"),
            ("opera", "Opera")]
if sys.platform == "win32":
    BROWSERS = [b for b in BROWSERS if b[0] != "safari"]

CMD = "Command" if sys.platform == "darwin" else "Control"


def labelled(parent, sizer, label, ctrl, tip=None, expand=True):
    """A label and its control on one row. The label is also the control's spoken name on the Mac."""
    row = wx.BoxSizer(wx.HORIZONTAL)
    text = wx.StaticText(parent, label=label)
    row.Add(text, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    row.Add(ctrl, 1 if expand else 0, wx.ALIGN_CENTER_VERTICAL)
    sizer.Add(row, 0, wx.EXPAND | wx.ALL, 6)
    mac_accessibility_label(ctrl, label.rstrip(":"))
    if tip:
        ctrl.SetToolTip(tip)
    return text


def buttons(dlg, ok_label, cancel_label="Cancel"):
    row = wx.BoxSizer(wx.HORIZONTAL)
    cancel = wx.Button(dlg, wx.ID_CANCEL, cancel_label)
    ok = wx.Button(dlg, wx.ID_OK, ok_label) if ok_label else None
    row.AddStretchSpacer()
    row.Add(cancel, 0, wx.ALL, 6)
    if ok:
        row.Add(ok, 0, wx.ALL, 6)
        ok.SetDefault()
    dlg.SetEscapeId(wx.ID_CANCEL)
    return row, ok, cancel


class MoreOptions(wx.Dialog):
    """Choices for the next download only. Everything here resets after it is added."""

    def __init__(self, parent, opts: dict, link: str, run_probe):
        super().__init__(parent, title="More Options for the Next Download",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.opts = dict(opts)
        self.link = link
        self.run_probe = run_probe
        s = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self, label="These apply to the next link you download, then reset. "
                                          "Leave anything blank to skip it.")
        s.Add(intro, 0, wx.ALL, 8)

        self.start = wx.TextCtrl(self, value=opts.get("start", ""))
        labelled(self, s, "Start at (for example 1:30):", self.start,
                 "Download only part of it. Minutes and seconds, like 1:30, or hours too, like 1:02:00.")
        self.end = wx.TextCtrl(self, value=opts.get("end", ""))
        labelled(self, s, "Stop at (for example 3:45):", self.end, "Where the part you want ends.")

        self.chapters = wx.CheckBox(self, label="Also save each chapter as its own file")
        self.chapters.SetValue(bool(opts.get("chapters")))
        s.Add(self.chapters, 0, wx.ALL, 6)
        self.subs = wx.CheckBox(self, label="Also save English subtitles (.srt)")
        self.subs.SetValue(bool(opts.get("subtitles")))
        s.Add(self.subs, 0, wx.ALL, 6)

        self.browser = wx.Choice(self, choices=[b[1] for b in BROWSERS])
        keys = [b[0] for b in BROWSERS]
        self.browser.SetSelection(keys.index(opts.get("cookies", "")) if opts.get("cookies", "") in keys else 0)
        labelled(self, s, "Sign in using:", self.browser,
                 "For members-only or age-checked videos, or when a site asks to confirm you're not a bot. "
                 "Uses the sign-in already in that browser. Nothing is sent anywhere else.")

        self.name = wx.TextCtrl(self, value=opts.get("name", ""))
        labelled(self, s, "File name (without extension):", self.name,
                 "Leave blank to name it after its title.")

        frow = wx.BoxSizer(wx.HORIZONTAL)
        self.stream_text = wx.StaticText(self, label=self._stream_words())
        frow.Add(self.stream_text, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.pick = wx.Button(self, label="Choose Exact Stream...")
        self.pick.SetToolTip("Look the link up and choose one exact audio or video stream from a list.")
        self.clear_pick = wx.Button(self, label="Use the Format Instead")
        frow.Add(self.pick, 0, wx.RIGHT, 6)
        frow.Add(self.clear_pick, 0)
        s.Add(frow, 0, wx.EXPAND | wx.ALL, 6)
        self.clear_pick.Enable(bool(self.opts.get("format_id")))

        self.extra = wx.TextCtrl(self, value=opts.get("extra", ""))
        labelled(self, s, "Extra yt-dlp options (advanced):", self.extra,
                 "Anything yt-dlp accepts on its command line, for example --limit-rate 2M.")

        row, ok, _ = buttons(self, "Keep These Options")
        s.Add(row, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizerAndFit(s)
        self.SetMinSize((560, -1))
        self.Fit()
        self.pick.Bind(wx.EVT_BUTTON, self.on_pick)
        self.clear_pick.Bind(wx.EVT_BUTTON, self.on_clear_pick)
        ok.Bind(wx.EVT_BUTTON, self.on_ok)
        self.start.SetFocus()

    def _stream_words(self):
        if self.opts.get("format_id"):
            return "Exact stream: %s." % (self.opts.get("format_words") or self.opts["format_id"])
        return "Exact stream: none chosen, so the Format menu decides."

    def on_pick(self, _):
        if not self.link or not words.looks_like_link(self.link):
            wx.MessageBox("Put a link in the Link field first, then choose Choose Exact Stream again.",
                          "No link yet", wx.OK | wx.ICON_INFORMATION, self)
            return
        self.stream_text.SetLabel("Looking up the link. This takes a few seconds.")
        self.pick.Disable()

        def work():
            res = self.run_probe(self.link)
            wx.CallAfter(self._picked, res)
        threading.Thread(target=work, daemon=True).start()

    def _picked(self, res):
        self.pick.Enable()
        if not res or not res.get("formats"):
            self.stream_text.SetLabel("Couldn't list the streams for that link. %s" % (res or {}).get("error", ""))
            return
        fmts = res["formats"]
        dlg = wx.SingleChoiceDialog(self, "Streams for: %s" % res.get("title", ""), "Choose Exact Stream",
                                    [f["words"] for f in fmts])
        if dlg.ShowModal() == wx.ID_OK:
            f = fmts[dlg.GetSelection()]
            self.opts["format_id"] = f["id"]
            self.opts["format_words"] = f["words"]
            self.opts["format_audio_only"] = f["audio_only"]
            if not f["audio_only"] and "+" not in f["id"]:
                # A video stream without sound gets the best sound added.
                self.opts["format_id"] = f["id"] + "+bestaudio/" + f["id"]
        dlg.Destroy()
        self.stream_text.SetLabel(self._stream_words())
        self.clear_pick.Enable(bool(self.opts.get("format_id")))
        self.Layout()

    def on_clear_pick(self, _):
        for k in ("format_id", "format_words", "format_audio_only"):
            self.opts.pop(k, None)
        self.stream_text.SetLabel(self._stream_words())
        self.clear_pick.Disable()
        self.pick.SetFocus()

    def on_ok(self, _):
        for label, field in (("Start at", self.start), ("Stop at", self.end)):
            v = field.GetValue().strip()
            if v and words.parse_time(v) is None:
                wx.MessageBox("%s should be a time like 1:30 or 1:02:00." % label, "Check the time",
                              wx.OK | wx.ICON_WARNING, self)
                field.SetFocus()
                return
        a, b = words.parse_time(self.start.GetValue()), words.parse_time(self.end.GetValue())
        if a is not None and b is not None and b <= a:
            wx.MessageBox("Stop at must come after Start at.", "Check the times", wx.OK | wx.ICON_WARNING, self)
            self.end.SetFocus()
            return
        self.opts.update({
            "start": self.start.GetValue().strip(), "end": self.end.GetValue().strip(),
            "chapters": self.chapters.GetValue(), "subtitles": self.subs.GetValue(),
            "cookies": BROWSERS[self.browser.GetSelection()][0], "name": self.name.GetValue().strip(),
            "extra": self.extra.GetValue().strip(),
        })
        self.EndModal(wx.ID_OK)


def options_summary(opts: dict) -> str:
    bits = []
    if opts.get("format_id"):
        bits.append("exact stream " + (opts.get("format_words") or opts["format_id"]))
    if opts.get("start") or opts.get("end"):
        bits.append("from %s to %s" % (opts.get("start") or "the start", opts.get("end") or "the end"))
    if opts.get("chapters"):
        bits.append("split by chapter")
    if opts.get("subtitles"):
        bits.append("subtitles")
    if opts.get("cookies"):
        bits.append("%s sign-in" % opts["cookies"].capitalize())
    if opts.get("name"):
        bits.append('named "%s"' % opts["name"])
    if opts.get("extra"):
        bits.append("extra options " + opts["extra"])
    return "Next download: " + (", ".join(bits) if bits else "no extra options") + "."


class Settings(wx.Dialog):
    def __init__(self, parent, cfg: dict):
        super().__init__(parent, title="Settings", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.cfg = cfg
        s = wx.BoxSizer(wx.VERTICAL)
        auto = engine.auto_parallel()
        self.parallel_vals = [0] + list(range(1, 13))
        self.parallel = wx.Choice(self, choices=["Automatic (%d on this computer)" % auto] +
                                  [str(i) for i in range(1, 13)])
        self.parallel.SetSelection(self.parallel_vals.index(int(cfg.get("app_parallel") or 0))
                                   if int(cfg.get("app_parallel") or 0) in self.parallel_vals else 0)
        labelled(self, s, "Downloads at once:", self.parallel,
                 "More at once uses more of the computer's cores for converting. Automatic is half the "
                 "cores, between two and eight.")
        self.site_vals = list(range(1, 7))
        self.per_site = wx.Choice(self, choices=[str(i) for i in self.site_vals])
        self.per_site.SetSelection(max(0, min(5, int(cfg.get("app_per_site") or 3) - 1)))
        labelled(self, s, "From the same site at once:", self.per_site,
                 "Sites that see too many downloads at once from one address start refusing. Three is safe.")
        self.frag_vals = [1, 2, 4, 8, 16]
        self.frags = wx.Choice(self, choices=["1", "2", "4", "8", "16"])
        f = int(cfg.get("app_fragments") or 4)
        self.frags.SetSelection(self.frag_vals.index(f) if f in self.frag_vals else 2)
        labelled(self, s, "Pieces fetched at once per download:", self.frags,
                 "Long videos arrive in pieces; fetching several at once is faster on a quick connection.")

        self.cover = wx.CheckBox(self, label="Add cover art to audio files")
        self.cover.SetValue(bool(cfg.get("app_cover_art", True)))
        s.Add(self.cover, 0, wx.ALL, 6)
        self.sounds = wx.CheckBox(self, label="Play a sound when downloads finish or fail")
        self.sounds.SetValue(bool(cfg.get("app_sounds", True)))
        s.Add(self.sounds, 0, wx.ALL, 6)
        self.say_vals = [0, 10, 30, 60]
        self.say = wx.Choice(self, choices=["Never", "Every 10 seconds", "Every 30 seconds", "Every minute"])
        v = int(cfg.get("app_announce_progress") or 0)
        self.say.SetSelection(self.say_vals.index(v) if v in self.say_vals else 0)
        labelled(self, s, "Speak progress while downloading:", self.say,
                 "For screen readers. Finishes and failures are always spoken.")
        self.clip = wx.CheckBox(self, label="Offer a link I've copied when I switch to the app")
        self.clip.SetValue(bool(cfg.get("app_clipboard", True)))
        s.Add(self.clip, 0, wx.ALL, 6)
        self.upd = wx.CheckBox(self, label="Keep the download engine up to date automatically")
        self.upd.SetValue(bool(cfg.get("auto_update", True)))
        self.upd.SetToolTip("Sites change often and the engine (yt-dlp) keeps up. Checks once a day, "
                            "and again when a download fails.")
        s.Add(self.upd, 0, wx.ALL, 6)
        self.push = None
        if os.path.exists(engine.PUSHOVER):
            self.push = wx.CheckBox(self, label="Send a Pushover notification when downloads finish")
            self.push.SetValue(bool(cfg.get("notify")))
            s.Add(self.push, 0, wx.ALL, 6)
        row, ok, _ = buttons(self, "Save Settings")
        s.Add(row, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizerAndFit(s)
        ok.Bind(wx.EVT_BUTTON, self.on_ok)
        self.parallel.SetFocus()

    def on_ok(self, _):
        self.cfg.update({
            "app_parallel": self.parallel_vals[self.parallel.GetSelection()],
            "app_per_site": self.site_vals[self.per_site.GetSelection()],
            "app_fragments": self.frag_vals[self.frags.GetSelection()],
            "app_cover_art": self.cover.GetValue(), "app_sounds": self.sounds.GetValue(),
            "app_announce_progress": self.say_vals[self.say.GetSelection()],
            "app_clipboard": self.clip.GetValue(), "auto_update": self.upd.GetValue(),
        })
        if self.push is not None:
            self.cfg["notify"] = self.push.GetValue()
        self.EndModal(wx.ID_OK)


def entry_words(i: int, e: dict) -> str:
    bits = ["%d. %s" % (i, e.get("title") or e.get("url"))]
    if e.get("duration"):
        bits.append(words.duration(e["duration"]))
    if e.get("uploader"):
        bits.append("by " + e["uploader"])
    return ", ".join(bits)


class TickList(wx.Dialog):
    """Tick the items you want. Reads item by item; Space ticks; the count is always stated."""

    def __init__(self, parent, title: str, intro: str, entries: list[dict], ok_label="Download Ticked",
                 ticked=True):
        super().__init__(parent, title=title, size=(720, 560), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.entries = entries
        self.ok_label = ok_label
        s = wx.BoxSizer(wx.VERTICAL)
        s.Add(wx.StaticText(self, label=intro), 0, wx.ALL, 8)
        self.list = wx.CheckListBox(self, choices=[entry_words(i + 1, e) for i, e in enumerate(entries)])
        mac_accessibility_label(self.list, "Items")
        if ticked:
            for i in range(len(entries)):
                self.list.Check(i)
        s.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
        self.count = wx.StaticText(self, label="")
        s.Add(self.count, 0, wx.ALL, 6)
        row = wx.BoxSizer(wx.HORIZONTAL)
        b_all = wx.Button(self, label="Tick All")
        b_none = wx.Button(self, label="Untick All")
        row.Add(b_all, 0, wx.RIGHT, 6)
        row.Add(b_none, 0)
        s.Add(row, 0, wx.ALL, 6)
        brow, self.ok, _ = buttons(self, ok_label)
        s.Add(brow, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(s)
        b_all.Bind(wx.EVT_BUTTON, lambda e: self._set_all(True))
        b_none.Bind(wx.EVT_BUTTON, lambda e: self._set_all(False))
        self.list.Bind(wx.EVT_CHECKLISTBOX, lambda e: self._count(speak=True))
        self._count()
        self.list.SetFocus()
        if entries:
            self.list.SetSelection(0)

    def _set_all(self, on):
        for i in range(self.list.GetCount()):
            self.list.Check(i, on)
        self._count()

    def _count(self, speak=False):
        k = len(self.list.GetCheckedItems())
        self.count.SetLabel("%d of %d ticked." % (k, self.list.GetCount()))
        if speak:  # VoiceOver re-reads the row before the tick lands, so say the result
            from .system import announce
            announce("%d ticked." % k)
        self.ok.SetLabel("%s (%d)" % (self.ok_label, k))
        self.ok.Enable(k > 0)
        self.Layout()

    def chosen(self) -> list[dict]:
        out = []
        for i in self.list.GetCheckedItems():
            e = dict(self.entries[i])
            e["number"] = i + 1
            out.append(e)
        return out


class PlaylistQuestion(wx.Dialog):
    """A link that turned out to be a set. Download all, choose, or just the one."""

    ALL, CHOOSE, ONE = 101, 102, 103

    def __init__(self, parent, title: str, count: int, can_single: bool, site: str):
        super().__init__(parent, title="A Playlist")
        s = wx.BoxSizer(wx.VERTICAL)
        what = "%s is a set of %s on %s." % (title, words.n(count, "item"), site or "the site")
        if can_single:
            what += " The link also points at one item in it."
        msg = wx.StaticText(self, label=what + " Each item gets its own row, saved into a folder named after the set.")
        msg.Wrap(520)
        s.Add(msg, 0, wx.ALL, 10)
        row = wx.BoxSizer(wx.HORIZONTAL)
        b_all = wx.Button(self, self.ALL, "Download All %d" % count)
        b_choose = wx.Button(self, self.CHOOSE, "Choose Items...")
        row.Add(b_all, 0, wx.ALL, 4)
        row.Add(b_choose, 0, wx.ALL, 4)
        if can_single:
            b_one = wx.Button(self, self.ONE, "Just That One")
            row.Add(b_one, 0, wx.ALL, 4)
            b_one.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(self.ONE))
        cancel = wx.Button(self, wx.ID_CANCEL, "Cancel")
        row.Add(cancel, 0, wx.ALL, 4)
        s.Add(row, 0, wx.ALL, 6)
        self.SetEscapeId(wx.ID_CANCEL)
        b_all.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(self.ALL))
        b_choose.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(self.CHOOSE))
        (b_one if can_single else b_choose).SetDefault()
        self.SetSizerAndFit(s)
        (b_one if can_single else b_choose).SetFocus()


class Search(wx.Dialog):
    """Search a site by words and tick what to download, without visiting the site."""

    def __init__(self, parent, query: str, site: str, run_search):
        super().__init__(parent, title="Search", size=(760, 600), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.run_search = run_search
        self.results = []
        s = wx.BoxSizer(wx.VERTICAL)
        top = wx.BoxSizer(wx.HORIZONTAL)
        lab = wx.StaticText(self, label="Search for:")
        self.query = wx.TextCtrl(self, value=query, style=wx.TE_PROCESS_ENTER)
        mac_accessibility_label(self.query, "Search for")
        top.Add(lab, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        top.Add(self.query, 1, wx.RIGHT, 6)
        self.site = wx.Choice(self, choices=[name for _, name, _ in SEARCH_SITES])
        keys = [k for k, _, _ in SEARCH_SITES]
        self.site.SetSelection(keys.index(site) if site in keys else 0)
        mac_accessibility_label(self.site, "Search on")
        top.Add(wx.StaticText(self, label="on"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        top.Add(self.site, 0, wx.RIGHT, 6)
        self.go = wx.Button(self, label="Search")
        top.Add(self.go, 0)
        s.Add(top, 0, wx.EXPAND | wx.ALL, 8)
        self.status = wx.StaticText(self, label="Type words and press Return.")
        s.Add(self.status, 0, wx.ALL, 6)
        self.list = wx.CheckListBox(self, choices=[])
        mac_accessibility_label(self.list, "Results")
        s.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
        brow, self.ok, _ = buttons(self, "Download Ticked", "Close")
        self.ok.Disable()
        s.Add(brow, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(s)
        self.go.Bind(wx.EVT_BUTTON, self.on_search)
        self.query.Bind(wx.EVT_TEXT_ENTER, self.on_search)
        self.list.Bind(wx.EVT_CHECKLISTBOX, lambda e: self._count(speak=True))
        self.list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_activate)
        self.query.SetFocus()
        if query.strip():
            wx.CallAfter(self.on_search, None)

    def site_key(self):
        return SEARCH_SITES[self.site.GetSelection()][0]

    def on_search(self, _):
        q = self.query.GetValue().strip()
        if not q:
            self.query.SetFocus()
            return
        self.go.Disable()
        site = SEARCH_SITES[self.site.GetSelection()][1]
        self.status.SetLabel("Searching %s for %s..." % (site, q))

        def work():
            res = self.run_search(q, self.site_key())
            wx.CallAfter(self._show, q, site, res)
        threading.Thread(target=work, daemon=True).start()

    def _show(self, q, site, res):
        if not self:
            return
        self.go.Enable()
        self.results = res or []
        self.list.Set([entry_words(i + 1, e) for i, e in enumerate(self.results)])
        if not self.results:
            self.status.SetLabel("Nothing found on %s for %s." % (site, q))
            self.query.SetFocus()
        else:
            self.status.SetLabel("%s on %s for %s. Tick with Space, then Download Ticked."
                                 % (words.n(len(self.results), "result"), site, q))
            self.list.SetFocus()
            self.list.SetSelection(0)
        from .system import announce
        announce(self.status.GetLabel())
        self._count()

    def _count(self, speak=False):
        k = len(self.list.GetCheckedItems())
        self.ok.SetLabel("Download Ticked (%d)" % k)
        if speak:
            from .system import announce
            announce("%d ticked." % k)
        self.ok.Enable(k > 0)
        self.Layout()

    def on_activate(self, _):
        i = self.list.GetSelection()
        if i != wx.NOT_FOUND:
            self.list.Check(i, not self.list.IsChecked(i))
            self._count()

    def chosen(self):
        return [self.results[i] for i in self.list.GetCheckedItems()]
