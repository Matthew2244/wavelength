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
# Each key means one thing on both systems: speed is Period and Comma everywhere, like > and <
# in the player; Normal is N and Mute is K everywhere. Where the two systems differ, it's
# because Windows can't have the Mac's key, never a key that does something else there.
_WIN = sys.platform == "win32"
# On Windows, Ctrl+Alt is AltGr on many keyboards (German [ ] \\ are AltGr+8, 9, ß) and some graphics
# drivers rotate the screen on Ctrl+Alt+arrows, so Windows gets keys neither touches. On the Mac,
# Command-Option-D shows and hides the Dock for the whole system, so volume stays on the arrows.


def player_keys(windows: bool) -> list:
    """The Player menu's keys for Windows or for the Mac (tests check both on either system)."""
    return [
        ("Play or Pause", "toggle", "Ctrl+Alt+P"),
        ("Previous Item", "prev", "Ctrl+Alt+PageUp"),
        ("Next Item", "next", "Ctrl+Alt+PageDown"),
        ("Back", "back", "Ctrl+Alt+Home" if windows else "Ctrl+Alt+Left"),
        ("Forward", "forward", "Ctrl+Alt+End" if windows else "Ctrl+Alt+Right"),
        None,
        ("Louder", "louder", "Ctrl+Alt+U" if windows else "Ctrl+Alt+Up"),
        ("Quieter", "quieter", "Ctrl+Alt+D" if windows else "Ctrl+Alt+Down"),
        ("Mute or Unmute", "mute", "Ctrl+Alt+K"),
        ("Faster", "faster", "Ctrl+Alt+."),
        ("Slower", "slower", "Ctrl+Alt+,"),
        ("Normal Speed", "normal", "Ctrl+Alt+N"),
        None,
        ("Say the Time", "time", "Ctrl+Alt+T"),
        ("Say the Speed and Volume", "levels", "Ctrl+Alt+V"),
    ]


PLAYER_KEYS = player_keys(_WIN)

from .keyboard import altgr_char, vk_of as _vk  # noqa: E402


def typed_with_altgr(keys: str) -> bool:
    """On Windows, AltGr is Control-Alt, so AltGr+N (ń on a Polish keyboard) or AltGr+V (@ in
    Hungarian) reaches a Control-Alt shortcut instead of the text box. When the right Alt key is
    down, the key types something on this layout and a text field has the focus, type it there
    and say so (True), so the shortcut doesn't fire. Pressing Control-Alt still runs it."""
    if not _WIN:
        return False
    vk = _vk(keys)
    if vk is None:
        return False
    try:
        import ctypes
        if not ctypes.windll.user32.GetKeyState(0xA5) & 0x8000:  # VK_RMENU: AltGr is the right Alt
            return False
        ch = altgr_char(vk)
    except Exception:  # noqa: BLE001 - if Windows can't say, the shortcut works as before
        return False
    focus = wx.Window.FindFocus()
    if not ch or not hasattr(focus, "WriteText") or not focus.IsEditable():
        return False
    if ch != "\u0301":
        focus.WriteText(ch)
    return True


def player_menu(owner: wx.Window, main) -> wx.Menu:
    """A Player menu for `owner`'s menu bar, driving main.player_do."""
    m = wx.Menu()
    for it in PLAYER_KEYS:
        if it is None:
            m.AppendSeparator()
            continue
        label, action, keys = it
        mi = m.Append(wx.ID_ANY, "%s\t%s" % (label, keys))
        owner.Bind(wx.EVT_MENU, lambda e, a=action, k=keys: typed_with_altgr(k) or main.player_do(a), mi)
    return m
