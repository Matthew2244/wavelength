"""The player: downloaded files, or links played without downloading.

Built for listening first and looking second, and fine for both:
- Space plays and pauses; Left and Right skip (the length is a setting), Shift for a
  minute; Command-Left and Right change item; [ and ] change speed, without changing
  pitch; T says the time; C turns captions on and off. Every one is also in the
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

from . import engine, words
from .manager import run_task
from .system import announce, mac_accessibility_label, mac_value_description, open_path, reveal

SPEEDS = [0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0]
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
            if name.startswith(stem) and name.lower().endswith((".srt", ".vtt")):
                with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as fh:
                    return words.caption_cues(fh.read())
    except OSError:
        pass
    return []


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
        self.length = 0.0
        self.dragging = False
        self.last_second = -1
        self.positions = Positions()
        self.last_saved = 0.0
        self.sleep_at = 0.0
        self.sleep_end_of_item = False
        self.fading = False
        self.base_volume = float(self.cfg.get("app_volume", 1.0))
        self.speed = float(self.cfg.get("app_speed", 1.0))
        self.captions_on = bool(self.cfg.get("app_captions", True))

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
        self.slider.SetToolTip("Where it's playing. Arrow keys move by the skip length; Page Up and Down by a minute.")
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
        for b, tip in ((self.prev_btn, "The previous item (Command-Left)."),
                       (self.back_btn, "Back by the skip length (Left arrow; Shift-Left for a minute)."),
                       (self.play_btn, "Play or pause (Space)."),
                       (self.fwd_btn, "Forward by the skip length (Right arrow; Shift-Right for a minute)."),
                       (self.next_btn, "The next item (Command-Right).")):
            b.SetToolTip(tip.replace("Command", "Control") if sys.platform == "win32" else tip)
            row.Add(b, 0, wx.RIGHT, 6)
        s.Add(row, 0, wx.LEFT | wx.RIGHT, 12)

        row = wx.BoxSizer(wx.HORIZONTAL)
        lab = wx.StaticText(p, label="Speed:")
        self.speed_choice = wx.Choice(p, choices=[speed_words(v) for v in SPEEDS])
        self.speed_choice.SetSelection(SPEEDS.index(self.speed) if self.speed in SPEEDS else 3)
        mac_accessibility_label(self.speed_choice, "Speed")
        self.speed_choice.SetToolTip("Faster or slower without changing pitch ([ and ]).")
        vlab = wx.StaticText(p, label="Volume:")
        self.volume = wx.Slider(p, value=int(self.base_volume * 100), minValue=0, maxValue=100, size=(160, -1))
        mac_accessibility_label(self.volume, "Volume")
        mac_value_description(self.volume, "%d percent" % int(self.base_volume * 100))
        self.download_btn = wx.Button(p, label="Download This")
        self.download_btn.SetToolTip("Keep a copy of what's playing, in the main window's format.")
        self.show_btn = wx.Button(p, label="Show File")
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
        self.qlist.SetToolTip("Everything queued. Return plays the selected one.")
        s.Add(self.qlist, 0, wx.EXPAND | wx.ALL, 12)
        p.SetSizer(s)
        self.CreateStatusBar()
        self._menus()
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
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_tick, self.timer)
        self.timer.Start(250)
        self._update_buttons()

    # ------------------------------------------------------------------ menus

    def _menus(self):
        bar = wx.MenuBar()
        m = wx.Menu()

        def add(label, fn, wid=wx.ID_ANY):
            item = m.Append(wid, label)
            self.Bind(wx.EVT_MENU, lambda e: fn(), item)
            return item
        # Plain keys (Space, arrows, T, C, [ and ]) are handled by on_key and written into the
        # names so the menu teaches them; menus can't carry bare keys on every system.
        add("Play or Pause (Space)", self.toggle)
        add("Back (Left Arrow)", lambda: self.skip(-self.skip_len()))
        add("Forward (Right Arrow)", lambda: self.skip(self.skip_len()))
        add("Back a Minute (Shift-Left)", lambda: self.skip(-60))
        add("Forward a Minute (Shift-Right)", lambda: self.skip(60))
        m.AppendSeparator()
        add("Previous Item\tCtrl+Left", lambda: self.go(-1))
        add("Next Item\tCtrl+Right", lambda: self.go(+1))
        m.AppendSeparator()
        add("Slower ([)", lambda: self.step_speed(-1))
        add("Faster (])", lambda: self.step_speed(+1))
        add("Normal Speed (\\)", lambda: self.set_speed(1.0))
        add("Louder\tCtrl+Up", lambda: self.set_volume(min(1.0, self.base_volume + 0.1)))
        add("Quieter\tCtrl+Down", lambda: self.set_volume(max(0.0, self.base_volume - 0.1)))
        m.AppendSeparator()
        add("Say the Time (T)", self.say_time)
        add("Captions On or Off (C)", self.toggle_captions)
        sleep = wx.Menu()
        for minutes, label in SLEEP_CHOICES:
            item = sleep.Append(wx.ID_ANY, label)
            self.Bind(wx.EVT_MENU, lambda e, mm=minutes: self.set_sleep(mm), item)
        m.AppendSubMenu(sleep, "Sleep Timer")
        m.AppendSeparator()
        add("Download This\tCtrl+S", self.download_this)
        add("Show the File\tCtrl+R", self.show_file)
        add("Close Player\tCtrl+W", self.Close)
        bar.Append(m, "&Playback")
        self.SetMenuBar(bar)

    # ------------------------------------------------------------------ the queue

    def set_queue(self, items: list[dict], start: int = 0):
        self.save_position()
        self.queue = items
        self._fill_queue()
        self.play_index(start)

    def _fill_queue(self):
        rows = []
        for i, it in enumerate(self.queue):
            state = ("Playing" if i == self.index else "Next" if i == self.index + 1 else
                     "Played" if i < self.index else "Later")
            rows.append("%s: %s" % (state, it.get("title") or it.get("url") or it.get("path")))
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
        self.index = k
        self.item = self.queue[k]
        self.loaded = False
        self.length = 0.0
        self.cues = []
        self.caption.SetLabel("")
        self.last_second = -1
        self.time.SetLabel("Loading")
        self.slider.SetValue(0)
        self.title.SetLabel(self.item.get("title") or "Loading")
        self.byline.SetLabel(self.item.get("uploader") and "By " + self.item["uploader"] or "")
        self.SetTitle("%s: Player" % (self.item.get("title") or "Loading"))
        self._fill_queue()
        self._update_buttons()
        if self.item.get("path"):
            self.cues = captions_for(self.item["path"])
            self._load(self.item["path"], local=True)
        else:
            self.status("Getting the stream for %s." % (self.item.get("title") or words.site_name(self.item["url"])))
            item = self.item
            threading.Thread(target=self._resolve, args=(item,), daemon=True).start()

    def _resolve(self, item):
        found = {}

        def on(ev):
            if ev.get("ev") == "stream":
                found.update(ev)
            elif ev.get("ev") == "log":
                found.setdefault("log", []).append(ev.get("text", ""))
        want = item.get("want") or "audio"
        run_task({"task": "stream", "url": item["url"], "want": want, "cookies": item.get("cookies", "")}, on,
                 timeout=120)
        wx.CallAfter(self._resolved, item, found)

    def _resolved(self, item, found):
        if not self or item is not self.item:
            return  # moved on meanwhile
        if not found.get("url"):
            reason = words.explain_failure("\n".join(found.get("log", [])), False, words.site_name(item["url"]))
            if any("NOPLAYABLE" in x for x in found.get("log", [])):
                reason = "This one can't be played without downloading it first."
            self.fail(reason)
            return
        # No length from the site means a live stream (radio, a broadcast): the Mac's player
        # makes up a length for those (18 hours for an internet radio station).
        item.update(play_url=found["url"], title=found.get("title") or item.get("title"),
                    uploader=found.get("uploader") or item.get("uploader"),
                    live=bool(found.get("is_live") or not found.get("duration")), got=found.get("want"))
        self.cues = [tuple(c) for c in found.get("cues") or []]
        self.title.SetLabel(item["title"] or "Playing")
        self.byline.SetLabel("By " + item["uploader"] if item.get("uploader") else "")
        self.SetTitle("%s: Player" % item["title"])
        self._fill_queue()
        self._load(found["url"], local=False)

    def _load(self, target: str, local: bool):
        self.load_started = time.time()
        ok = self.media.Load(target) if local else self.media.LoadURI(target)
        if not ok:
            self.fail("This couldn't be opened for playing.")

    def fail(self, reason: str):
        self.loaded = False
        self.status(reason)
        self.say(reason)
        self._update_buttons()
        if self.cfg.get("app_play_next", True) and self.index + 1 < len(self.queue):
            wx.CallLater(2500, self.go, +1)

    # ------------------------------------------------------------------ playing

    def on_loaded(self, _):
        if self.loaded or not self.item:
            return
        self.loaded = True
        self.length = max(0.0, self.media.Length() / 1000.0)
        live = self.item.get("live") or self.length <= 0
        self.slider.Enable(not live)
        self.slider.SetRange(0, max(1, int(self.length)))
        self.slider.SetLineSize(self.skip_len())
        self.slider.SetPageSize(60)
        is_video = self._is_video()
        self._show_video(is_video)
        self.media.SetVolume(self.base_volume)
        self.media.Play()
        self.media.SetPlaybackRate(self.speed)
        key = self._key()
        resume = self.positions.get(key) if self.cfg.get("app_resume", True) and not live else 0
        if resume:
            self.media.Seek(int(resume * 1000))
            self.say("Picking up at %s." % words.duration(resume))
        elif not self.IsActive():
            self.say("Playing: %s." % (self.item.get("title") or ""))
        self.status("Playing%s." % (" live" if live else ""))
        self._show_time(resume or 0, force=True)
        self._update_buttons()

    def _is_video(self) -> bool:
        if self.item.get("path"):
            return os.path.splitext(self.item["path"])[1].lower() in (".mp4", ".m4v", ".mov", ".webm", ".mkv")
        return self.item.get("got") == "video"

    def _show_video(self, on: bool):
        self.media.Show(on)
        self.media_holder.SetProportion(1 if on else 0)
        self.media.SetMinSize((640, 360) if on else (0, 0))
        self.panel.Layout()

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
            self.status("Finished.")
            self._update_buttons()

    def playing(self) -> bool:
        return self.media.GetState() == wx.media.MEDIASTATE_PLAYING

    def toggle(self):
        if not self.loaded:
            if self.item and self.index >= 0:
                self.play_index(self.index)
            return
        if self.playing():
            self.media.Pause()
            self.save_position()
            self.say("Paused at %s." % words.clock_words(self.media.Tell() / 1000))
        else:
            self.media.Play()
            self.media.SetPlaybackRate(self.speed)  # some systems reset the rate on play
            self.say("Playing.")
        self._update_buttons()

    def skip(self, seconds: float):
        if not self.loaded or self.item.get("live"):
            return
        now = self.media.Tell() / 1000.0
        target = max(0.0, min(self.length - 1 if self.length else now + seconds, now + seconds))
        self.media.Seek(int(target * 1000))
        self.slider.SetValue(int(target))
        self._show_time(target, force=True)

    def on_slider_release(self, _):
        self.dragging = False
        if self.loaded:
            self.media.Seek(int(self.slider.GetValue() * 1000))

    def skip_len(self) -> int:
        return int(self.cfg.get("app_skip", 10) or 10)

    def set_speed(self, value: float):
        self.speed = value
        if value in SPEEDS:
            self.speed_choice.SetSelection(SPEEDS.index(value))
        if self.loaded:
            self.media.SetPlaybackRate(value)
        self.cfg["app_speed"] = value
        engine.save_settings(self.cfg)
        self.say("Speed: %s." % speed_words(value))

    def step_speed(self, d: int):
        k = SPEEDS.index(self.speed) if self.speed in SPEEDS else 3
        k = max(0, min(len(SPEEDS) - 1, k + d))
        self.set_speed(SPEEDS[k])

    def set_volume(self, v: float, say=True):
        self.base_volume = round(v, 2)
        self.volume.SetValue(int(self.base_volume * 100))
        mac_value_description(self.volume, "%d percent" % int(self.base_volume * 100))
        if self.loaded and not self.fading:
            self.media.SetVolume(self.base_volume)
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

    def toggle_captions(self):
        self.captions_on = not self.captions_on
        self.cfg["app_captions"] = self.captions_on
        engine.save_settings(self.cfg)
        if not self.captions_on:
            self.caption.SetLabel("")
        self.say("Captions %s%s." % ("on" if self.captions_on else "off",
                                     "" if self.cues or not self.captions_on else ", but this one has none"))

    def set_sleep(self, minutes: int):
        self.sleep_end_of_item = minutes == -1
        self.sleep_at = time.time() + minutes * 60 if minutes > 0 else 0.0
        if minutes == 0:
            self.say("Sleep timer off.")
        elif minutes == -1:
            self.say("Stopping at the end of this item.")
        else:
            self.say("Stopping in %s, at %s." % (words.duration(minutes * 60), words.clock_time(self.sleep_at)))

    # ------------------------------------------------------------------ every quarter second

    def on_tick(self, _):
        if self.item and not self.item.get("path") and not self.loaded and self.load_started and \
                time.time() - self.load_started > 25:
            self.load_started = 0
            self.fail("That stream didn't start. It may only play after downloading.")
        if not self.loaded:
            return
        now = self.media.Tell() / 1000.0
        if not self.dragging and not self.item.get("live"):
            self.slider.SetValue(int(now))
        self._show_time(now)
        if self.captions_on and self.cues:
            line = words.cue_at(self.cues, now)
            if line != self.caption.GetLabel():
                self.caption.SetLabel(line)
                self.caption.Wrap(max(200, self.panel.GetClientSize().width - 40))
        if self.sleep_at and time.time() >= self.sleep_at - 10 and self.playing():
            left = self.sleep_at - time.time()
            self.fading = True
            self.media.SetVolume(max(0.0, self.base_volume * left / 10))
            if left <= 0:
                self.media.Pause()
                self.media.SetVolume(self.base_volume)
                self.sleep_at, self.fading = 0.0, False
                self.save_position()
                self.status("Sleep timer: paused.")
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

    def download_this(self):
        if not self.item:
            return
        url = self.item.get("url") or self.item.get("page")
        if not url:
            self.say("This is already a downloaded file.")
            return
        self.main.add_links([url], "player")

    def show_file(self):
        if self.item and self.item.get("path"):
            reveal([self.item["path"]])
        else:
            self.say("This is playing from the site; nothing's saved yet. Download This keeps a copy.")

    def _update_buttons(self):
        self.play_btn.SetLabel("Pause" if self.loaded and self.playing() else "Play")
        self.prev_btn.Enable(self.index > 0)
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
        """Plain keys for playing: Space, arrows, T, C, [ and ]. Not while typing or in the queue."""
        focus = self.FindFocus()
        key = event.GetKeyCode()
        if isinstance(focus, wx.TextCtrl) or (focus is self.qlist and key in (wx.WXK_UP, wx.WXK_DOWN,
                                                                                wx.WXK_RETURN, wx.WXK_SPACE)):
            event.Skip()
            return
        mods = event.GetModifiers()
        if key == wx.WXK_SPACE and not isinstance(focus, wx.Button) and mods == 0:
            self.toggle()
        elif key in (wx.WXK_LEFT, wx.WXK_RIGHT) and focus is not self.slider and focus is not self.volume:
            sign = -1 if key == wx.WXK_LEFT else 1
            if mods == wx.MOD_SHIFT:
                self.skip(sign * 60)
            elif mods == 0:
                self.skip(sign * self.skip_len())
            else:
                event.Skip()
        elif mods == 0 and key in (ord("T"), ord("t")):
            self.say_time()
        elif mods == 0 and key in (ord("C"), ord("c")):
            self.toggle_captions()
        elif mods == 0 and key == ord("["):
            self.step_speed(-1)
        elif mods == 0 and key == ord("]"):
            self.step_speed(+1)
        elif mods == 0 and key == ord("\\"):
            self.set_speed(1.0)
        elif key == wx.WXK_ESCAPE:
            self.Close()
        else:
            event.Skip()

    def say(self, text: str):
        self.status(text)
        announce(text)

    def status(self, text: str):
        self.SetStatusText(text)

    def on_close(self, event):
        self.save_position()
        self.timer.Stop()
        self.media.Stop()
        self.main.player = None
        event.Skip()
