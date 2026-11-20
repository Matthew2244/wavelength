"""What a control is for, said after the screen reader has read it (Matthew, 2026-11-20:
"after the button or control is focused, announcing what it is for... so hints or tips").

Focus is watched by polling, not by focus events: those don't travel up to the window from
every control on both systems, and a poll also catches focus moved by a shortcut or SetFocus.
When the focus settles on a control with a tip, its hint is said politely after HINT_MS, so
the control's own name, role and value come first. It's dropped if the focus moves on before
then, and a control isn't hinted again if the focus comes back within REPEAT_S.

On the Mac, VoiceOver already reads a control's tip itself, as its hint, so only the shortcut
is said there. On Windows NVDA, JAWS and Narrator don't read wx tips, so the tip's first
sentence is said, with the shortcut.
"""
import re
import sys
import time

import wx

POLL_MS = 150
HINT_MS = 900   # after the focus is seen: the control's name and role are read by then
REPEAT_S = 5.0  # back on the same control this soon: it was just heard

_MOD = r"(?:Command|Control|Option|Alt|Shift)"
_KEY = (r"(?:%s(?:-%s)*-(?:Page Up|Page Down|[A-Z][a-z]+ Arrow|[A-Za-z]+|[^\s,()])"
        r"|Escape|Return|Enter|Space|Tab|Delete|Backspace)" % (_MOD, _MOD))
_KEYS_ONLY = re.compile(r"^%s(?:(?:,? or |, )%s)*$" % (_KEY, _KEY))
_PAREN = re.compile(r"\s*\(([^()]*)\)")

_quiet: dict = {}  # id(ctrl) -> until: a control focused to be told something else just now


def keys_in(tip: str) -> list[str]:
    """The control's own shortcuts, from the tip's brackets: "(Command-R)", "(Escape, or
    Command-W)". A bracket after "use ..." names another control's key ("use Search (Command-F)")
    and is left out."""
    found = []
    for m in _PAREN.finditer(tip or ""):
        inside = m.group(1).strip()
        if not _KEYS_ONLY.match(inside):
            continue
        if re.search(r"\buse\s+\S+(\s+\S+)?\s*$", tip[:m.start()], re.I):
            continue
        found.extend(k for k in re.split(r",? or |, ", inside) if k)
    return found


def first_sentence(tip: str) -> str:
    """The tip's first sentence, without its key brackets (the keys are said on their own)."""
    text = _PAREN.sub(lambda m: "" if _KEYS_ONLY.match(m.group(1).strip()) else m.group(0), tip or "")
    text = " ".join(text.split())
    m = re.search(r"[.!?](\s|$)", text)
    return (text[:m.start() + 1] if m else text).strip()


def hint_for(tip: str, mac: bool | None = None) -> str:
    """What's said for a control with this tip. Mac: the shortcut only (VoiceOver reads the tip
    as its own hint). Windows: the first sentence, then the shortcut."""
    mac = sys.platform == "darwin" if mac is None else mac
    keys = keys_in(tip)
    shortcut = (" or ".join(keys) + ".") if keys else ""
    if mac:
        return shortcut
    return " ".join(t for t in (first_sentence(tip), shortcut) if t)


def quiet(ctrl, seconds: float = 3.0) -> None:
    """The next focus on ctrl brings no hint: something else is being said about it
    (dialogs.focus_then_say: "The Link field is empty... You're back in the Link field.")."""
    if ctrl is not None:
        _quiet[id(ctrl)] = time.monotonic() + seconds


def _tip_of(win):
    for w in (win, win.GetParent() if win else None):
        if w is None or w.IsTopLevel():
            return None, ""
        try:
            tip = w.GetToolTipText()
        except Exception:  # noqa: BLE001 - a control without tips
            tip = ""
        if tip:
            return w, tip
    return None, ""


class FocusHints:
    """Watches the focus app-wide and says each control's hint once it settles there."""

    def __init__(self, enabled, speak, owner=None, later=None):
        self.enabled = enabled          # callable: the setting, read each time
        self.speak = speak              # speak(text): polite announce
        self.later = later or (lambda ms, fn: wx.CallLater(ms, fn))
        self.focus = None
        self.pending = None
        self.said: dict = {}            # id(ctrl) -> when its hint was last said
        self.timer = None
        if owner is not None:
            self.timer = wx.Timer(owner)
            owner.Bind(wx.EVT_TIMER, lambda e: self.tick(), self.timer)
            self.timer.Start(POLL_MS)

            def gone(event):
                if event.GetEventObject() is owner:
                    self.stop()  # a timer firing into a destroyed window crashes
                event.Skip()
            owner.Bind(wx.EVT_WINDOW_DESTROY, gone)

    def stop(self):
        if self.timer is not None:
            self.timer.Stop()
        self._cancel()

    def _cancel(self):
        if self.pending is not None:
            try:
                self.pending.Stop()
            except Exception:  # noqa: BLE001 - already fired, or not a wx timer (tests)
                pass
            self.pending = None

    def tick(self, focus=None):
        """One look at the focus. `focus` is for tests; the app reads wx.Window.FindFocus()."""
        now = wx.Window.FindFocus() if focus is None else focus
        if now is self.focus:
            return
        self.focus = now
        self._cancel()  # the focus moved on: the last control's hint would be about the wrong thing
        if now is None or not self.enabled():
            return
        key = id(now)
        t = time.monotonic()
        if _quiet.pop(key, 0) > t:
            return
        if t - self.said.get(key, -REPEAT_S - 1) < REPEAT_S:
            return
        ctrl, tip = _tip_of(now)
        text = hint_for(tip) if tip else ""
        if not text:
            return

        def fire():
            self.pending = None
            if self.focus is not now or not now or not self.enabled():
                return
            self.said[key] = time.monotonic()
            self.speak(text)
        self.pending = self.later(HINT_MS, fire)
