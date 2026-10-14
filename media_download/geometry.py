"""Windows come back where you left them, and never off screen."""
from __future__ import annotations

import wx


def restore(win: wx.TopLevelWindow, ui: wx.Config, key: str) -> bool:
    raw = ui.Read(key, "")
    try:
        x, y, w, h = (int(v) for v in raw.split(","))
    except ValueError:
        return False
    rect = wx.Rect(x, y, max(w, 400), max(h, 300))
    # A display that's been unplugged must not strand the window where nobody can reach it.
    for i in range(wx.Display.GetCount()):
        area = wx.Display(i).GetClientArea()
        if area.Intersects(rect):
            # ...and a window saved on a big screen must fit a small one (a laptop at 1366 by 768).
            rect.width, rect.height = min(rect.width, area.width), min(rect.height, area.height)
            rect.x = max(area.x, min(rect.x, area.x + area.width - rect.width))
            rect.y = max(area.y, min(rect.y, area.y + area.height - rect.height))
            win.SetSize(rect)
            return True
    return False


def fit_on_screen(win: wx.TopLevelWindow) -> None:
    """A first launch: no bigger than the screen it opens on."""
    idx = wx.Display.GetFromWindow(win)
    area = wx.Display(idx if idx != wx.NOT_FOUND else 0).GetClientArea()
    w, h = win.GetSize()
    win.SetSize((min(w, area.width - 20), min(h, area.height - 20)))


def save(win: wx.TopLevelWindow, ui: wx.Config, key: str) -> None:
    if win.IsIconized() or win.IsFullScreen():
        return
    r = win.GetRect()
    ui.Write(key, "%d,%d,%d,%d" % (r.x, r.y, r.width, r.height))
    ui.Flush()
