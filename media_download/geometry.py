"""Windows come back where you left them, and never off screen."""
from __future__ import annotations

import wx


def restore(win: wx.TopLevelWindow, ui: wx.Config, key: str) -> None:
    raw = ui.Read(key, "")
    try:
        x, y, w, h = (int(v) for v in raw.split(","))
    except ValueError:
        return
    rect = wx.Rect(x, y, max(w, 400), max(h, 300))
    # A display that's been unplugged must not strand the window where nobody can reach it.
    if any(wx.Display(i).GetClientArea().Intersects(rect) for i in range(wx.Display.GetCount())):
        win.SetSize(rect)


def save(win: wx.TopLevelWindow, ui: wx.Config, key: str) -> None:
    if win.IsIconized() or win.IsFullScreen():
        return
    r = win.GetRect()
    ui.Write(key, "%d,%d,%d,%d" % (r.x, r.y, r.width, r.height))
    ui.Flush()
