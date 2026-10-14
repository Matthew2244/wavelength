"""View, Bigger Text for every window, not only the main one (low vision).

The main window keeps the chosen size in `current`. Every other window calls apply() when it
opens, and the main window calls it again for windows already open when the size changes.
Text, fields and lists grow. Popup menus, buttons and checkboxes keep the system size: a bigger
font inside a fixed-height Mac control is clipped, and a popup menu drew blank at 22 points.
Controls with a size of their own (the player's title, captions and clock) grow in proportion.
"""
from __future__ import annotations

import sys

import wx

# On Windows buttons, checkboxes and popups grow too; on the Mac a bigger font inside those
# fixed-height controls is clipped, and a popup menu drew blank at 22 points.
_GROW = (wx.StaticText, wx.TextCtrl, wx.ListBox, wx.CheckListBox) + (
    (wx.Button, wx.CheckBox, wx.RadioButton, wx.Choice) if sys.platform == "win32" else ())

current = 0   # chosen point size; 0 until the main window sets it
default = 0   # the system's size, for proportion


def _walk(win):
    for c in win.GetChildren():
        yield c
        if not isinstance(c, wx.TopLevelWindow):
            yield from _walk(c)


def apply(win) -> None:
    if not current or not default or not win:
        return
    for c in _walk(win):
        if not isinstance(c, _GROW):
            continue
        f = c.GetFont()
        base = getattr(c, "_base_pt", None)
        if base is None:
            base = c._base_pt = f.GetPointSize()
        f.SetPointSize(max(8, round(base * current / float(default))))
        c.SetFont(f)
        if isinstance(c, wx.StaticText):
            c.InvalidateBestSize()
    win.Layout()
    if hasattr(win, "_room_for_controls"):
        win._room_for_controls()  # the player grows to fit bigger text instead of cutting it off
    status = win.GetStatusBar() if isinstance(win, wx.Frame) else None
    if status:
        f = status.GetFont()
        base = getattr(status, "_base_pt", None) or f.GetPointSize()
        status._base_pt = base
        f.SetPointSize(max(8, round(base * current / float(default))))
        status.SetFont(f)
        status.SetMinHeight(int(f.GetPixelSize().height * 1.6) if f.GetPixelSize().height else 20)
