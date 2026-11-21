"""Wavelength in the menu bar (Mac) or the notification area (Windows), for Settings, General,
"Start in the menu bar" (Matthew, 2026-11-20). Its menu: Show Wavelength, Download from the
Clipboard, Quit. The window stays closed at launch until Show Wavelength (or the Dock icon)."""
from __future__ import annotations

import os
import sys

import wx
import wx.adv

PLACE = "the menu bar" if sys.platform == "darwin" else "the notification area"


def _icon() -> wx.Icon:
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "assets", "icon.png")
    img = wx.Image(path) if os.path.exists(path) else wx.Image(16, 16)
    size = 18 if sys.platform == "darwin" else 16
    icon = wx.Icon()
    icon.CopyFromBitmap(wx.Bitmap(img.Scale(size, size, wx.IMAGE_QUALITY_HIGH)))
    return icon


class Tray(wx.adv.TaskBarIcon):
    SHOW, CLIP, QUIT = wx.NewIdRef(), wx.NewIdRef(), wx.NewIdRef()

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.SetIcon(_icon(), "Wavelength")  # the tooltip is its spoken name
        self.Bind(wx.EVT_MENU, lambda e: main.show_from_tray(), id=self.SHOW)
        self.Bind(wx.EVT_MENU, lambda e: main.download_from_tray(), id=self.CLIP)
        self.Bind(wx.EVT_MENU, lambda e: main.quit_from_tray(), id=self.QUIT)
        # Windows: a click on the icon opens the window; the menu is the right-click (or Shift-F10).
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, lambda e: main.show_from_tray())

    def CreatePopupMenu(self):
        menu = wx.Menu()
        menu.Append(self.SHOW, "Show Wavelength")
        menu.Append(self.CLIP, "Download from the Clipboard")
        menu.AppendSeparator()
        menu.Append(self.QUIT, "Quit Wavelength")
        return menu
