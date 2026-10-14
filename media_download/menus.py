"""Right-click menus (context menus), the same everywhere in the app.

One opens on a right click, on Control-click on the Mac, with VoiceOver's VO-Shift-M, and with
Shift-F10 or the Menu key on Windows. Each lists only what makes sense for the row it was opened
on, names things the way the window's own menus do, and shows the shortcut where there is one,
so the menu also teaches the keys.
"""
from __future__ import annotations

import os
import sys
import webbrowser

import wx

CMD = "Command" if sys.platform == "darwin" else "Control"


def item(label: str, handler, enabled: bool = True, keys: str = ""):
    """One menu line. `keys` is shown beside it ("Ctrl+P"), for learning; it isn't bound here."""
    return (label, handler, enabled, keys)


SEP = None


def _fill(menu: wx.Menu, owner: wx.Window, items) -> None:
    for it in items:
        if it is SEP:
            if menu.GetMenuItemCount():
                menu.AppendSeparator()
            continue
        label, handler, enabled, keys = it
        if not enabled:
            continue  # left out, not dimmed: by ear, a list of "dimmed" lines is only in the way
        if isinstance(handler, list):  # a submenu
            sub = wx.Menu()
            _fill(sub, owner, handler)
            menu.AppendSubMenu(sub, label)
            continue
        mi = menu.Append(wx.ID_ANY, label + ("\t" + keys if keys else ""))
        mi.Enable(bool(enabled))
        owner.Bind(wx.EVT_MENU, lambda e, h=handler: wx.CallAfter(h), mi)


def attach(ctrl: wx.Window, build) -> None:
    """Give `ctrl` a context menu. build() returns the items for whatever is selected now, or
    nothing for no menu. A right click on a list row selects that row first, as people expect."""

    def show(pos=None):
        items = build() or []
        if not any(it is not SEP for it in items):
            return
        log = os.environ.get("MEDIA_DOWNLOAD_TEST_MENU_LOG")
        if log:  # tests: record what would open, and don't put a real menu on anybody's screen
            with open(log, "a") as fh:
                fh.write(" | ".join(labels(items)) + "\n")
            return
        menu = wx.Menu()
        _fill(menu, ctrl, items)
        if pos is None:
            ctrl.PopupMenu(menu)
        else:
            ctrl.PopupMenu(menu, pos)
        menu.Destroy()

    def on_context(event):
        pos = event.GetPosition()
        if pos == wx.DefaultPosition:  # from the keyboard: open at the selected row
            show(_row_point(ctrl))
            return
        local = ctrl.ScreenToClient(pos)
        if isinstance(ctrl, wx.ListBox):
            i = ctrl.HitTest(local)
            if i != wx.NOT_FOUND and i != ctrl.GetSelection():
                ctrl.SetSelection(i)
                ev = wx.CommandEvent(wx.wxEVT_LISTBOX, ctrl.GetId())
                ev.SetEventObject(ctrl)
                ev.SetInt(i)
                ctrl.GetEventHandler().ProcessEvent(ev)
        show(local)

    ctrl.Bind(wx.EVT_CONTEXT_MENU, on_context)
    ctrl._context_menu = lambda: show(_row_point(ctrl))  # for Command-K, and for tests
    from .system import mac_menu_action
    mac_menu_action(ctrl, ctrl._context_menu)  # VoiceOver's VO-Shift-M


def labels(items) -> list[str]:
    """What the menu will say, in order: enabled items only, as _fill shows them."""
    return [it[0] for it in items if it is not SEP and it[2]]


def _row_point(ctrl):
    if isinstance(ctrl, wx.ListBox) and ctrl.GetSelection() != wx.NOT_FOUND:
        return wx.Point(20, 10)
    return None


def open_web(url: str) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    webbrowser.open(url)
    return True


def copy_text(text: str) -> bool:
    if text and wx.TheClipboard.Open():
        try:
            wx.TheClipboard.SetData(wx.TextDataObject(text))
        finally:
            wx.TheClipboard.Close()
        return True
    return False


# The player, from any window: the same keys everywhere (Command-Option on the Mac,
# Control-Alt on Windows), so it can be paused or turned down without going to it.
_WIN = sys.platform == "win32"
# On Windows, Ctrl+Alt is AltGr on many keyboards (German [ ] \\ are AltGr+8, 9, ß) and some graphics
# drivers rotate the screen on Ctrl+Alt+arrows, so Windows gets keys neither touches.
PLAYER_KEYS = [
    ("Play or Pause", "toggle", "Ctrl+Alt+P"),
    ("Previous Item", "prev", "Ctrl+Alt+PageUp" if _WIN else "Ctrl+Alt+Left"),
    ("Next Item", "next", "Ctrl+Alt+PageDown" if _WIN else "Ctrl+Alt+Right"),
    ("Back", "back", "Ctrl+Alt+Home" if _WIN else "Ctrl+Alt+,"),
    ("Forward", "forward", "Ctrl+Alt+End" if _WIN else "Ctrl+Alt+."),
    None,
    ("Louder", "louder", "Ctrl+Alt+U" if _WIN else "Ctrl+Alt+Up"),
    ("Quieter", "quieter", "Ctrl+Alt+D" if _WIN else "Ctrl+Alt+Down"),
    ("Mute or Unmute", "mute", "Ctrl+Alt+K" if _WIN else "Ctrl+Alt+0"),
    ("Faster", "faster", "Ctrl+Alt+." if _WIN else "Ctrl+Alt+]"),
    ("Slower", "slower", "Ctrl+Alt+," if _WIN else "Ctrl+Alt+["),
    ("Normal Speed", "normal", "Ctrl+Alt+N" if _WIN else "Ctrl+Alt+\\"),
    None,
    ("Say the Time", "time", "Ctrl+Alt+T"),
    ("Say the Speed and Volume", "levels", "Ctrl+Alt+V"),
]


def player_menu(owner: wx.Window, main) -> wx.Menu:
    """A Player menu for `owner`'s menu bar, driving main.player_do."""
    m = wx.Menu()
    for it in PLAYER_KEYS:
        if it is None:
            m.AppendSeparator()
            continue
        label, action, keys = it
        mi = m.Append(wx.ID_ANY, "%s\t%s" % (label, keys))
        owner.Bind(wx.EVT_MENU, lambda e, a=action: main.player_do(a), mi)
    return m
