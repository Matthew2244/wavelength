"""View, Bigger Text for every window, not only the main one (low vision).

The main window keeps the chosen size in `current`. Every other window calls apply() when it
opens, and the main window calls it again for windows already open when the size changes.
Text, fields and lists grow, and so do buttons, popup menus, checkboxes and search fields: on
Windows by their wx font, on the Mac by grow_mac_controls (a wx font inside a fixed-height Mac
control is clipped, and a popup menu drew blank at 22 points; the native route avoids both).
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
    grow_mac_controls(win, current)
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


def _objc():
    import ctypes
    import ctypes.util
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]

    def send(obj, sel, *args, restype=ctypes.c_void_p, argtypes=()):
        f = objc.objc_msgSend
        f.restype = restype
        f.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
        return f(obj, objc.sel_registerName(sel.encode()), *args)
    return ctypes, objc, send


def grow_mac_controls(win, pt: int) -> None:
    """Bigger Text for the Mac's buttons, popup menus, checkboxes and search fields, which a
    wx font change leaves at the system size (or clips). Buttons switch to the bezel that grows
    with its text; the rest get a native font of the chosen size. Back at the system size they
    return to the standard look."""
    if sys.platform != "darwin" or not win:
        return
    try:
        ctypes, objc, send = _objc()
        nsfont = objc.objc_getClass(b"NSFont")
    except Exception:  # noqa: BLE001 - controls stay the system size, as before
        return
    for c in _walk(win):
        _grow_mac(c, pt, ctypes, send, nsfont)
    win.Layout()


def apply_controls(controls) -> None:
    """Bigger Text for controls made after their window applied it (the OK and Cancel row)."""
    if not current or not default:
        return
    for c in controls:
        if not c:
            continue
        if sys.platform == "darwin":
            try:
                ctypes, objc, send = _objc()
                _grow_mac(c, current, ctypes, send, objc.objc_getClass(b"NSFont"))
            except Exception:  # noqa: BLE001
                pass
        elif isinstance(c, _GROW):
            f = c.GetFont()
            base = getattr(c, "_base_pt", None) or f.GetPointSize()
            c._base_pt = base
            f.SetPointSize(max(8, round(base * current / float(default))))
            c.SetFont(f)
            c.InvalidateBestSize()


def _grow_mac(c, pt, ctypes, send, nsfont) -> None:
    big = bool(default) and pt > default + 1
    if not isinstance(c, (wx.Button, wx.CheckBox, wx.Choice, wx.SearchCtrl)) or isinstance(c, wx.BitmapButton):
        return
    if not big and not getattr(c, "_shown_pt", None):
        return  # at the system size and never grown: leave the control exactly as the system made it
    try:
        h = c.GetHandle()
        if not h:
            return
        size = float(pt if big else default)
        font = send(nsfont, "systemFontOfSize:", size, argtypes=(ctypes.c_double,))
        if isinstance(c, wx.Button):
            send(h, "setBezelStyle:", 2 if big else 1, restype=None, argtypes=(ctypes.c_long,))
        if isinstance(c, wx.Choice):
            send(h, "setControlSize:", 3 if big else 0, restype=None, argtypes=(ctypes.c_long,))
        send(h, "setFont:", font, restype=None, argtypes=(ctypes.c_void_p,))
        if isinstance(c, wx.SearchCtrl):
            cell = send(h, "cell")
            if cell:
                send(cell, "setFont:", font, restype=None, argtypes=(ctypes.c_void_p,))
        c._shown_pt = int(size)  # what measuring code must use: the wx font still says 13
        f = c.GetFont()
        f.SetPointSize(int(size))
        dc = wx.ClientDC(c)
        dc.SetFont(f)
        label = c.GetLabelText() if isinstance(c, (wx.Button, wx.CheckBox)) else max(
            [c.GetString(i) for i in range(c.GetCount())] or [""], key=len) if isinstance(c, wx.Choice) else "M" * 12
        w, th = dc.GetTextExtent(label or "M")
        if not big:
            c.SetMinSize((getattr(c, "_base_w", -1), -1) if isinstance(c, wx.SearchCtrl) else wx.DefaultSize)
            c.InvalidateBestSize()
            return
        if isinstance(c, wx.Button):
            c.SetMinSize((w + int(th * 1.6), int(th * 1.6)))
        elif isinstance(c, wx.CheckBox):
            c.SetMinSize((w + int(th * 2.2), int(th * 1.5)))
        elif isinstance(c, wx.Choice):
            c.SetMinSize((w + int(th * 3), int(th * 1.6)))
        else:
            base_w = getattr(c, "_base_w", None) or c.GetSize().width
            c._base_w = base_w
            c.SetMinSize((int(base_w * size / default), int(th * 1.6)))
    except Exception:  # noqa: BLE001 - one odd control keeps the system size
        return


def measuring_font(c) -> "wx.Font":
    """The font a control really draws with, for sizing it: on the Mac grow_mac_controls sets
    the native font and leaves the wx one at the system size."""
    f = c.GetFont()
    pt = getattr(c, "_shown_pt", None)
    if pt:
        f = wx.Font(f)
        f.SetPointSize(pt)
    return f
