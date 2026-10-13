"""The app's dialogs. Each one states every current value in its controls,
names its buttons in plain words, and closes with Escape."""
from __future__ import annotations

import os
import sys
import threading

import wx

from . import describe, engine, words
from .options import SEARCH_SITES
from . import menus
from .system import mac_accessibility_label

BROWSERS = [("", "Don't use a browser's sign-in"), ("chrome", "Chrome"), ("safari", "Safari"),
            ("firefox", "Firefox"), ("edge", "Edge"), ("brave", "Brave"), ("vivaldi", "Vivaldi"),
            ("opera", "Opera")]
if sys.platform == "win32":
    BROWSERS = [b for b in BROWSERS if b[0] != "safari"]

CMD = "Command" if sys.platform == "darwin" else "Control"


def labelled(parent, sizer, label, ctrl, text=None, tip=None, expand=True):
    """A label and its control on one row. The label is also the control's spoken name on the Mac.

    Make the label (`text`) before the control: the Mac reads a window in the order its
    controls were created, and a field heard before its own label reads backwards to anyone
    moving through with VoiceOver's arrow keys. Moving it in the tab order doesn't help.
    """
    row = wx.BoxSizer(wx.HORIZONTAL)
    if text is None:
        text = wx.StaticText(parent, label=label)
    row.Add(text, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    row.Add(ctrl, 1 if expand else 0, wx.ALIGN_CENTER_VERTICAL)
    sizer.Add(row, 0, wx.EXPAND | wx.ALL, 6)
    mac_accessibility_label(ctrl, label.rstrip(":"))
    if tip:
        ctrl.SetToolTip(tip)
    return text


def fit_choices(win):
    """Size every popup menu in a window to its longest choice: on the Mac a popup sizes itself
    to its first choice and cuts the rest off ("Pause the video to read...")."""
    for c in win.GetChildren():
        if isinstance(c, wx.Choice) and c.GetCount():
            dc = wx.ClientDC(c)
            dc.SetFont(c.GetFont())
            w = max(dc.GetTextExtent(c.GetString(i))[0] for i in range(c.GetCount()))
            c.SetMinSize((w + 60, -1))


def heading(dlg, sizer, text):
    h = wx.StaticText(dlg, label=text)
    h.SetFont(h.GetFont().Bold())
    sizer.Add(h, 0, wx.LEFT | wx.TOP, 8)
    return h


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

        _label = wx.StaticText(self, label="Start at (for example 1:30):")
        self.start = wx.TextCtrl(self, value=opts.get("start", ""))
        labelled(self, s, "Start at (for example 1:30):", self.start, _label,
                 "Download only part of it. Minutes and seconds, like 1:30, or hours too, like 1:02:00.")
        _label = wx.StaticText(self, label="Stop at (for example 3:45):")
        self.end = wx.TextCtrl(self, value=opts.get("end", ""))
        labelled(self, s, "Stop at (for example 3:45):", self.end, _label, "Where the part you want ends.")

        self.chapters = wx.CheckBox(self, label="Also save each chapter as its own file")
        self.chapters.SetValue(bool(opts.get("chapters")))
        s.Add(self.chapters, 0, wx.ALL, 6)
        self.subs = wx.CheckBox(self, label="Also save English subtitles (.srt)")
        self.subs.SetValue(bool(opts.get("subtitles")))
        s.Add(self.subs, 0, wx.ALL, 6)
        self.transcript = wx.CheckBox(self, label="Also save a text transcript to read (.txt)")
        self.transcript.SetValue(bool(opts.get("transcript")))
        self.transcript.SetToolTip("The captions as plain paragraphs, without timings or repeats. For reading "
                                   "a talk, lesson or podcast instead of listening, or with a braille display.")
        s.Add(self.transcript, 0, wx.ALL, 6)

        _label = wx.StaticText(self, label="Sign in using:")
        self.browser = wx.Choice(self, choices=[b[1] for b in BROWSERS])
        keys = [b[0] for b in BROWSERS]
        self.browser.SetSelection(keys.index(opts.get("cookies", "")) if opts.get("cookies", "") in keys else 0)
        labelled(self, s, "Sign in using:", self.browser, _label,
                 "For members-only or age-checked videos, or when a site asks to confirm you're not a bot. "
                 "Uses the sign-in already in that browser. Nothing is sent anywhere else.")

        _label = wx.StaticText(self, label="File name (without extension):")
        self.name = wx.TextCtrl(self, value=opts.get("name", ""))
        labelled(self, s, "File name (without extension):", self.name, _label,
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

        _label = wx.StaticText(self, label="Extra yt-dlp options (advanced):")
        self.extra = wx.TextCtrl(self, value=opts.get("extra", ""))
        labelled(self, s, "Extra yt-dlp options (advanced):", self.extra, _label,
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
        if not self:  # closed while the lookup was still going
            return
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
        try:
            from .options import split_extra
            split_extra(self.extra.GetValue())
        except ValueError:
            wx.MessageBox("The extra yt-dlp options have a quote mark that's never closed.",
                          "Check the extra options", wx.OK | wx.ICON_WARNING, self)
            self.extra.SetFocus()
            return
        self.opts.update({
            "start": self.start.GetValue().strip(), "end": self.end.GetValue().strip(),
            "chapters": self.chapters.GetValue(), "subtitles": self.subs.GetValue(),
            "transcript": self.transcript.GetValue(),
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
    if opts.get("transcript"):
        bits.append("a text transcript")
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
        heading(self, s, "Downloads")
        auto = engine.auto_parallel()
        self.parallel_vals = [0] + list(range(1, 13))
        _label = wx.StaticText(self, label="Downloads at once:")
        self.parallel = wx.Choice(self, choices=["Automatic (%d on this computer)" % auto] +
                                  [str(i) for i in range(1, 13)])
        self.parallel.SetSelection(self.parallel_vals.index(int(cfg.get("app_parallel") or 0))
                                   if int(cfg.get("app_parallel") or 0) in self.parallel_vals else 0)
        labelled(self, s, "Downloads at once:", self.parallel, _label,
                 "More at once uses more of the computer's cores for converting. Automatic is half the "
                 "cores, between two and eight.")
        self.site_vals = list(range(1, 7))
        _label = wx.StaticText(self, label="From the same site at once:")
        self.per_site = wx.Choice(self, choices=[str(i) for i in self.site_vals])
        self.per_site.SetSelection(max(0, min(5, int(cfg.get("app_per_site") or 3) - 1)))
        labelled(self, s, "From the same site at once:", self.per_site, _label,
                 "Sites that see too many downloads at once from one address start refusing. Three is safe.")
        self.frag_vals = [1, 2, 4, 8, 16]
        _label = wx.StaticText(self, label="Pieces fetched at once per download:")
        self.frags = wx.Choice(self, choices=["1", "2", "4", "8", "16"])
        f = int(cfg.get("app_fragments") or 4)
        self.frags.SetSelection(self.frag_vals.index(f) if f in self.frag_vals else 2)
        labelled(self, s, "Pieces fetched at once per download:", self.frags, _label,
                 "Long videos arrive in pieces; fetching several at once is faster on a quick connection.")

        self.rate_vals = ["", "500K", "1M", "2M", "5M", "10M"]
        _label = wx.StaticText(self, label="Limit download speed:")
        self.rate = wx.Choice(self, choices=["No limit", "500 KB a second", "1 MB a second", "2 MB a second",
                                             "5 MB a second", "10 MB a second"])
        r = cfg.get("app_rate_limit") or ""
        self.rate.SetSelection(self.rate_vals.index(r) if r in self.rate_vals else 0)
        labelled(self, s, "Limit download speed:", self.rate, _label,
                 "Per download. Leaves room for everyone else on a shared or slow connection.")
        self.cover = wx.CheckBox(self, label="Add cover art to audio files")
        self.cover.SetValue(bool(cfg.get("app_cover_art", True)))
        s.Add(self.cover, 0, wx.ALL, 6)
        self.say_vals = [0, 10, 30, 60]
        _label = wx.StaticText(self, label="Speak progress while downloading:")
        self.say = wx.Choice(self, choices=["Never", "Every 10 seconds", "Every 30 seconds", "Every minute"])
        v = int(cfg.get("app_announce_progress") or 0)
        self.say.SetSelection(self.say_vals.index(v) if v in self.say_vals else 0)
        labelled(self, s, "Speak progress while downloading:", self.say, _label,
                 "For screen readers. Finishes and failures are always spoken.")
        heading(self, s, "Sounds")
        from .system import SOUNDS, THEMES
        self.sounds = wx.CheckBox(self, label="Play sounds")
        self.sounds.SetValue(bool(cfg.get("app_sounds", True)))
        self.sounds.SetToolTip("A sound for each thing that happens: finished, failed, added, copied, search "
                               "results and more. Choose Sounds picks which.")
        s.Add(self.sounds, 0, wx.ALL, 6)
        self.theme_vals = [k for k, _ in THEMES]
        _label = wx.StaticText(self, label="Sound set:")
        self.theme = wx.Choice(self, choices=[w for _, w in THEMES])
        t = cfg.get("app_sound_theme", "rhodes")
        self.theme.SetSelection(self.theme_vals.index(t) if t in self.theme_vals else 0)
        labelled(self, s, "Sound set:", self.theme, _label,
                 "Each set has a sound for everything the app does. Changing it plays its Finished sound.")
        self.theme.Bind(wx.EVT_CHOICE, lambda e: self._preview("done"))
        self.vol_vals = [1.0, 0.75, 0.5, 0.25]
        self.volume = None
        if sys.platform == "darwin":  # Windows plays sounds at the system's own level
            _label = wx.StaticText(self, label="Sound volume:")
            self.volume = wx.Choice(self, choices=["Full", "Three quarters", "Half", "Quarter"])
            v = float(cfg.get("app_sound_volume", 1.0) or 1.0)
            self.volume.SetSelection(min(range(4), key=lambda k: abs(self.vol_vals[k] - v)))
            labelled(self, s, "Sound volume:", self.volume, _label, "How loud the app's sounds are, under the "
                     "system volume. Changing it plays a sound at the new level.")
            self.volume.Bind(wx.EVT_CHOICE, lambda e: self._preview("item_done"))
        self.sounds_off = list(cfg.get("app_sounds_off") or [])
        pick = wx.Button(self, label="Choose Sounds...")
        pick.SetToolTip("Lists every sound with a checkbox: checked plays, unchecked stays quiet. You can hear "
                        "each one there.")
        pick.Bind(wx.EVT_BUTTON, self.on_pick_sounds)
        s.Add(pick, 0, wx.ALL, 6)
        heading(self, s, "Player")
        self.skip_vals = [5, 10, 15, 30, 60]
        _label = wx.StaticText(self, label="Skip back and forward by:")
        self.skip = wx.Choice(self, choices=["5 seconds", "10 seconds", "15 seconds", "30 seconds", "1 minute"])
        sk = int(cfg.get("app_skip", 10) or 10)
        self.skip.SetSelection(self.skip_vals.index(sk) if sk in self.skip_vals else 1)
        labelled(self, s, "Skip back and forward by:", self.skip, _label, "What Left and Right arrows do in the player.")
        self.play_next = wx.CheckBox(self, label="Play the next item when one finishes")
        self.play_next.SetValue(bool(cfg.get("app_play_next", True)))
        s.Add(self.play_next, 0, wx.ALL, 6)
        self.resume = wx.CheckBox(self, label="Remember where I stopped in each item")
        self.resume.SetValue(bool(cfg.get("app_resume", True)))
        self.resume.SetToolTip("For podcasts, lectures and audiobooks. Not for the first or last 30 seconds.")
        s.Add(self.resume, 0, wx.ALL, 6)
        self.ad_vals = ["pause", "over", "off"]
        _label = wx.StaticText(self, label="Audio description, when there is some:")
        self.ad = wx.Choice(self, choices=["Pause the video to read it", "Read it over the video",
                                           "Don't read it"])
        m = cfg.get("app_ad_mode", "pause")
        self.ad.SetSelection(self.ad_vals.index(m) if m in self.ad_vals else 0)
        labelled(self, s, "Audio description, when there is some:", self.ad, _label,
                 "Pausing is extended description: nothing gets talked over. D in the player changes it.")
        self.adv_vals = ["system", "screen reader"]
        _label = wx.StaticText(self, label="Read description with:")
        self.adv = wx.Choice(self, choices=["The system voice", "My screen reader"])
        v = cfg.get("app_ad_voice", "system")
        self.adv.SetSelection(self.adv_vals.index(v) if v in self.adv_vals else 0)
        labelled(self, s, "Read description with:", self.adv, _label,
                 "The system voice lets the player resume exactly when it finishes. Your screen reader uses your "
                 "own voice and rate; the pause is then estimated.")
        self.captions = wx.CheckBox(self, label="Show captions under videos when there are some")
        self.captions.SetValue(bool(cfg.get("app_captions", True)))
        s.Add(self.captions, 0, wx.ALL, 6)
        heading(self, s, "Everything else")
        self.clip = wx.CheckBox(self, label="Offer a link I've copied when I switch to the app")
        self.clip.SetValue(bool(cfg.get("app_clipboard", True)))
        s.Add(self.clip, 0, wx.ALL, 6)
        self.awake = wx.CheckBox(self, label="Keep the computer awake while downloading")
        self.awake.SetValue(bool(cfg.get("app_keep_awake", True)))
        self.awake.SetToolTip("So a long playlist left overnight finishes. Only while something is "
                              "downloading; the screen can still turn off.")
        s.Add(self.awake, 0, wx.ALL, 6)
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
        fit_choices(self)
        self.SetSizerAndFit(s)
        ok.Bind(wx.EVT_BUTTON, self.on_ok)
        self.parallel.SetFocus()

    def _theme_now(self):
        return self.theme_vals[self.theme.GetSelection()]

    def _vol_now(self):
        return self.vol_vals[self.volume.GetSelection()] if self.volume else 1.0

    def _preview(self, kind):
        """Announce, then play: VoiceOver has just read the new choice; let it finish first."""
        from .system import play
        wx.CallLater(700, play, kind, self._theme_now(), self._vol_now())

    def on_pick_sounds(self, _):
        dlg = SoundPicker(self, self.sounds_off, self._theme_now, self._vol_now)
        if dlg.ShowModal() == wx.ID_OK:
            self.sounds_off = dlg.off()
        dlg.Destroy()

    def on_ok(self, _):
        self.cfg.update({
            "app_sound_theme": self._theme_now(), "app_sound_volume": self._vol_now(),
            "app_sounds_off": self.sounds_off,
            "app_parallel": self.parallel_vals[self.parallel.GetSelection()],
            "app_per_site": self.site_vals[self.per_site.GetSelection()],
            "app_fragments": self.frag_vals[self.frags.GetSelection()],
            "app_rate_limit": self.rate_vals[self.rate.GetSelection()],
            "app_cover_art": self.cover.GetValue(), "app_sounds": self.sounds.GetValue(),
            "app_announce_progress": self.say_vals[self.say.GetSelection()],
            "app_clipboard": self.clip.GetValue(), "auto_update": self.upd.GetValue(),
            "app_keep_awake": self.awake.GetValue(),
            "app_skip": self.skip_vals[self.skip.GetSelection()], "app_play_next": self.play_next.GetValue(),
            "app_resume": self.resume.GetValue(), "app_captions": self.captions.GetValue(),
            "app_ad_mode": self.ad_vals[self.ad.GetSelection()], "app_ad_voice": self.adv_vals[self.adv.GetSelection()],
        })
        if self.push is not None:
            self.cfg["notify"] = self.push.GetValue()
        self.EndModal(wx.ID_OK)


SEARCH_PAGE = 25  # results per page; pages keep coming until the site has no more

# How Search can order what it has loaded. YouTube's own "sort by upload date" no longer works
# (asked for, it answers in its usual order), so the app sorts the results it has.
ORDERS = [("site", "As the site ranks them"), ("newest", "Newest first"), ("oldest", "Oldest first"),
          ("views", "Most viewed first"), ("longest", "Longest first"), ("shortest", "Shortest first")]


def _when_key(e):
    """A sortable upload time; unknown is None."""
    import time as _t
    d = e.get("uploaded")
    if d and len(str(d)) == 8:
        try:
            return _t.mktime(_t.strptime(str(d), "%Y%m%d"))
        except ValueError:
            return None
    return float(e["uploaded_ts"]) if e.get("uploaded_ts") else None


def sort_value(e, how):
    """What `how` sorts on for one result; None when the site didn't say."""
    if how in ("newest", "oldest"):
        return _when_key(e)
    if how == "views":
        return e.get("views") or None
    if how in ("longest", "shortest"):
        return e.get("duration") or None
    return e.get("_rank", 0)


def order_results(results, how):
    """Sorted copy; anything the site didn't say (no date, no views) goes last, in site order."""
    rank = lambda e: e.get("_rank", 0)  # noqa: E731
    if how == "site":
        return sorted(results, key=rank)
    pick = lambda e: sort_value(e, how)  # noqa: E731
    known = [e for e in results if pick(e) is not None]
    unknown = sorted((e for e in results if pick(e) is None), key=rank)
    known.sort(key=lambda e: (pick(e), -rank(e)), reverse=how in ("newest", "views", "longest"))
    return known + unknown


def entry_words(i: int, e: dict) -> str:
    bits = ["%d. %s" % (i, e.get("title") or e.get("url"))]
    if e.get("duration"):
        bits.append(words.duration(e["duration"]))
    if e.get("uploader"):
        bits.append("by " + e["uploader"])
    for extra in (words.uploaded(e), words.views(e.get("views"))):
        if extra:
            bits.append(extra)
    return ", ".join(bits)


def entry_menu(win, lst, entries, main, play=None):
    """The right-click menu for a row of results or list items (Search, a playlist's items).
    `win` must have _count(); `main` is the main window, for adding, copying and looking up."""
    i = lst.GetSelection()
    if i == wx.NOT_FOUND or i >= len(entries):
        return [menus.item("Check All", lambda: _check_range(win, lst, 0, lst.GetCount(), True)),
                menus.item("Uncheck All", lambda: _check_range(win, lst, 0, lst.GetCount(), False))]
    e = entries[i]
    url = e.get("url") or ""
    on = lst.IsChecked(i)
    who = e.get("uploader") or ""
    items = []
    if play:
        items.append(menus.item("Play or Pause", play, True, "Ctrl+P"))
    items += [
        menus.item("Uncheck" if on else "Check", lambda: (lst.Check(i, not on), win._count(speak=True)),
                   keys="Space"),
        menus.item("Download This One Now", lambda: main.download_now(e)),
        menus.item("Look Up Exact Date and Details", lambda: look_up_row(win, lst, entries, i, main), True, "Ctrl+I"),
    ]
    if e.get("channel_url"):
        items.append(menus.item("Everything from %s..." % (who or "This Channel"),
                                lambda: main.add_links([e["channel_url"]])))
    if who and hasattr(win, "search_for"):
        items.append(menus.item("Search for %s" % who, lambda: win.search_for(who)))
    items += [
        menus.SEP,
        menus.item("Open the Web Page", lambda: main.open_page(url), url.startswith("http")),
        menus.item("Copy Link", lambda: main.copy(url, "Link copied."), bool(url)),
        menus.item("Copy Title", lambda: main.copy(e.get("title") or url, "Title copied.")),
        menus.SEP,
        menus.item("Check All", lambda: _check_range(win, lst, 0, lst.GetCount(), True)),
        menus.item("Uncheck All", lambda: _check_range(win, lst, 0, lst.GetCount(), False)),
        menus.item("Check from Here to the End", lambda: _check_range(win, lst, i, lst.GetCount(), True)),
        menus.item("Check from the Start to Here", lambda: _check_range(win, lst, 0, i + 1, True)),
    ]
    return items


def _check_range(win, lst, a, b, on):
    for k in range(a, b):
        lst.Check(k, on)
    win._count(speak=True)


def look_up_row(win, lst, entries, i, main):
    """Ask the site for everything about one row (an exact date where the list only had "about 2
    years ago", the length and date YouTube Music's song search leaves out), update the row, say it."""
    e = entries[i]
    from .system import announce
    announce("Looking up %s." % (e.get("title") or "it"))

    def done(info):
        if not win or i >= len(entries) or entries[i] is not e:
            return
        if info.get("error"):
            announce(info["error"])
            return
        for k in ("uploaded", "uploaded_ts", "approx", "views", "duration", "uploader"):
            if info.get(k):
                e[k] = info[k]
        if info.get("uploaded"):
            e.pop("uploaded_ts", None)
            e.pop("approx", None)
        checked = lst.IsChecked(i)
        lst.SetString(i, entry_words(i + 1, e))
        lst.Check(i, checked)  # some systems clear the check when the text changes
        bits = [x for x in (words.uploaded(e), words.views(e.get("views")),
                            words.duration(e.get("duration")) if e.get("duration") else "",
                            "by " + e["uploader"] if e.get("uploader") else "") if x]
        said = ", ".join(bits) or "Nothing more is known about it."
        announce(said[0].upper() + said[1:] + ".")
    main.look_up(e.get("url") or "", done)


class SoundPicker(wx.Dialog):
    """Every sound the app makes, each with a checkbox (checked plays). Return or Play Selected
    plays the selected one; Hear Them All says each name, then plays it."""

    def __init__(self, parent, off: list, theme, volume):
        super().__init__(parent, title="Choose Sounds", size=(560, 480),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        from .system import SOUNDS
        self.keys = [k for k, _, _ in SOUNDS]
        self.theme, self.volume = theme, volume
        s = wx.BoxSizer(wx.VERTICAL)
        s.Add(wx.StaticText(self, label="Checked sounds play; unchecked ones stay quiet. Return plays the "
                                        "selected one."), 0, wx.ALL, 8)
        self.list = wx.CheckListBox(self, choices=[w for _, w, _ in SOUNDS])
        mac_accessibility_label(self.list, "Sounds")
        for i, k in enumerate(self.keys):
            self.list.Check(i, k not in off)
        s.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
        row = wx.BoxSizer(wx.HORIZONTAL)
        play = wx.Button(self, label="Play Selected")
        play.SetToolTip("Plays the selected sound in the chosen set (Return).")
        allb = wx.Button(self, label="Hear Them All")
        allb.SetToolTip("Says each sound's name, then plays it, one after another.")
        row.Add(play, 0, wx.RIGHT, 6)
        row.Add(allb, 0)
        s.Add(row, 0, wx.ALL, 6)
        brow, ok, _ = buttons(self, "Use These")
        s.Add(brow, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(s)
        play.Bind(wx.EVT_BUTTON, lambda e: self.play_selected())
        allb.Bind(wx.EVT_BUTTON, lambda e: self.hear_all())
        self.list.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.play_selected())
        self.list.Bind(wx.EVT_KEY_DOWN, self.on_key)
        self.list.Bind(wx.EVT_CHECKLISTBOX, lambda e: self._said(e.GetInt()))
        self.timers = []
        self.list.SetFocus()
        self.list.SetSelection(0)

    def on_key(self, event):
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.play_selected()
        else:
            event.Skip()

    def _said(self, i):
        from .system import announce
        announce("%s: %s." % (self.list.GetString(i), "on" if self.list.IsChecked(i) else "off"))

    def play_selected(self):
        from .system import play
        i = self.list.GetSelection()
        if i != wx.NOT_FOUND:
            play(self.keys[i], self.theme(), self.volume())

    def hear_all(self):
        """Name, pause, sound, for every one: announce first, then play (never both at once)."""
        from .system import announce, play
        for t in self.timers:
            t.Stop()
        self.timers = []
        at = 0
        for i, k in enumerate(self.keys):
            self.timers.append(wx.CallLater(at + 1, announce, self.list.GetString(i)))
            self.timers.append(wx.CallLater(at + 1700, play, k, self.theme(), self.volume()))
            at += 3400

    def off(self) -> list:
        return [k for i, k in enumerate(self.keys) if not self.list.IsChecked(i)]

    def Destroy(self):
        for t in self.timers:
            t.Stop()
        return super().Destroy()


class CheckList(wx.Dialog):
    """Check the items you want. Reads item by item; Space checks; the count is always stated."""

    def __init__(self, parent, title: str, intro: str, entries: list[dict], ok_label="Download Checked",
                 checked=True):
        super().__init__(parent, title=title, size=(720, 560), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.entries = entries
        self.ok_label = ok_label
        self.main = parent
        s = wx.BoxSizer(wx.VERTICAL)
        s.Add(wx.StaticText(self, label=intro), 0, wx.ALL, 8)
        self.list = wx.CheckListBox(self, choices=[entry_words(i + 1, e) for i, e in enumerate(entries)])
        mac_accessibility_label(self.list, "Items")
        if checked:
            for i in range(len(entries)):
                self.list.Check(i)
        s.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
        self.count = wx.StaticText(self, label="")
        s.Add(self.count, 0, wx.ALL, 6)
        row = wx.BoxSizer(wx.HORIZONTAL)
        b_all = wx.Button(self, label="Check All")
        b_none = wx.Button(self, label="Uncheck All")
        row.Add(b_all, 0, wx.RIGHT, 6)
        row.Add(b_none, 0)
        s.Add(row, 0, wx.ALL, 6)
        brow, self.ok, _ = buttons(self, ok_label)
        s.Add(brow, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(s)
        b_all.Bind(wx.EVT_BUTTON, lambda e: self._set_all(True))
        b_none.Bind(wx.EVT_BUTTON, lambda e: self._set_all(False))
        self.list.Bind(wx.EVT_CHECKLISTBOX, lambda e: self._count(speak=True))
        menus.attach(self.list, lambda: entry_menu(self, self.list, self.entries, self.main))
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
        self.count.SetLabel("%d of %d checked." % (k, self.list.GetCount()))
        if speak:  # VoiceOver re-reads the row before the check lands, so say the result
            from .system import announce
            announce("%d checked." % k)
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


class Search(wx.Frame):
    """Search a site by words and check what to download, without visiting the site.

    A window of its own, with its own menu bar, not a dialog. As a modal dialog it held the
    whole app's keyboard: with the player raised over it, Quit, Close and every shortcut did
    nothing. As a modeless dialog on the Mac it borrowed whichever menu bar was up last, so
    Command-Delete in the results could remove a download from the main list, and Command-W
    after a preview closed the player instead. Its own menus settle both."""

    def __init__(self, parent, query: str, site: str, run_search, play=None, player=None, on_done=None):
        super().__init__(parent, title="Search", size=(760, 600))
        self.main = parent
        self.run_search = run_search
        self.on_done = on_done  # (window, chosen entries), when it closes
        self.results = []
        self.last_query = ""
        self.searched = ("", "")  # (words, site) the results in the list belong to
        self.next_start = 1
        self.has_more = False
        self.loading = False
        p = self.panel = wx.Panel(self)  # a panel gives a frame Tab between controls
        s = wx.BoxSizer(wx.VERTICAL)
        top = wx.BoxSizer(wx.HORIZONTAL)
        lab = wx.StaticText(p, label="Search for:")
        self.query = wx.TextCtrl(p, value=query, style=wx.TE_PROCESS_ENTER)
        mac_accessibility_label(self.query, "Search for")
        top.Add(lab, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        top.Add(self.query, 1, wx.RIGHT, 6)
        on_lab = wx.StaticText(p, label="on")
        self.site = wx.Choice(p, choices=[name for _, name, _ in SEARCH_SITES])
        keys = [k for k, _, _ in SEARCH_SITES]
        self.site.SetSelection(keys.index(site) if site in keys else 0)
        mac_accessibility_label(self.site, "Search on")
        top.Add(on_lab, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        top.Add(self.site, 0, wx.RIGHT, 6)
        self.go = wx.Button(p, label="Search")
        top.Add(self.go, 0)
        s.Add(top, 0, wx.EXPAND | wx.ALL, 8)
        orow = wx.BoxSizer(wx.HORIZONTAL)
        olab = wx.StaticText(p, label="Order:")
        self.order = wx.Choice(p, choices=[w for _, w in ORDERS])
        self.order.SetSelection(0)
        mac_accessibility_label(self.order, "Order")
        self.order.SetToolTip("Sorts the results loaded so far, keeping what's checked. More results that "
                              "come in are sorted in too.")
        orow.Add(olab, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        orow.Add(self.order, 0)
        s.Add(orow, 0, wx.LEFT | wx.RIGHT, 8)
        self.status = wx.StaticText(p, label="Type words and press Return.")
        s.Add(self.status, 0, wx.ALL, 6)
        self.list = wx.CheckListBox(p, choices=[])
        mac_accessibility_label(self.list, "Results")
        s.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
        brow = wx.BoxSizer(wx.HORIZONTAL)
        brow.AddStretchSpacer()
        self.cancel = wx.Button(p, wx.ID_CANCEL, "Close")
        self.cancel.SetToolTip("Closes Search without downloading (Escape, or %s-W)." % CMD)
        brow.Add(self.cancel, 0, wx.ALL, 6)
        self.play = play
        self.get_player = player or (lambda: None)
        if play:
            self.play_btn = wx.Button(p, label="Play Selected")
            self.play_btn.SetToolTip("Listen to the selected result without downloading it, to check it's the "
                                     "right one; press again to pause (%s-P). The search stays open." % CMD)
            self.list.Bind(wx.EVT_LISTBOX, lambda e: (self._preview_label(), self._near_end()))
            brow.Add(self.play_btn, 0, wx.ALL, 6)
            self.play_btn.Bind(wx.EVT_BUTTON, self.on_play)
        self.more_btn = wx.Button(p, label="More Results")
        self.more_btn.SetToolTip("Gets the next %d results. They also come by themselves when you reach the end "
                                 "of the list. There's no limit but the site's own (%s-Shift-M)."
                                 % (SEARCH_PAGE, CMD))
        self.more_btn.Disable()
        brow.Add(self.more_btn, 0, wx.ALL, 6)
        self.more_btn.Bind(wx.EVT_BUTTON, lambda e: self.more())
        self.ok = wx.Button(p, wx.ID_OK, "Download Checked")
        self.ok.SetToolTip("Adds the checked results to the downloads list and closes Search (%s-Return)." % CMD)
        brow.Add(self.ok, 0, wx.ALL, 6)
        self.ok.Disable()
        s.Add(brow, 0, wx.EXPAND | wx.ALL, 6)
        p.SetSizer(s)
        self._menus()
        self.go.Bind(wx.EVT_BUTTON, self.on_search)
        self.order.Bind(wx.EVT_CHOICE, lambda e: self.reorder(speak=True))
        self.query.Bind(wx.EVT_TEXT_ENTER, self.on_search)
        self.list.Bind(wx.EVT_CHECKLISTBOX, lambda e: self._count(speak=True))
        if not play:
            self.list.Bind(wx.EVT_LISTBOX, lambda e: self._near_end())
        self.list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_activate)
        self.ok.Bind(wx.EVT_BUTTON, lambda e: self.download_checked())
        self.cancel.Bind(wx.EVT_BUTTON, lambda e: self._finish([]))
        self.Bind(wx.EVT_CLOSE, lambda e: self._finish([]))
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)
        menus.attach(self.list, lambda: entry_menu(self, self.list, self.results, self.main,
                                                   play=(lambda: self.on_play(None)) if self.play else None))
        self.query.SetFocus()
        if query.strip():
            wx.CallAfter(self.on_search, None)

    def _menus(self):
        bar = wx.MenuBar()

        def add(menu, label, fn, wid=wx.ID_ANY):
            item = menu.Append(wid, label)
            self.Bind(wx.EVT_MENU, lambda e: fn(), item)
        f = wx.Menu()
        add(f, "&Search\tCtrl+F", lambda: (self.query.SetFocus(), self.query.SelectAll()))
        add(f, "&Download Checked\tCtrl+Return", self.download_checked)
        add(f, "&More Results\tCtrl+Shift+M", self.more)
        add(f, "Look Up Exact Date and &Info\tCtrl+I", self._look_up_selected)
        add(f, "Actions for the Selected &Result...\tCtrl+K", lambda: self.list._context_menu())
        if self.play:
            add(f, "&Play or Pause Selected\tCtrl+P", lambda: self.on_play(None))
        f.AppendSeparator()
        add(f, "Close Searc&h\tCtrl+W", lambda: self._finish([]))
        add(f, "&Quit\tCtrl+Q", lambda: self.main.Close(), wx.ID_EXIT)
        if sys.platform == "darwin":
            add(f, "Settings...\tCtrl+,", lambda: self.main.on_settings(None), wx.ID_PREFERENCES)
            add(f, "About", lambda: self.main.on_about(None), wx.ID_ABOUT)
        ed = wx.Menu()  # on the Mac, Command-V in a field needs a Paste item to answer it
        ed.Append(wx.ID_UNDO, "&Undo\tCtrl+Z")
        ed.AppendSeparator()
        ed.Append(wx.ID_CUT, "Cu&t\tCtrl+X")
        ed.Append(wx.ID_COPY, "&Copy\tCtrl+C")
        ed.Append(wx.ID_PASTE, "&Paste\tCtrl+V")
        ed.Append(wx.ID_SELECTALL, "Select &All\tCtrl+A")
        v = wx.Menu()
        add(v, "Go to the Search &Field\tCtrl+L", lambda: self.query.SetFocus())
        add(v, "Go to the &Results\tCtrl+D", lambda: self.list.SetFocus())
        v.AppendSeparator()
        add(v, "Go to the D&ownloads Window\tCtrl+1", self.main.on_to_main)
        add(v, "Go to the &Player\tCtrl+2", self.main.on_to_player)
        bar.Append(f, "&File")
        bar.Append(ed, "&Edit")
        bar.Append(v, "&View")
        self.SetMenuBar(bar)

    def on_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE and not event.HasAnyModifiers():
            self._finish([])
        else:
            event.Skip()

    def download_checked(self):
        chosen = self.chosen()
        if not chosen:
            self.status.SetLabel("Nothing checked yet. Check results with Space, then Download Checked.")
            from .system import announce
            announce(self.status.GetLabel())
            return
        self._finish(chosen)

    def _look_up_selected(self):
        i = self.list.GetSelection()
        if i == wx.NOT_FOUND or i >= len(self.results):
            self.status.SetLabel("Select a result first.")
            return
        look_up_row(self, self.list, self.results, i, self.main)

    def search_for(self, words_: str):
        self.query.SetValue(words_)
        self.on_search(None)

    def show_again(self, q: str):
        """Brought forward by the main window (Command-F, or words in the Link field). A new
        query searches; the same one keeps the results and what's checked."""
        self.Raise()
        if q and q != self.last_query:
            self.query.SetValue(q)
            self.on_search(None)
        elif self.results:
            self.list.SetFocus()
        else:
            self.query.SetFocus()

    def site_key(self):
        return SEARCH_SITES[self.site.GetSelection()][0]

    def _finish(self, chosen):
        """Close for good. A modeless dialog's Cancel only hides it, which left an invisible
        Search window behind; destroy it instead, then hand over what was checked."""
        if getattr(self, "_finished", False):  # Command-W can arrive by menu and by accelerator
            return
        self._finished = True
        done, self.on_done = self.on_done, None
        self.Hide()
        if done:
            done(self, chosen)
        wx.CallAfter(lambda: self and self.Destroy())

    def on_search(self, _):
        q = self.query.GetValue().strip()
        if not q:
            self.query.SetFocus()
            return
        self.last_query = q
        site_key = self.site_key()
        site = SEARCH_SITES[self.site.GetSelection()][1]
        self.searched = (q, site_key)
        self.results = []
        self.list.Set([])
        self.has_more = False
        self.repeats = 0
        self.next_start = 1  # the site's position the next page begins at (repeats dropped don't count)
        self._count()
        self.status.SetLabel("Searching %s for %s..." % (site, q))
        self._fetch(q, site_key, site, 1)

    def more(self):
        """The next page of the same search. No ceiling: it stops only when the site has nothing more."""
        q, site_key = self.searched
        if not q or self.loading:
            return
        if not self.has_more:
            self.status.SetLabel("That's every result %s has for %s." % (self._site_name(site_key), q))
            from .system import announce, cue
            cue("no_more")
            announce(self.status.GetLabel())
            return
        self.status.SetLabel("Getting more results...")
        self._fetch(q, site_key, self._site_name(site_key), self.next_start)

    def _near_end(self):
        """Reaching the last row asks for more by itself, the way a feed does."""
        i = self.list.GetSelection()
        if self.has_more and not self.loading and i != wx.NOT_FOUND and i >= len(self.results) - 1:
            self.more()

    @staticmethod
    def _site_name(key):
        return next((name for k, name, _ in SEARCH_SITES if k == key), key)

    def _fetch(self, q, site_key, site, start):
        self.loading = True
        self.go.Disable()
        self.more_btn.Disable()

        def work():
            res = self.run_search(q, site_key, start)
            wx.CallAfter(self._show, q, site_key, site, start, res)
        threading.Thread(target=work, daemon=True).start()

    def _show(self, q, site_key, site, start, res):
        if not self:
            return
        if (q, site_key) != self.searched or start != self.next_start:
            return  # a newer search started meanwhile; this page belongs to the old one
        self.loading = False
        self.go.Enable()
        self.next_start = start + SEARCH_PAGE
        seen = {e["url"] for e in self.results}
        fresh = [e for e in (res or []) if e["url"] not in seen]
        first_new = len(self.results)
        for i, e in enumerate(fresh):
            e["_rank"] = first_new + i  # the site's own order, kept for "As the site ranks them"
        self.results.extend(fresh)
        if ORDERS[self.order.GetSelection()][0] == "site":
            for i, e in enumerate(fresh):
                self.list.Append(entry_words(first_new + i + 1, e))  # appended: checks so far stay checked
        else:
            self.reorder()
        # Only an empty page is the end. A short page usually is too, but a site can drop an entry
        # it can't list; and YouTube repeats some results from page to page (dropped above), so a
        # page of nothing but repeats isn't the end either: fetch the next one straight away.
        self.has_more = bool(res)
        self.more_btn.Enable(self.has_more)
        self.repeats = 0 if fresh or not res else getattr(self, "repeats", 0) + 1
        if res and not fresh and self.repeats < 3:
            wx.CallAfter(self.more)
            return
        from .system import announce, cue
        cue("results" if fresh else "no_more")
        if not self.results:
            self.status.SetLabel("Nothing found on %s for %s." % (site, q))
            self.query.SetFocus()
        elif start == 1:
            self.status.SetLabel("%s on %s for %s. Check with Space, then Download Checked. More come when you "
                                 "reach the end." % (words.n(len(self.results), "result"), site, q))
            self.list.SetFocus()
            self.list.SetSelection(0)
        elif fresh:
            self.status.SetLabel("%d more, %s in all." % (len(fresh), words.n(len(self.results), "result")))
        else:
            self.status.SetLabel("That's every result %s has for %s: %s." % (site, q,
                                                                             words.n(len(self.results), "result")))
        announce(self.status.GetLabel())
        self._count()

    def reorder(self, speak=False):
        """Sort what's loaded by the Order choice, keeping checks and the selected result."""
        how = ORDERS[self.order.GetSelection()][0]
        checked = {self.results[i]["url"] for i in self.list.GetCheckedItems() if i < len(self.results)}
        sel = self.list.GetSelection()
        keep = self.results[sel]["url"] if 0 <= sel < len(self.results) else None
        self.results = order_results(self.results, how)
        self.list.Set([entry_words(i + 1, e) for i, e in enumerate(self.results)])
        for i, e in enumerate(self.results):
            if e["url"] in checked:
                self.list.Check(i)
        if self.results:
            at = next((i for i, e in enumerate(self.results) if e["url"] == keep), 0) if not speak else 0
            self.list.SetSelection(at)
        if speak:
            from .system import announce
            missing = sum(1 for e in self.results if sort_value(e, how) is None)
            note = (" %d the site didn't give that for are at the end." % missing) if missing and how != "site" else ""
            announce("%s, %s.%s" % (ORDERS[self.order.GetSelection()][1], words.n(len(self.results), "result"), note))

    def _count(self, speak=False):
        k = len(self.list.GetCheckedItems())
        self.ok.SetLabel("Download Checked (%d)" % k)
        if speak:
            from .system import announce
            announce("%d checked." % k)
        self.ok.Enable(k > 0)
        self.panel.Layout()

    def on_activate(self, _):
        i = self.list.GetSelection()
        if i != wx.NOT_FOUND:
            self.list.Check(i, not self.list.IsChecked(i))
            self._count()

    def chosen(self):
        return [self.results[i] for i in self.list.GetCheckedItems()]

    def _previewing(self):
        """The player, if it's on the selected result."""
        i = self.list.GetSelection()
        pl = self.get_player()
        if pl and pl.item and 0 <= i < len(self.results) and pl.item.get("url") == self.results[i]["url"]:
            return pl
        return None

    def _preview_label(self):
        if not self:
            return
        pl = self._previewing()
        self.play_btn.SetLabel("Pause Preview" if pl and pl.loaded and pl.playing() else "Play Selected")
        self.panel.Layout()

    def on_play(self, _):
        """Play the selected result; press again to pause. The player opens behind Search and
        the keyboard stays here, so you can go on through the results; this button stands in for
        the player's own Space."""
        i = self.list.GetSelection()
        if i == wx.NOT_FOUND or i >= len(self.results):
            self.status.SetLabel("Select a result first, then Play Selected.")
            return
        pl = self._previewing()
        if pl:
            pl.toggle()
        else:
            self.play([self.results[i]])
            self.Raise()
            self.list.SetFocus()
            self.status.SetLabel("Getting %s ready to play." % (self.results[i].get("title") or "it"))
        wx.CallLater(400, self._preview_label)


class DescribeDialog(wx.Dialog):
    """Audio description for one video: its own described track, published described
    versions, or make one. Each option is a row; the buttons act on the selected row."""

    def __init__(self, parent, url: str, title: str, run_find, actions: dict, run_more=None):
        super().__init__(parent, title="Audio Description", size=(760, 460),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.url, self.title, self.actions = url, title, actions
        self.run_more = run_more
        self.options: list[dict] = []
        self.next_start = 1
        self.more_left = False
        self.looking = True
        s = wx.BoxSizer(wx.VERTICAL)
        self.status = wx.StaticText(self, label="Looking for audio description for %s..." % (title or url))
        s.Add(self.status, 0, wx.ALL, 10)
        self.list = wx.ListBox(self, style=wx.LB_SINGLE)
        mac_accessibility_label(self.list, "What's available")
        s.Add(self.list, 1, wx.EXPAND | wx.ALL, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.play_btn = wx.Button(self, label="Play")
        self.dl_btn = wx.Button(self, label="Download")
        self.play_btn.SetToolTip("Closes this window and plays the selected one in the player.")
        self.make_btn = wx.Button(self, label="Make Description")
        self.make_btn.SetToolTip("Claude reads frames from the video at each change of shot and writes what it "
                                 "sees, every moment of it. About a minute for a short video, much longer for a "
                                 "film. Machine-made and unchecked.")
        self.more_btn = wx.Button(self, label="Look Further")
        self.more_btn.SetToolTip("Searches deeper for described versions made by people, %d search results at "
                                 "a time, for as long as the site has more." % describe.VERSIONS_PAGE)
        close = wx.Button(self, wx.ID_CANCEL, "Close")
        for b in (self.play_btn, self.dl_btn, self.make_btn, self.more_btn):
            row.Add(b, 0, wx.RIGHT, 6)
            b.Disable()
        row.AddStretchSpacer()
        row.Add(close, 0)
        s.Add(row, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(s)
        self.SetEscapeId(wx.ID_CANCEL)
        self.list.Bind(wx.EVT_LISTBOX, lambda e: self._buttons())
        self.list.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._act("play"))
        self.play_btn.Bind(wx.EVT_BUTTON, lambda e: self._act("play"))
        self.dl_btn.Bind(wx.EVT_BUTTON, lambda e: self._act("download"))
        self.make_btn.Bind(wx.EVT_BUTTON, lambda e: self._act("make"))
        self.more_btn.Bind(wx.EVT_BUTTON, lambda e: self.look_further())
        menus.attach(self.list, self.row_menu)
        threading.Thread(target=lambda: wx.CallAfter(self._found, run_find(url)), daemon=True).start()

    def _found(self, res):
        if not self:
            return
        about = res.get("about") or {}
        self.title = about.get("title") or self.title
        opts = []
        if about.get("track"):
            opts.append({"kind": "track", "format": about["track"],
                         "words": "This video has its own described track (%s): real description, by a person."
                                  % about.get("track_words", "described")})
        opts.extend(self._version_row(c) for c in res.get("candidates") or [])
        self.next_start = describe.VERSIONS_PAGE + 1
        self.more_left = bool(res.get("searched")) and bool(self.run_more)
        self.looking = False
        if about.get("has_video", True):
            if about.get("can_make"):
                opts.append({"kind": "make", "words": "Make a description: Claude reads the picture. Machine-made "
                                                      "and unchecked. About a minute for a short video; a long film "
                                                      "takes much longer, since every moment is described."})
            else:
                opts.append({"kind": "none", "words": "Making one needs the Claude command-line tool "
                                                      "(claude.com/code), which isn't on this computer."})
        self.options = opts
        self.list.Set([o["words"] for o in opts])
        found = sum(1 for o in opts if o["kind"] in ("track", "version"))
        if found:
            msg = "%s for %s. Described versions are by people, so they come first." % (
                words.n(found, "described option"), self.title)
        elif any(o["kind"] == "make" for o in opts):
            msg = ("No described version turned up for %s in the first %d search results. Look Further "
                   "searches deeper, or you can make a description." % (self.title, describe.VERSIONS_PAGE))
        else:
            msg = "No audio description found for %s." % self.title
        self.status.SetLabel(msg)
        self.status.Wrap(700)
        from .system import announce
        announce(msg)
        if opts:
            self.list.SetSelection(0)
            self.list.SetFocus()
        self._buttons()
        self.Layout()

    def row_menu(self):
        o = self._selected()
        if not o:
            return []
        main = wx.GetApp().frame if hasattr(wx.GetApp(), "frame") else None
        url = o.get("url") or ""
        items = []
        if o["kind"] in ("track", "version"):
            items += [menus.item("Play", lambda: self._act("play")),
                      menus.item("Download", lambda: self._act("download"))]
        if o["kind"] == "make":
            items.append(menus.item("Make Description", lambda: self._act("make")))
        if url and main:
            items += [menus.SEP, menus.item("Open the Web Page", lambda: main.open_page(url)),
                      menus.item("Copy Link", lambda: main.copy(url, "Link copied.")),
                      menus.item("Copy Title", lambda: main.copy(o.get("title") or url, "Title copied."))]
        if self.more_left:
            items += [menus.SEP, menus.item("Look Further", self.look_further, not self.looking)]
        return items

    @staticmethod
    def _version_row(c):
        return {"kind": "version", "url": c["url"], "title": c.get("title"),
                "words": "A described version: %s%s%s%s" % (
                    c.get("title"), ", " + words.duration(c["duration"]) if c.get("duration") else "",
                    ", by " + c["uploader"] if c.get("uploader") else "",
                    "".join(", " + x for x in (words.uploaded(c), words.views(c.get("views"))) if x))}

    def look_further(self):
        if self.looking or not self.more_left:
            return
        self.looking = True
        self.more_btn.Disable()
        start = self.next_start
        self.status.SetLabel("Looking further, from search result %d..." % start)
        from .system import announce
        announce(self.status.GetLabel())
        threading.Thread(target=lambda: wx.CallAfter(self._more_found, start, self.run_more(self.title, start)),
                         daemon=True).start()

    def _more_found(self, start, res):
        if not self:
            return
        self.looking = False
        self.next_start = start + describe.VERSIONS_PAGE
        self.more_left = bool(res.get("searched"))
        have = {o.get("url") for o in self.options}
        fresh = [self._version_row(c) for c in res.get("candidates") or [] if c["url"] not in have]
        at = next((i for i, o in enumerate(self.options) if o["kind"] in ("make", "none")), len(self.options))
        self.options[at:at] = fresh  # people's versions stay above Make a description
        self.list.Set([o["words"] for o in self.options])
        end = start + describe.VERSIONS_PAGE - 1
        if fresh:
            msg = "Found %s more in search results %d to %d." % (words.n(len(fresh), "described version"), start, end)
            self.list.SetSelection(at)
        elif self.more_left:
            msg = "None in search results %d to %d. Look Further goes on." % (start, end)
            self.list.SetSelection(max(0, at - 1) if self.options else wx.NOT_FOUND)
        else:
            msg = "That's the end of the search. Nothing more."
        self.status.SetLabel(msg)
        self.status.Wrap(700)
        from .system import announce, cue
        cue("results" if fresh else "no_more")
        announce(msg)
        self.list.SetFocus()
        self._buttons()
        self.Layout()

    def _selected(self):
        i = self.list.GetSelection()
        return self.options[i] if 0 <= i < len(self.options) else None

    def _buttons(self):
        o = self._selected()
        k = o and o["kind"]
        self.play_btn.Enable(k in ("track", "version"))
        self.dl_btn.Enable(k in ("track", "version"))
        self.make_btn.Enable(k == "make")
        self.more_btn.Enable(self.more_left and not self.looking)

    def _act(self, what):
        o = self._selected()
        if not o:
            return
        if o["kind"] == "make" and what != "download":
            self.actions["make"]()
            self.EndModal(wx.ID_OK)
        elif o["kind"] == "track":
            self.actions["track_" + what](o["format"])
            self.EndModal(wx.ID_OK)
        elif o["kind"] == "version":
            self.actions["version_" + what]({"url": o["url"], "title": o["title"]})
            self.EndModal(wx.ID_OK)
