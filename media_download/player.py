"""The player: downloaded files, or links played without downloading.

Built for listening first and looking second, and fine for both:
- Space plays and pauses; Left and Right skip (the length is a setting), Shift for a
  minute; Up and Down change the volume; Page Up and Page Down change item; [ and ] (or < and >) change speed, without
  changing pitch, and N or backslash makes it normal; T says the time; C turns captions on and off. Every one is also in the
  Playback menu and on a labelled button.
- Nothing is spoken unless asked for (T, or a new item starting while the window is in
  the background). The title, time and captions are large on screen.
- Podcasts and audiobooks: each item remembers where it stopped, and there's a sleep
  timer that fades out.
- Captions show under the picture, from downloaded subtitles or the stream's own.

wx.media.MediaCtrl does the playing: AVFoundation on the Mac (files, HLS, Opus and FLAC
included), Windows Media Player's engine on Windows.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

import wx
import wx.media

from . import describe, engine, words
from .speech import Reader
from . import geometry
from .manager import run_task
from .system import (announce, mac_accessibility_label, mac_focus, mac_has_focus, mac_value_description, open_path,
                     reveal)

# Down to a quarter, for following something fast or learning a part by ear; up to three times,
# where plenty of people listen to podcasts and lectures. Pitch is kept at every speed (verified
# on the Mac: 3.0 measured 2.98 times real time).
SPEEDS = [0.25, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9, 1.0, 1.1, 1.2, 1.25, 1.3, 1.4, 1.5, 1.6, 1.75, 1.8, 2.0,
          2.25, 2.5, 2.75, 3.0]
NORMAL = SPEEDS.index(1.0)
AD_MODES = [("pause", "pauses the video to read"), ("over", "reads over the video, with the sound lowered"),
            ("off", "off")]
SLEEP_CHOICES = [(0, "Off"), (15, "15 minutes"), (30, "30 minutes"), (45, "45 minutes"), (60, "1 hour"),
                 (-1, "At the end of this item")]
POSITIONS = os.path.join(engine.SUPPORT, "positions.json")
MEDIA_EXT = (".mp3", ".m4a", ".mp4", ".m4v", ".mov", ".opus", ".ogg", ".oga", ".flac", ".wav", ".aac", ".webm",
             ".mkv", ".aiff", ".aif", ".caf")


def playable_file(paths: list[str]) -> str | None:
    """The file to play from a download's files: the main one, not a chapter or a transcript."""
    media = [p for p in paths if os.path.splitext(p)[1].lower() in MEDIA_EXT and os.path.exists(p)]
    if not media:
        return None
    # Chapter files share the main file's name plus " - 01 ..."; the shortest name is the whole.
    return min(media, key=lambda p: len(os.path.basename(p)))


def captions_for(path: str) -> list:
    """Cues from subtitles saved beside a downloaded file ("Song.en.srt"), if there are any."""
    folder, base = os.path.split(path)
    stem = os.path.splitext(base)[0]
    try:
        for name in sorted(os.listdir(folder)):
            # "Intro.en.srt" belongs to Intro.m4a; "Intro (Live).en.srt" doesn't.
            if (name.startswith(stem + ".") and name.lower().endswith((".srt", ".vtt"))
                    and describe.SUFFIX.strip(" -") not in name):  # captions, not the description
                with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as fh:
                    return words.caption_cues(fh.read())
    except OSError:
        pass
    return []


# Speed keys by the character typed, not the key: [ ] and \ need Option or AltGr on many
# layouts (German, French, Nordic...), so a bare-key check never fired there. < and > are
# YouTube's keys and sit on Comma and Period, like the Windows Player menu's; N is on every
# layout.
SPEED_CHARS = {"[": "slower", "<": "slower", "]": "faster", ">": "faster", "\\": "normal", "n": "normal",
               "N": "normal"}


def speed_key(event) -> str | None:
    """'slower', 'faster' or 'normal' for a key press, or None. Command or Control means a
    shortcut for something else, so those never count."""
    if event.ControlDown() or event.RawControlDown() or event.MetaDown():
        return None
    ch = event.GetUnicodeKey()
    key = event.GetKeyCode()
    typed = chr(ch) if ch and ch != wx.WXK_NONE else (chr(key) if 0 < key < 256 else "")
    if event.ShiftDown() and key in (ord(","), ord(".")) and typed in (",", "."):
        typed = "<" if key == ord(",") else ">"  # the key code is the unshifted one
    if typed in ("n", "N") and event.GetModifiers() not in (0, wx.MOD_SHIFT):
        return None  # Option-N is a dead key for accents, not "normal"
    what = SPEED_CHARS.get(typed)
    return what


def speed_words(v: float) -> str:
    """'Normal', '1.5 times': "1.5x" is read aloud as "1.5 x"."""
    return "Normal" if v == 1.0 else ("%g times" % v)


class Positions:
    """Where each item was stopped, so a podcast or a long lecture picks up where it left off."""

    def __init__(self):
        try:
            with open(POSITIONS) as fh:
                self.data = json.load(fh)
        except (OSError, ValueError):
            self.data = {}

    def get(self, key: str) -> float:
        return float(self.data.get(key, 0) or 0)

    def set(self, key: str, seconds: float, length: float) -> None:
        # Not worth remembering the first 30 seconds or the last 30: start again from the top.
        if seconds < 30 or (length and seconds > length - 30):
            self.data.pop(key, None)
        else:
            self.data[key] = round(seconds, 1)
        if len(self.data) > 2000:
            for k in list(self.data)[:500]:
                del self.data[k]

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(POSITIONS), exist_ok=True)
            tmp = POSITIONS + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(self.data, fh)
            os.replace(tmp, POSITIONS)
        except OSError:
            pass


class PlayerFrame(wx.Frame):
    def __init__(self, main):
        super().__init__(None, title="Player", size=(820, 640))
        self.main = main
        self.cfg = main.cfg
        self.queue: list[dict] = []
        self.index = -1
        self.item: dict | None = None
        self.cues: list = []
        self.loaded = False
        self.load_started = 0.0
        self._gen = 0  # which play_index a stream lookup belongs to, so a stale one is dropped
        self._resolving = False
        self.ad_free_from = 0.0  # where the last description finished being read
        self.length = 0.0
        self.dragging = False
        self.last_second = -1
        self.positions = Positions()
        self.last_saved = 0.0
        self.sleep_at = 0.0
        self.sleep_left = 0.0  # a sleep timer's time left while paused by hand: it waits with you
        self.sleep_end_of_item = False
        self.fading = False
        self.base_volume = float(self.cfg.get("app_volume", 1.0))
        self.muted = False  # M: for this session only, so the app never opens silent
        self.speed = float(self.cfg.get("app_speed", 1.0))
        self.captions_on = bool(self.cfg.get("app_captions", True))
        self.reader = Reader(voice=self.cfg.get("app_ad_voice", "system"))
        self.ad_mode = self.cfg.get("app_ad_mode", "pause")
        self.ad_cues: list = []
        self.ad_next = 0
        self.ad_active = False
        self.ad_paused = False
        self.ad_text = ""

        p = self.panel = wx.Panel(self)
        s = wx.BoxSizer(wx.VERTICAL)
        big = wx.Font(wx.FontInfo(20).Bold())
        self.title = wx.StaticText(p, label="Nothing playing", style=wx.ST_ELLIPSIZE_END)
        self.title.SetFont(big)
        s.Add(self.title, 0, wx.EXPAND | wx.ALL, 12)
        self.byline = wx.StaticText(p, label="")
        s.Add(self.byline, 0, wx.LEFT | wx.RIGHT, 12)

        backend = wx.media.MEDIABACKEND_WMP10 if sys.platform == "win32" else ""
        self.media = wx.media.MediaCtrl(p, szBackend=backend, size=(640, 360))
        self.media.SetBackgroundColour(wx.BLACK)
        self.media_holder = s.Add(self.media, 1, wx.EXPAND | wx.ALL, 12)

        self.caption = wx.StaticText(p, label="", style=wx.ALIGN_CENTRE_HORIZONTAL | wx.ST_NO_AUTORESIZE)
        self.caption.SetFont(wx.Font(wx.FontInfo(18)))
        self.caption.SetMinSize((-1, 60))
        s.Add(self.caption, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.pos_label = wx.StaticText(p, label="Position:")
        self.slider = wx.Slider(p, minValue=0, maxValue=1, style=wx.SL_HORIZONTAL)
        mac_accessibility_label(self.slider, "Position")
        self.slider.SetToolTip("Where it's playing. Left and Right move by the skip length set in Settings; Shift with "
                               "them moves a minute. T says the time.")
        self.time = wx.StaticText(p, label="0:00")
        self.time.SetFont(wx.Font(wx.FontInfo(16)))
        row.Add(self.pos_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(self.slider, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        row.Add(self.time, 0, wx.ALIGN_CENTER_VERTICAL)
        s.Add(row, 0, wx.EXPAND | wx.ALL, 12)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.prev_btn = wx.Button(p, label="Previous")
        self.back_btn = wx.Button(p, label="Back")
        self.play_btn = wx.Button(p, label="Play")
        self.fwd_btn = wx.Button(p, label="Forward")
        self.next_btn = wx.Button(p, label="Next")
        for b, tip in ((self.prev_btn, "The previous item (Page Up%s)." % (", or Fn-Up" if sys.platform == "darwin" else "")),
                       (self.back_btn, "Back by the skip length (Left arrow; Shift-Left for a minute)."),
                       (self.play_btn, "Play or pause (Space)."),
                       (self.fwd_btn, "Forward by the skip length (Right arrow; Shift-Right for a minute)."),
                       (self.next_btn, "The next item (Page Down%s)." % (", or Fn-Down" if sys.platform == "darwin" else ""))):
            b.SetToolTip(tip)
            row.Add(b, 0, wx.RIGHT, 6)
        s.Add(row, 0, wx.LEFT | wx.RIGHT, 12)

        row = wx.BoxSizer(wx.HORIZONTAL)
        lab = wx.StaticText(p, label="Speed:")
        self.speed_choice = wx.Choice(p, choices=[speed_words(v) for v in SPEEDS])
        self.speed_choice.SetSelection(SPEEDS.index(self.speed) if self.speed in SPEEDS else NORMAL)
        mac_accessibility_label(self.speed_choice, "Speed")
        from .dialogs import fit_choices
        fit_choices(p)  # a Mac popup sizes itself to its first choice and cuts off the rest
        self.speed_choice.SetToolTip("How fast it plays, a quarter speed to three times, without changing the pitch. "
                                     "Remembered. [ and ], or < and >, step it; N goes back to normal.")
        vlab = wx.StaticText(p, label="Volume:")
        self.volume = wx.Slider(p, value=int(self.base_volume * 100), minValue=0, maxValue=100, size=(160, -1))
        mac_accessibility_label(self.volume, "Volume")
        mac_value_description(self.volume, "%d percent" % int(self.base_volume * 100))
        self.volume.SetToolTip("How loud the player is. Remembered. Up and Down Arrow change it anywhere in the "
                               "player, with Shift for small steps; M mutes.")
        self.download_btn = wx.Button(p, label="Download This")
        self.download_btn.SetToolTip("Download what's playing, in the main window's format; it joins the downloads "
                                     "list (%s-%s). Only for links, since a downloaded file is already saved."
                                     % (("Command", "Return") if sys.platform == "darwin" else ("Control", "Enter")))
        self.show_btn = wx.Button(p, label="Show the File")
        self.show_btn.SetToolTip("Show the playing file in %s (%s-R). Only for downloaded files, not links." % (
            "Finder" if sys.platform == "darwin" else "File Explorer", "Command" if sys.platform == "darwin" else "Control"))
        row.Add(lab, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        row.Add(self.speed_choice, 0, wx.RIGHT, 16)
        row.Add(vlab, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        row.Add(self.volume, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 16)
        row.Add(self.download_btn, 0, wx.RIGHT, 6)
        row.Add(self.show_btn, 0)
        s.Add(row, 0, wx.ALL, 12)

        qlab = wx.StaticText(p, label="Up next:")
        s.Add(qlab, 0, wx.LEFT | wx.RIGHT, 12)
        self.qlist = wx.ListBox(p, style=wx.LB_SINGLE, size=(-1, 110))
        mac_accessibility_label(self.qlist, "Up next")
        self.qlist.SetToolTip("Everything queued, in order. %s plays the selected one; %s-K lists what else "
                              "you can do with it." % (("Return", "Command") if sys.platform == "darwin"
                                                       else ("Enter", "Control")))
        s.Add(self.qlist, 0, wx.EXPAND | wx.ALL, 12)
        p.SetSizer(s)
        self.CreateStatusBar()
        self._menus()
        self._sync_menu()
        self._show_video(False)

        self.Bind(wx.media.EVT_MEDIA_LOADED, self.on_loaded, self.media)
        self.Bind(wx.media.EVT_MEDIA_FINISHED, self.on_finished, self.media)
        self.play_btn.Bind(wx.EVT_BUTTON, lambda e: self.toggle())
        self.back_btn.Bind(wx.EVT_BUTTON, lambda e: self.skip(-self.skip_len()))
        self.fwd_btn.Bind(wx.EVT_BUTTON, lambda e: self.skip(self.skip_len()))
        self.prev_btn.Bind(wx.EVT_BUTTON, lambda e: self.go(-1))
        self.next_btn.Bind(wx.EVT_BUTTON, lambda e: self.go(+1))
        self.speed_choice.Bind(wx.EVT_CHOICE, lambda e: self.set_speed(SPEEDS[self.speed_choice.GetSelection()]))
        self.volume.Bind(wx.EVT_SLIDER, lambda e: self.set_volume(self.volume.GetValue() / 100.0, say=False))
        self.slider.Bind(wx.EVT_SLIDER, self.on_slider_moved)
        self.slider.Bind(wx.EVT_SCROLL_THUMBTRACK, lambda e: setattr(self, "dragging", True))
        self.slider.Bind(wx.EVT_SCROLL_THUMBRELEASE, self.on_slider_release)
        self.slider.Bind(wx.EVT_SCROLL_LINEUP, lambda e: self.skip(-self.skip_len()))
        self.slider.Bind(wx.EVT_SCROLL_LINEDOWN, lambda e: self.skip(self.skip_len()))
        self.slider.Bind(wx.EVT_SCROLL_PAGEUP, lambda e: self.skip(-60))
        self.slider.Bind(wx.EVT_SCROLL_PAGEDOWN, lambda e: self.skip(60))
        self.download_btn.Bind(wx.EVT_BUTTON, lambda e: self.download_this())
        self.show_btn.Bind(wx.EVT_BUTTON, lambda e: self.show_file())
        self.qlist.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.play_index(self.qlist.GetSelection()))
        self.qlist.Bind(wx.EVT_KEY_DOWN, self.on_queue_key)
        from . import menus
        menus.attach(self.qlist, self.queue_menu)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_tick, self.timer)
        self.timer.Start(250)
        geometry.restore(self, main.ui, "player")
        self._update_buttons()

    # ------------------------------------------------------------------ menus

    def _menus(self):
        bar = wx.MenuBar()
        m = wx.Menu()

        def add(label, fn, wid=wx.ID_ANY):
            item = m.Append(wid, label)
            self.Bind(wx.EVT_MENU, lambda e: fn(), item)
            return item
        # Plain keys (Space, arrows, T, C, speed) are handled by on_key and written into the
        # names so the menu teaches them; menus can't carry bare keys on every system.
        add("Play or Pause (Space)", self.toggle)
        add("Back (Left Arrow)", lambda: self.skip(-self.skip_len()))
        add("Forward (Right Arrow)", lambda: self.skip(self.skip_len()))
        add("Back a Minute (Shift-Left)", lambda: self.skip(-60))
        add("Forward a Minute (Shift-Right)", lambda: self.skip(60))
        m.AppendSeparator()
        # Page Up and Page Down (Fn-Up and Fn-Down on a Mac laptop), so that from any other window
        # each of these is the same key with Command-Option (Control-Alt) added.
        add("Previous Item (Page Up)", lambda: self.go(-1))
        add("Next Item (Page Down)", lambda: self.go(+1))
        m.AppendSeparator()
        add("Slower ([ or <)", lambda: self.step_speed(-1))
        add("Faster (] or >)", lambda: self.step_speed(+1))
        add("Normal Speed (N)", lambda: self.set_speed(1.0))
        # Plain Up and Down, like Left and Right: Command-Down opens a file and Command-Shift-Up
        # moves a download in the main window, so the player no longer borrows them for volume.
        add("Louder (Up Arrow)", lambda: self.volume_step(+1))
        add("Quieter (Down Arrow)", lambda: self.volume_step(-1))
        add("A Little Louder (Shift-Up)", lambda: self.volume_step(+1, small=True))
        add("A Little Quieter (Shift-Down)", lambda: self.volume_step(-1, small=True))
        add("Mute or Unmute (M or K)", self.toggle_mute)  # K: the same letter as Control-Alt-K from anywhere
        add("Say the Speed and Volume (V)", self.say_levels)
        m.AppendSeparator()
        add("Say the Time (T)", self.say_time)
        # Checked and chosen marks, so the current state is read in the menu, not learned by changing it.
        self.captions_item = m.AppendCheckItem(wx.ID_ANY, "Captions (C)")
        self.Bind(wx.EVT_MENU, lambda e: self.toggle_captions(), self.captions_item)
        ad = wx.Menu()
        self.ad_items = {}
        for mode, words_ in AD_MODES:
            label = {"pause": "Pause the Video to Read", "over": "Read Over the Video", "off": "Off"}[mode]
            it = ad.AppendRadioItem(wx.ID_ANY, label)
            self.ad_items[mode] = it
            self.Bind(wx.EVT_MENU, lambda e, mm=mode: self.set_ad(mm), it)
        m.AppendSubMenu(ad, "Audio Description (D cycles)")
        add("Find or Make Audio Description...\tCtrl+Shift+A", self.find_description)
        sleep = wx.Menu()
        for minutes, label in SLEEP_CHOICES:
            item = sleep.Append(wx.ID_ANY, label)
            self.Bind(wx.EVT_MENU, lambda e, mm=minutes: self.set_sleep(mm), item)
        m.AppendSubMenu(sleep, "Sleep Timer")
        m.AppendSeparator()
        add("Download This\tCtrl+Return", self.download_this)  # downloading is Command-Return everywhere
        add("Show the File\tCtrl+R", self.show_file)
        add("Actions for the Selected Queue Item...\tCtrl+K", lambda: self.qlist._context_menu())
        add("Close Player\tCtrl+W", self.Close)
        add("Go to the Downloads Window\tCtrl+1", self.to_main)
        m.AppendSeparator()
        add("Bigger Text\tCtrl+=", lambda: self.main._text_size(+2))
        add("Smaller Text\tCtrl+-", lambda: self.main._text_size(-2))
        add("Actual Size\tCtrl+0", lambda: self.main._text_size(0))
        m.AppendSeparator()
        # Quit, Settings and About belong to the app, not the window: on the Mac they live in the
        # app menu, which takes them from whichever window is in front. Without them here,
        # Command-Q did nothing while the player was in front.
        add("&Quit\tCtrl+Q", lambda: self.main.Close(), wx.ID_EXIT)
        if sys.platform == "darwin":
            add("Settings...\tCtrl+,", lambda: self.main.on_settings(None), wx.ID_PREFERENCES)
            add("About", lambda: self.main.on_about(None), wx.ID_ABOUT)
        else:  # Control-Comma did nothing in the player on Windows
            add("Setti&ngs...\tCtrl+,", lambda: self.main.on_settings(None))
        bar.Append(m, "&Playback")
        self.SetMenuBar(bar)
        # The same Command-Option keys as the Player menu in the other windows, so one set of
        # keys works everywhere; here the plain keys (Space, M, V...) work too.
        from .menus import PLAYER_KEYS, typed_with_altgr
        table = []
        for it in PLAYER_KEYS:
            if it is None:
                continue
            _, action, keys = it
            acc = wx.AcceleratorEntry()
            if acc.FromString(keys):
                wid = wx.NewIdRef()
                self.Bind(wx.EVT_MENU, lambda e, a=action, k=keys: typed_with_altgr(k) or self.main.player_do(a),
                          id=wid)
                table.append((acc.GetFlags(), acc.GetKeyCode(), wid))
        if table:
            self.SetAcceleratorTable(wx.AcceleratorTable(table))

    # ------------------------------------------------------------------ the queue

    def set_queue(self, items: list[dict], start: int = 0):
        self.save_position()
        self._clear_sleep()  # a timer set for the last listen doesn't carry over to a new one
        self.queue = items
        self._fill_queue()
        self.play_index(start)

    def _fill_queue(self):
        rows = []
        for i, it in enumerate(self.queue):
            state = ("Playing" if i == self.index else "Next" if i == self.index + 1 else
                     "Played" if i < self.index else "Later")
            when = words.uploaded(it)
            name = it.get("title") or (os.path.basename(it["path"]) if it.get("path") else
                                       words.short_link(it.get("url") or ""))  # never a whole address or path
            rows.append("%s: %s%s" % (state, name,
                                      ", " + when if when else ""))
        self.qlist.Set(rows)
        if 0 <= self.index < len(rows):
            self.qlist.SetSelection(self.index)

    def go(self, delta: int):
        if not self.queue:
            return
        k = self.index + delta
        if 0 <= k < len(self.queue):
            self.play_index(k)
        else:
            self.say("That's the %s item." % ("first" if delta < 0 else "last"))

    def play_index(self, k: int):
        if not (0 <= k < len(self.queue)):
            return
        self.save_position()
        self.media.Stop()
        self._end_ad(resume=False)
        self.ad_cues, self.ad_next = [], 0
        self.index = k
        self.item = self.queue[k]
        self._gen += 1
        self._resolving = False
        self.ad_free_from = 0.0
        self.loaded = False
        self.load_started = 0.0  # the "didn't start" clock belongs to this item, not the last one
        self.length = 0.0
        self.cues = []
        self.caption.SetLabel("")
        self.last_second = -1
        self.time.SetLabel("Loading")
        self.slider.SetValue(0)
        self.title.SetLabel(self.item.get("title") or "Loading")
        self.title.SetToolTip(self.item.get("title") or "")  # the whole title, where it's cut short
        self._byline()
        self.SetTitle("%s: Player" % (self.item.get("title") or "Loading"))
        self._fill_queue()
        self._update_buttons()
        if self.item.get("path"):
            self.cues = captions_for(self.item["path"])
            self._load(self.item["path"], local=True)
        else:
            self.status("Getting the stream for %s." % (self.item.get("title") or words.site_name(self.item["url"])))
            item = self.item
            self._resolving = True
            threading.Thread(target=self._resolve, args=(item, self._gen), daemon=True).start()

    def _resolve(self, item, gen):
        found = {}

        def on(ev):
            if ev.get("ev") == "stream":
                found.update(ev)
            elif ev.get("ev") == "log":
                found.setdefault("log", []).append(ev.get("text", ""))
        want = item.get("want") or "audio"
        run_task({"task": "stream", "url": item["url"], "want": want,
                  "cookies": item.get("cookies") or self.main.cfg.get("app_signin", ""),
                  "format": item.get("format", "")}, on,
                 timeout=120)
        wx.CallAfter(self._resolved, item, found, gen)

    def _resolved(self, item, found, gen):
        if not self or item is not self.item or gen != self._gen:
            return  # moved on meanwhile, or this item was started again
        self._resolving = False
        if not found.get("url") and not item.get("tried_list"):
            # Perhaps a playlist, an album or a podcast feed: list it and play its items in turn.
            item["tried_list"] = True
            item["first_log"] = found.get("log", [])  # the real reason, if it isn't a list either
            self.status("Looking for a list of items in that link.")
            self._resolving = True
            threading.Thread(target=self._list, args=(item, gen), daemon=True).start()
            return
        if not found.get("url"):
            reason = words.explain_failure("\n".join(found.get("log", [])), False, words.site_name(item["url"]),
                                           item.get("cookies") or self.main.cfg.get("app_signin", ""),
                                           for_download=False)
            if any("NOPLAYABLE" in x for x in found.get("log", [])):
                reason = ("This one can't be played without downloading it first. Download This (%s) saves it; "
                          "then Play in the downloads list plays it."
                          % ("Command-Return" if sys.platform == "darwin" else "Control-Enter"))
            self.fail(reason)
            return
        # No length from the site means a live stream (radio, a broadcast): the Mac's player
        # makes up a length for those (18 hours for an internet radio station).
        # A list's own title for an item ("Turning") beats the item page's ("gd1977-05-08d01t01").
        item.update(play_url=found["url"], title=item.get("title") or found.get("title"),
                    duration=found.get("duration") or item.get("duration") or 0,
                    uploader=found.get("uploader") or item.get("uploader"),
                    uploaded=found.get("uploaded") or item.get("uploaded"),
                    uploaded_ts=found.get("uploaded_ts") or item.get("uploaded_ts"),
                    approx=found.get("approx") if found.get("uploaded_ts") else item.get("approx"),
                    views=found.get("views") or item.get("views"),
                    live=bool(found.get("is_live") or not (found.get("duration") or item.get("duration"))),
                    got=found.get("want"))
        self.cues = [tuple(c) for c in found.get("cues") or []]
        self.title.SetLabel(item["title"] or "Playing")
        self.title.SetToolTip(item["title"] or "")
        self._byline()
        self.SetTitle("%s: Player" % item["title"])
        self._fill_queue()
        self._load(found["url"], local=False)

    def _list(self, item, gen):
        got = {}

        def on(ev):
            if ev.get("ev") == "playlist":
                got.update(ev)
        run_task({"task": "probe", "spec": {"url": item["url"], "dest": engine.TEMP, "kind": "best",
                                            "cookies": item.get("cookies") or self.main.cfg.get("app_signin", "")}}, on,
                 timeout=180)
        wx.CallAfter(self._listed, item, got, gen)

    def _listed(self, item, got, gen):
        if not self or item is not self.item or gen != self._gen:
            return
        self._resolving = False
        entries = got.get("entries") or []
        if not entries:
            self._resolved(item, {"log": item.get("first_log") or ["NOPLAYABLE"]}, gen)
            return
        new = [{"url": e["url"], "title": e.get("title") or "", "uploader": e.get("uploader") or "",
                "want": item.get("want", "audio"), "tried_list": True,
                **{k: e[k] for k in ("uploaded", "uploaded_ts", "approx", "views", "duration") if e.get(k)}}
               for e in entries]
        self.queue[self.index:self.index + 1] = new
        self.say("%s: %s. Playing them in turn." % (got.get("title") or "A list", words.n(len(new), "item")))
        self.play_index(self.index)

    def _load(self, target: str, local: bool):
        self.load_started = time.time()
        ok = self.media.Load(target) if local else self.media.LoadURI(target)
        if not ok:
            self.fail("This couldn't be opened for playing.")

    def fail(self, reason: str):
        self.loaded = False
        self.load_started = 0.0  # Space tries again after a failure
        self._resolving = False
        self.status(reason)
        self.say(reason)
        self._update_buttons()
        if self.cfg.get("app_play_next", True) and self.index + 1 < len(self.queue):
            failed_at = self.index

            def onward():
                # Only if nothing changed in the 2.5 s: closing the player, or picking another
                # item, must not have it start something by itself.
                if self and self.IsShown() and self.index == failed_at and not self.loaded:
                    self.go(+1)
            wx.CallLater(2500, onward)

    # ------------------------------------------------------------------ playing

    def on_loaded(self, _):
        if self.loaded or not self.item:
            return
        self.loaded = True
        self.load_started = 0.0  # started: the "didn't start" clock is done
        # The site's own length when there is one: AVFoundation reported YouTube streams at
        # twice their length (38 seconds for 19).
        self.length = float(self.item.get("duration") or 0) or max(0.0, self.media.Length() / 1000.0)
        live = self.item.get("live") or self.length <= 0
        self.slider.Enable(not live)
        self.slider.SetRange(0, max(1, int(self.length)))
        self.slider.SetLineSize(self.skip_len())
        self.slider.SetPageSize(60)
        is_video = self._is_video()
        self._show_video(is_video)
        self.media.SetVolume(self.out_volume())
        self._play()
        self._load_description()
        key = self._key()
        resume = self.positions.get(key) if self.cfg.get("app_resume", True) and not live else 0
        if resume:
            self.media.Seek(int(resume * 1000))
            self._ad_reseek(resume)  # descriptions from here, not from the start
            self.say("Picking up at %s." % words.duration(resume))
        elif not self.IsActive():
            self.say("Playing: %s." % (self.item.get("title") or ""))
        self.status("Playing%s." % (" live" if live else ""))
        self._show_time(resume or 0, force=True)
        self._update_buttons()

    # ------------------------------------------------------------------ audio description

    def _load_description(self):
        srt = describe.for_item(self.item.get("path"), self.item.get("url") or self.item.get("page"))
        self.ad_cues = []
        if srt:
            try:
                with open(srt, encoding="utf-8", errors="replace") as fh:
                    self.ad_cues = [c for c in words.caption_cues(fh.read()) if not c[2].startswith("[")]
            except OSError:
                pass
        self.ad_next = 0
        self._byline()

    def _byline(self):
        bits = ["By " + self.item["uploader"]] if self.item and self.item.get("uploader") else []
        when = words.uploaded(self.item) if self.item else ""
        if when:
            bits.append(when[0].upper() + when[1:])
        if self.ad_cues:
            bits.append("Audio description: " + dict(AD_MODES)[self.ad_mode])
        self.byline.SetLabel(". ".join(bits))

    def _ad_reseek(self, now: float):
        """A skip or a jump: stop any reading, carry on playing if a reading had paused it, and pick
        up the descriptions from the new place (not by stepping through every earlier one)."""
        was_paused_for_ad = self.ad_paused
        self._end_ad(resume=True)
        self.ad_free_from = 0.0
        self.ad_next = next((i for i, c in enumerate(self.ad_cues) if c[0] >= now - 0.2), len(self.ad_cues))
        if was_paused_for_ad:
            self._update_buttons()

    def _ad_tick(self, now: float):
        if self.ad_active:
            if not self.reader.speaking():
                self.ad_free_from = now
                self._end_ad(resume=True)
            return
        if self.ad_mode == "off" or not self.ad_cues or self.ad_next >= len(self.ad_cues) or not self.playing():
            return
        start, _, text = self.ad_cues[self.ad_next]
        if now + 0.15 < start:
            return
        self.ad_next += 1
        if now - max(start, self.ad_free_from) > 3:
            # Long past (a skip landed after it): don't read a stale description. One that came
            # due while another was being read counts from when that reading ended.
            return
        self.ad_active, self.ad_text = True, text
        self.caption.SetLabel("Description: " + text)
        self._fit_caption()
        if self.ad_mode == "pause":
            self.media.Pause()
            self.ad_paused = True
        else:
            self.fading = True
            self.media.SetVolume(self.out_volume() * 0.35)
        self.reader.speak(text)

    def _end_ad(self, resume: bool):
        if not self.ad_active:
            return
        self.ad_active = False
        self.reader.stop()
        if self.caption.GetLabel().startswith("Description: "):
            self.caption.SetLabel("")
        self.fading = False
        if self.loaded:
            self.media.SetVolume(self.out_volume())
        if self.ad_paused:
            self.ad_paused = False
            if resume and self.loaded:
                self._play()  # the item stays wherever it was paused

    def _sync_menu(self):
        """The Playback menu's marks follow the state, however it was changed (key, menu, Settings)."""
        if getattr(self, "captions_item", None) is not None:
            self.captions_item.Check(bool(self.captions_on))
        if getattr(self, "ad_items", None) and self.ad_mode in self.ad_items:
            self.ad_items[self.ad_mode].Check(True)

    def set_ad(self, mode: str):
        order = [m for m, _ in AD_MODES]
        self.ad_mode = order[(order.index(mode) - 1) % len(order)]
        self.cycle_ad()  # one way of changing it, so it saves, reloads and speaks the same

    def cycle_ad(self):
        order = [m for m, _ in AD_MODES]
        self.ad_mode = order[(order.index(self.ad_mode) + 1) % len(order)]
        self.cfg["app_ad_mode"] = self.ad_mode
        engine.save_settings(self.cfg)
        self._end_ad(resume=True)
        if not self.ad_cues and self.item:
            self._load_description()  # one may have been made since this started playing
            if self.ad_cues and self.loaded:
                self._ad_reseek(self.media.Tell() / 1000.0)
        self._byline()
        self._sync_menu()
        if not self.ad_cues:
            self.say("Audio description %s. This one has none yet: Find or Make Audio Description, "
                     "in the Playback menu." % dict(AD_MODES)[self.ad_mode])
        else:
            self.say("Audio description %s." % dict(AD_MODES)[self.ad_mode])

    def find_description(self):
        if not self.item:
            return
        url = self.item.get("url") or self.item.get("page")
        was = bool(self.loaded and self.playing())
        if was:
            self.toggle(quiet=True)  # nothing said over the window's first line
        code = self.main.describe_dialog(url, self.item.get("title") or "", self.item.get("path"))
        # Closed without choosing anything: carry on as it was.
        if was and code != wx.ID_OK and self and self.loaded and not self.playing():
            self.toggle()

    def description_ready(self, job):
        """A description just made for what's in the player: read it from here, without a restart."""
        it = self.item
        if not it:
            return
        mine = (job.url and job.url in (it.get("url"), it.get("page"))) or \
            (job.source_path and job.source_path == it.get("path"))
        if not mine:
            return
        self._load_description()
        if self.ad_cues and self.loaded:
            self._ad_reseek(self.media.Tell() / 1000.0)
            self.say("Audio description is ready. It reads from here.")

    def _is_video(self) -> bool:
        if self.item.get("path"):
            return os.path.splitext(self.item["path"])[1].lower() in (".mp4", ".m4v", ".mov", ".webm", ".mkv")
        return self.item.get("got") == "video"

    def _show_video(self, on: bool):
        self.media.Show(on)
        self.media_holder.SetProportion(1 if on else 0)
        # The picture can shrink (it keeps its shape when drawn); the controls under it can't.
        # At 640 by 360 the queue and the speed and volume row fell off the bottom.
        self.media.SetMinSize((320, 180) if on else (0, 0))
        self.panel.Layout()
        self._room_for_controls()

    def _room_for_controls(self):
        """Grow the window, up to the screen, so every control fits; never shrink it."""
        need = self.panel.GetBestSize()
        have = self.GetClientSize()
        idx = wx.Display.GetFromWindow(self)
        area = wx.Display(idx if idx != wx.NOT_FOUND else 0).GetClientArea()
        w = min(max(have.width, need.width), area.width - 20)
        h = min(max(have.height, need.height), area.height - 60)
        self.SetMinClientSize((min(need.width, area.width - 20), min(need.height, area.height - 60)))
        if (w, h) != (have.width, have.height):
            self.SetClientSize((w, h))

    def on_finished(self, _):
        self.positions.set(self._key(), 0, 0)
        self.positions.save()
        if self.sleep_end_of_item:
            self.sleep_end_of_item = False
            self.status("Sleep timer: stopped at the end of the item.")
            self._update_buttons()
            return
        if self.cfg.get("app_play_next", True) and self.index + 1 < len(self.queue):
            self.go(+1)
        else:
            # Said, not just shown: silence at the end of a queue sounds the same as a stall.
            self.say("That's everything in the queue." if len(self.queue) > 1 else "Finished.")
            from .system import cue
            cue("queue_end")
            self._update_buttons()

    def _play(self):
        """Start, at the chosen speed. On the Mac a rate starts the player by itself, and Play
        straight followed by a rate froze AVFoundation's clock for seconds 7 times in 12 at 1.5
        (the sound went on; the time, slider, captions and saved place stopped). Measured on a
        bare MediaCtrl, 2026-10-14; setting the rate alone never froze. Windows' player isn't
        started by a rate, and resets it on Play, so there it's Play, then the rate."""
        if sys.platform == "darwin" and self.speed != 1.0:
            self.media.SetPlaybackRate(self.speed)
        else:
            self.media.Play()
            if self.speed != 1.0:
                self.media.SetPlaybackRate(self.speed)

    def playing(self) -> bool:
        return self.media.GetState() == wx.media.MEDIASTATE_PLAYING

    def toggle(self, quiet: bool = False):
        if not self.loaded:
            if self._resolving or self.load_started:
                # Starting it again would race the load already under way and leave it silent.
                self.say("Still getting ready to play.")
            elif self.item and self.index >= 0:
                self.play_index(self.index)
            return
        if self.ad_active:
            # Space while a description is being read: stop reading and carry on.
            self._end_ad(resume=True)
            self._update_buttons()
            return
        if self.playing():
            self.media.Pause()
            self.save_position()
            if self.sleep_at:  # the timer counts listening, not the time spent paused
                self.sleep_left, self.sleep_at = max(10.0, self.sleep_at - time.time()), 0.0
                if self.fading:
                    self.fading = False
                    self.media.SetVolume(self.out_volume())
            if not quiet:
                self.say("Paused at %s." % words.clock_words(self.media.Tell() / 1000))
        else:
            self._play()
            if self.sleep_left:
                self.sleep_at, self.sleep_left = time.time() + self.sleep_left, 0.0
            self.say("Playing.")
        self._update_buttons()

    def skip(self, seconds: float):
        if self.loaded and self.item.get("live"):
            self.say("This is live, so there's nothing to skip through.")
            return
        if not self.loaded:
            return
        now = self.media.Tell() / 1000.0
        target = max(0.0, min(self.length - 1 if self.length else now + seconds, now + seconds))
        self.media.Seek(int(target * 1000))
        self.slider.SetValue(int(target))
        self._show_time(target, force=True)
        self._ad_reseek(target)

    def on_slider_release(self, _):
        self.dragging = False
        if self.loaded:
            self.media.Seek(int(self.slider.GetValue() * 1000))
            self._ad_reseek(self.slider.GetValue())

    def on_slider_moved(self, _):
        """The position slider moved by the keyboard or VoiceOver: go there."""
        if self.loaded and not self.item.get("live") and not self.dragging:
            target = self.slider.GetValue()
            if abs(target - self.media.Tell() / 1000.0) >= 1:
                self.media.Seek(int(target * 1000))
                self._show_time(target, force=True)
                self._ad_reseek(target)

    def skip_len(self) -> int:
        return int(self.cfg.get("app_skip", 10) or 10)

    def set_speed(self, value: float):
        self.speed = value
        if value in SPEEDS:
            self.speed_choice.SetSelection(SPEEDS.index(value))
        if self.loaded:
            # Said at once, handed to the media a beat after the last press: on the Mac a burst of
            # rate changes (] five times quickly) could freeze AVFoundation's clock for seconds,
            # stopping the time, the slider and the saved place. Measured 2026-10-14.
            if getattr(self, "_rate_later", None):
                self._rate_later.Stop()
            self._rate_later = wx.CallLater(150, self._apply_rate)
        self.cfg["app_speed"] = value
        engine.save_settings(self.cfg)
        self.say("Speed: %s." % speed_words(value))

    def _apply_rate(self):
        # Only while playing: on the Mac, setting a rate starts a paused player, so changing the
        # speed while paused used to start it silently and Space then paused it. Play sets it.
        if self and self.loaded and self.playing():
            self.media.SetPlaybackRate(self.speed)

    def step_speed(self, d: int):
        k = SPEEDS.index(self.speed) if self.speed in SPEEDS else NORMAL
        to = max(0, min(len(SPEEDS) - 1, k + d))
        if to == k and self.speed in SPEEDS:  # at the end: say so, rather than the same speed again
            self.say("%s, %s." % ("Slowest" if d < 0 else "Fastest", speed_words(self.speed).lower()))
            return
        self.set_speed(SPEEDS[to])

    def out_volume(self) -> float:
        return 0.0 if self.muted else self.base_volume

    def toggle_mute(self):
        self.muted = not self.muted
        if self.loaded and not self.fading:
            self.media.SetVolume(self.out_volume())
        self.say("Muted." if self.muted else "Sound on, volume %d." % int(self.base_volume * 100))

    def say_levels(self):
        sleep = ""
        if self.sleep_end_of_item:
            sleep = " Sleep timer: stops at the end of this item."
        elif self.sleep_at:
            sleep = " Sleep timer: %s left." % words.duration(max(0, self.sleep_at - time.time()))
        elif self.sleep_left:
            sleep = " Sleep timer: %s of listening left." % words.duration(self.sleep_left)
        self.say("Speed %s. Volume %d%s.%s" % (speed_words(self.speed).lower(), int(self.base_volume * 100),
                                               ", muted" if self.muted else "", sleep))

    def volume_step(self, sign: int, small: bool = False):
        step = 0.02 if small else 0.1
        self.set_volume(max(0.0, min(1.0, self.base_volume + sign * step)))

    def set_volume(self, v: float, say=True):
        self.muted = False  # changing the volume means you want to hear it
        self.base_volume = round(v, 2)
        self.volume.SetValue(int(self.base_volume * 100))
        mac_value_description(self.volume, "%d percent" % int(self.base_volume * 100))
        if self.loaded and not self.fading:
            self.media.SetVolume(self.out_volume())
        self.cfg["app_volume"] = self.base_volume
        engine.save_settings(self.cfg)
        if say:
            self.say("Volume %d." % int(self.base_volume * 100))

    def say_time(self):
        if not self.loaded:
            self.say("Nothing is playing.")
            return
        now = self.media.Tell() / 1000.0
        if self.item.get("live") or not self.length:
            self.say("Live, %s in." % words.duration(now))
            return
        self.say("%s of %s. %s left." % (words.duration(now) or "0 seconds", words.duration(self.length),
                                          words.duration(max(0, self.length - now)).capitalize()))


    def settings_changed(self) -> None:
        """Settings was saved while the player exists (it is never destroyed, only hidden):
        take the new captions, description mode and voice now, not at the next launch."""
        self.captions_on = bool(self.cfg.get("app_captions", True))
        if not self.captions_on and hasattr(self, "caption"):
            self.caption.SetLabel("")
        mode = self.cfg.get("app_ad_mode", "pause")
        if mode != self.ad_mode:
            self._end_ad(resume=True)  # a description mid-read must not leave the video paused or quiet
            self.ad_mode = mode
        self.reader.voice = self.cfg.get("app_ad_voice", "system")
        self._byline()
        self._sync_menu()

    def toggle_captions(self):
        self.captions_on = not self.captions_on
        self.cfg["app_captions"] = self.captions_on
        engine.save_settings(self.cfg)
        if not self.captions_on:
            self.caption.SetLabel("")
        self._sync_menu()
        self.say("Captions %s%s." % ("on" if self.captions_on else "off",
                                     "" if self.cues or not self.captions_on else ", but this one has none"))

    def _clear_sleep(self):
        self.sleep_at = self.sleep_left = 0.0
        self.sleep_end_of_item = False

    def set_sleep(self, minutes: int):
        if minutes == -1 and self.item and (self.item.get("live") or self.length <= 0):
            self.say("Live radio has no end to stop at. Choose a time instead.")
            return
        self.sleep_left = 0.0
        self.sleep_end_of_item = minutes == -1
        self.sleep_at = time.time() + minutes * 60 if minutes > 0 else 0.0
        if minutes == 0:
            self.say("Sleep timer off.")
        elif minutes == -1:
            self.say("Stopping at the end of this item.")
        elif not self.playing():
            # Set while paused: it counts listening, so it starts when you press Play.
            self.sleep_at, self.sleep_left = 0.0, minutes * 60.0
            self.say("Stopping after %s of listening." % words.duration(minutes * 60))
        else:
            self.say("Stopping in %s, at %s." % (words.duration(minutes * 60), words.clock_time(self.sleep_at)))

    # ------------------------------------------------------------------ every quarter second

    def on_tick(self, _):
        if self.item and not self.loaded and self.load_started and time.time() - self.load_started > 1 and \
                self.media.Length() > 0:
            # Ready without saying so: AVFoundation sometimes never sends the "loaded" event for a
            # stream (seen intermittently with YouTube audio), though it knows the length.
            self.on_loaded(None)
        waited = time.time() - self.load_started if self.item and not self.loaded and self.load_started else 0
        if waited > 8 and not self.item.get("told_slow"):
            # A busy sound system can take 20 seconds to open anything (seen with coreaudiod
            # struggling); say so rather than leave silence that sounds broken.
            self.item["told_slow"] = True
            self.say("Still getting ready to play.")
        if waited > 30 and not self.item.get("path") and not self.item.get("retried"):
            # Really stalled: fetch a fresh link and try once more. Not sooner: restarting a load
            # that was merely slow made it slower.
            self.item["retried"] = True
            self.status("Still waiting for the stream; trying a fresh link.")
            self.play_index(self.index)
            return
        if self.item and not self.loaded and self.load_started and time.time() - self.load_started > 60:
            self.load_started = 0
            if self.item.get("path"):  # Windows' player can't open some files (.opus, .webm, .mkv)
                self.fail("This file can't be played here. Show the File, then open it in another app.")
            else:
                self.fail("That stream didn't start. It may only play after downloading.")
        if not self.loaded or not self.IsShown():
            return
        now = self.media.Tell() / 1000.0
        if not self.dragging and not self.item.get("live"):
            self.slider.SetValue(int(now))
        self._show_time(now)
        self._ad_tick(now)
        if self.captions_on and self.cues and not self.ad_active:
            line = words.cue_at(self.cues, now)
            if line != self.caption.GetLabel():
                self.caption.SetLabel(line)
                self._fit_caption()
        if self.sleep_at and time.time() >= self.sleep_at - 10 and self.playing():
            left = self.sleep_at - time.time()
            self.fading = True
            self.media.SetVolume(max(0.0, self.out_volume() * left / 10))
            if left <= 0:
                self.media.Pause()
                self.media.SetVolume(self.out_volume())
                self.sleep_at, self.fading = 0.0, False
                self.save_position()
                self.status("Paused by the sleep timer. Sleep well.")  # shown, never spoken
                self._update_buttons()
        if time.time() - self.last_saved > 10:
            self.save_position()

    def _show_time(self, now: float, force=False):
        sec = int(now)
        if sec == self.last_second and not force:
            return
        self.last_second = sec
        if self.item.get("live") or not self.length:
            self.time.SetLabel("Live %s" % words.clock_words(now))
            mac_value_description(self.slider, "Live")
        else:
            self.time.SetLabel("%s of %s" % (words.clock_words(now), words.clock_words(self.length)))
            mac_value_description(self.slider, "%s of %s" % (words.duration(now) or "0 seconds",
                                                             words.duration(self.length)))
        self.panel.Layout()

    # ------------------------------------------------------------------ the rest

    def _key(self) -> str:
        if not self.item:
            return ""
        return self.item.get("path") or self.item.get("url") or ""

    def save_position(self):
        if self.loaded and self.item and not self.item.get("live") and self.cfg.get("app_resume", True):
            self.positions.set(self._key(), self.media.Tell() / 1000.0, self.length)
            self.positions.save()
        self.last_saved = time.time()

    def queue_menu(self):
        from . import menus
        k = self.qlist.GetSelection()
        if k == wx.NOT_FOUND or k >= len(self.queue):
            return []
        it = self.queue[k]
        url = it.get("url") or it.get("page") or ""
        here = k == self.index
        return [
            menus.item("Play or Pause" if here else "Play This One", self.toggle if here else
                       (lambda: self.play_index(k)), True, "Space" if here else ""),
            menus.item("Download This One", lambda: self._download(it),
                       url.startswith("http") and not it.get("path")),
            menus.item("Show the File", lambda: reveal([it["path"]]), bool(it.get("path"))),
            menus.SEP,
            menus.item("Open the Web Page", lambda: self.main.open_page(url), url.startswith("http")),
            menus.item("Copy Link", lambda: self.main.copy(url, "Link copied."), bool(url)),
            menus.item("Copy Title", lambda: self.main.copy(it.get("title") or url, "Title copied.")),
            menus.SEP,
            menus.item("Remove from the Queue", lambda: self.remove_from_queue(k), not here),
        ]

    def remove_from_queue(self, k: int):
        if k == self.index or not 0 <= k < len(self.queue):
            return
        gone = self.queue.pop(k)
        if k < self.index:
            self.index -= 1
        self._fill_queue()
        self._update_buttons()  # removing the last one leaves nothing for Next
        self.say("Removed %s from the queue." % (gone.get("title") or "it"))

    def download_this(self):
        if not self.item:
            return
        url = self.item.get("url")
        if not url or self.item.get("path"):
            self.say("This is already a downloaded file.")
            return
        self._download(self.item)

    def _download(self, it):
        """A described track keeps its track: plain add_links would fetch the version without it."""
        url = it.get("url") or it.get("page") or ""
        if it.get("format"):
            title = (it.get("title") or "").replace(" (described)", "")
            self.main.download_track(url, it["format"], title)
        else:
            self.main.add_links([url], "player")

    def show_file(self):
        if self.item and self.item.get("path"):
            reveal([self.item["path"]])
        else:
            self.say("This is playing from the site; nothing's saved yet. Download This keeps a copy.")

    def _update_buttons(self):
        self.play_btn.SetLabel("Pause" if self.loaded and self.playing() else "Play")
        self.prev_btn.Enable(self.index > 0)
        # Dimmed only for live: between items they stay, so focus on them isn't thrown elsewhere.
        can_skip = not (self.item and self.item.get("live"))
        self.back_btn.Enable(can_skip)
        self.fwd_btn.Enable(can_skip)
        self.next_btn.Enable(self.index + 1 < len(self.queue))
        file = bool(self.item and self.item.get("path"))
        self.show_btn.Enable(file)
        self.download_btn.Enable(bool(self.item) and not file)
        self.panel.Layout()

    def on_queue_key(self, event):
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.play_index(self.qlist.GetSelection())
        else:
            event.Skip()

    def on_key(self, event):
        """Plain keys for playing: Space, arrows (Left and Right skip, Up and Down the volume), Page Up
        and Page Down (the item), T, C, speed. Not while typing or in the queue."""
        focus = self.FindFocus()
        for native in (self.slider, self.volume):  # wx doesn't see a focused slider; the Mac does
            if mac_has_focus(native):
                focus = native
        key = event.GetKeyCode()
        if key == wx.WXK_TAB and not event.ControlDown():
            # wx's own Tab stopped dead at the Speed menu on the Mac (it couldn't move onto the
            # volume slider), trapping the keyboard. So the player keeps its own order.
            self._tab(-1 if event.ShiftDown() else 1, focus)
            return
        if isinstance(focus, wx.TextCtrl) or (focus is self.qlist and key in (
                wx.WXK_UP, wx.WXK_DOWN, wx.WXK_PAGEUP, wx.WXK_PAGEDOWN, wx.WXK_HOME, wx.WXK_END,
                wx.WXK_RETURN)):
            event.Skip()
            return
        mods = event.GetModifiers()
        speed = speed_key(event)
        if speed:
            {"slower": lambda: self.step_speed(-1), "faster": lambda: self.step_speed(+1),
             "normal": lambda: self.set_speed(1.0)}[speed]()
        elif key == wx.WXK_SPACE and not isinstance(focus, (wx.Button, wx.Choice, wx.CheckBox)) and mods == 0:
            self.toggle()
        elif key in (wx.WXK_LEFT, wx.WXK_RIGHT) and focus is not self.volume:
            # On the position slider too: steps of the skip length, not the slider's own.
            sign = -1 if key == wx.WXK_LEFT else 1
            if mods == wx.MOD_SHIFT:
                self.skip(sign * 60)
            elif mods == 0:
                self.skip(sign * self.skip_len())
            else:
                event.Skip()
        elif key in (wx.WXK_PAGEUP, wx.WXK_PAGEDOWN) and mods == 0:
            self.go(-1 if key == wx.WXK_PAGEUP else 1)
        elif key in (wx.WXK_UP, wx.WXK_DOWN) and focus is not self.volume and not isinstance(focus, wx.Choice):
            # The volume slider and the Speed popup keep their own Up and Down.
            sign = 1 if key == wx.WXK_UP else -1
            if mods in (0, wx.MOD_SHIFT):
                self.volume_step(sign, small=mods == wx.MOD_SHIFT)
            else:
                event.Skip()
        elif mods == 0 and key in (ord("T"), ord("t")):
            self.say_time()
        elif mods == 0 and key in (ord("M"), ord("m"), ord("K"), ord("k")):
            self.toggle_mute()
        elif mods == 0 and key in (ord("V"), ord("v")):
            self.say_levels()
        elif mods == 0 and key in (ord("C"), ord("c")):
            self.toggle_captions()
        elif mods == 0 and key in (ord("D"), ord("d")):
            self.cycle_ad()
        elif key == wx.WXK_ESCAPE:
            self.Close()
        else:
            event.Skip()

    def _tab(self, step: int, focus):
        for native in (self.slider, self.volume):
            if mac_has_focus(native):
                focus = native
        order = [c for c in (self.slider, self.prev_btn, self.back_btn, self.play_btn, self.fwd_btn,
                             self.next_btn, self.speed_choice, self.volume, self.download_btn, self.show_btn,
                             self.qlist) if c.IsShown() and c.IsEnabled()]
        if not order:
            return
        k = order.index(focus) if focus in order else (-1 if step > 0 else 0)
        for n in range(1, len(order) + 1):
            target = order[(k + step * n) % len(order)]
            if target in (self.slider, self.volume):
                if mac_focus(target):
                    return
            else:
                target.SetFocus()
                if self.FindFocus() is target:
                    return

    def say(self, text: str):
        self.status(text)
        announce(text)

    def status(self, text: str):
        self.SetStatusText(text)

    def on_close(self, event):
        """Closing hides the player; it's never destroyed while the app runs.

        wxWidgets' Mac media backend can crash when AVFoundation sends a late "paused" notice to
        a media control that has been destroyed (use after free, found by closing and reopening
        the player). Keeping one player alive, and stopping it well before the app quits
        (shutdown()), avoids it."""
        self.save_position()
        geometry.save(self, self.main.ui, "player")
        self._end_ad(resume=False)
        self.media.Stop()
        self.loaded = False
        self.load_started = 0.0
        self.item = None
        self.queue, self.index = [], -1  # closed is closed: nothing left to start up hidden
        self._clear_sleep()
        self.Hide()
        if event.CanVeto():
            event.Veto()
        # Back to Search if it's open (a preview started there), else the downloads window.
        back = getattr(self, "came_from", None)
        if back:  # back to the control it was opened from, in whichever window that was
            top = wx.GetTopLevelParent(back)
            top.Raise()
            back.SetFocus()
        else:
            (getattr(self.main, "search_win", None) or self.main).Raise()

    def _fit_caption(self):
        """Grow the caption to however many lines it wrapped to, so a long description or a
        large text size is never cut off at the bottom."""
        self.caption.Wrap(max(200, self.panel.GetClientSize().width - 40))
        lines = max(2, self.caption.GetLabel().count("\n") + 1)
        h = self.caption.GetCharHeight() * lines + 8
        if self.caption.GetMinSize().height != h:
            self.caption.SetMinSize((-1, max(60, h)))
            self.panel.Layout()

    def to_main(self):
        self.main.on_to_main()

    def shutdown(self):
        """Before the app quits: stop, then let AVFoundation's last notices arrive while the
        control still exists."""
        self.save_position()
        self.timer.Stop()
        self._end_ad(resume=False)
        try:
            self.media.Stop()
            end = time.time() + 0.5
            while time.time() < end:
                wx.SafeYield(None, True)
                time.sleep(0.02)
        except Exception:  # noqa: BLE001
            pass
