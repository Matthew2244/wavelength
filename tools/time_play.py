"""Time the first Play the honest way: python tools/time_play.py WORKDIR FILE cold SECONDS

Uses the app's real event loop (CallLater and MainLoop). Never time media with a loop of
wx.SafeYield(): it disables and repaints every window on each call, which starved AVFoundation
and made a 0.4 s first Play look like 7 to 27 seconds (2026-10-13).
"""
import os, sys, time
sys.path.insert(0, os.path.expanduser("~/ytdl-accessible"))
os.environ["MEDIA_DOWNLOAD_TEST_DIR"] = sys.argv[1]
import wx
from media_download import gui, player
gui.announce = player.announce = lambda t: None
warm = False
app = wx.App(False)
f = gui.MainFrame(); f.cfg["app_volume"] = 0.0; f.SetPosition((-3000, -3000)); f.ShowWithoutActivating()
f.startup_checks()
T = {}
def press():
    T["play"] = time.time()
    f.open_player([{"path": sys.argv[2], "title": "Me at the zoo"}]); f.player.SetPosition((-3000, -3000))
    poll()
def poll():
    if f.player.loaded:
        print("%-6s Play to playing: %.2f s" % ("warm" if warm else "cold", time.time() - T["play"]), flush=True)
        f.Close(force=True); return
    if time.time() - T["play"] > 40:
        print("timed out", flush=True); f.Close(force=True); return
    wx.CallLater(50, poll)
wx.CallLater(int(sys.argv[4]) * 1000, press)
app.MainLoop()
