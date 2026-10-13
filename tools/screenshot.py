"""Draw the window into a PNG: python tools/screenshot.py OUT.png [TEXT_POINTS]

Fills the list with sample downloads in every state (no network), then has the
window draw itself (NSView cacheDisplayInRect). No screen capture, so no
screen-recording prompt. The window is shown transparent and off-screen without
activating, because macOS paints nothing in a window that was never shown.
"""
import ctypes
import ctypes.util
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["MEDIA_DOWNLOAD_TEST_DIR"] = tempfile.mkdtemp()

import wx  # noqa: E402
from media_download import gui, words  # noqa: E402
from media_download.jobs import Job  # noqa: E402

out = sys.argv[1]
pts = int(sys.argv[2]) if len(sys.argv) > 2 else 0
gui.announce = lambda t: None
gui.MainFrame.startup_checks = lambda self: None
app = wx.App(False)
f = gui.MainFrame()
f.SetSize((900, 780))
f.mgr.pump = lambda: None
dest = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs/Media Downloads")
samples = [
    ("done", "Herbie Hancock - Cantaloupe Island (Live)", dict(bytes_done=9_400_000, files=["/x/a.m4a"])),
    ("done", "Jimmy Smith - The Sermon", dict(bytes_done=31_200_000, files=["/x/b.opus"])),
    ("downloading", "Stevie Wonder - Live at Montreux 2009, full concert",
     dict(percent=45, eta=130, bytes_done=410_000_000, bytes_total=911_000_000, speed=6_100_000, kind="video",
          max_height=1080, part=1, part_count=2)),
    ("converting", "Thelonious Monk - 'Round Midnight", dict(stage="Adding cover art")),
    ("downloading", "Booker T. & the M.G.'s - Green Onions", dict(percent=12, eta=40, bytes_done=1_000_000,
                                                                  bytes_total=8_300_000)),
    ("waiting", "Oscar Peterson - C Jam Blues", {}),
    ("failed", "A members-only rehearsal stream", dict(reason="That one is for members only.")),
]
for state, title, extra in samples:
    j = Job(url="https://www.youtube.com/watch?v=%s" % (abs(hash(title)) % 10**11), dest=dest)
    j.title = title
    j.length = 412
    j.uploader = "Sample Channel"
    for k, v in extra.items():
        setattr(j, k, v)
    j.state = state
    f.mgr.jobs.append(j)
f.structure_changed = True
f.refresh()
f.list.SetSelection(2)
f.show_details()
f.link.SetValue("https://soundcloud.com/some-artist/a-new-track")
if pts:
    f.text_pt = pts
    f._apply_text_size()
f.SetTransparent(0)
f.SetPosition((-3000, -3000))
f.ShowWithoutActivating()
f.Layout()
f.panel.Layout()
for _ in range(20):
    wx.SafeYield()
    time.sleep(0.05)
f._update_title()
import snap  # noqa: E402
ok, w, h = snap.snap(f, out)
class B: pass
bounds = B(); bounds.w, bounds.h = w, h
print("wrote", ok, bounds.w, bounds.h, "title:", f.GetTitle())
f.timer.Stop()
f.Destroy()
