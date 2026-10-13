"""Drive the real window through real downloads, off-screen: python tools/drive.py WORKDIR

Not part of the test suite (it needs the internet). Adds links the way a person
would, answers the playlist question, waits, and prints every row, every
spoken message and the details of each row, so the wording can be read as a
listener would hear it.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
work = sys.argv[1]
os.environ["MEDIA_DOWNLOAD_TEST_DIR"] = os.path.join(work, "state")

import wx  # noqa: E402
from media_download import dialogs, engine, gui  # noqa: E402

said = []
gui.announce = lambda t: said.append(("spoken", t))
gui.play = lambda k: said.append(("sound", k))
gui.MainFrame.startup_checks = lambda self: None


class AnswerChoose:
    ALL, CHOOSE, ONE = dialogs.PlaylistQuestion.ALL, dialogs.PlaylistQuestion.CHOOSE, dialogs.PlaylistQuestion.ONE

    def __init__(self, parent, title, count, can_single, site):
        said.append(("dialog", "Playlist question: %s, %d items, single=%s" % (title, count, can_single)))

    def ShowModal(self):
        return self.CHOOSE

    def Destroy(self):
        pass


class TickTwo(dialogs.TickList):
    def ShowModal(self):
        self._set_all(False)
        self.list.Check(1)
        self.list.Check(3)
        self._count()
        said.append(("dialog", "Ticked items 2 and 4: " + self.count.GetLabel()))
        return wx.ID_OK


dialogs.PlaylistQuestion = AnswerChoose
dialogs.TickList = TickTwo
app = wx.App(False)
f = gui.MainFrame()
f.cfg["to"] = os.path.join(work, "out")
f.SetPosition((-3000, -3000))
f.SetTransparent(0)
f.ShowWithoutActivating()


def pump(seconds, until=None):
    end = time.time() + seconds
    while time.time() < end:
        wx.SafeYield()
        time.sleep(0.05)
        if until and until():
            return


links = sys.argv[2:] or [
    "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    "https://soundcloud.com/forss/flickermood",
    "https://archive.org/details/gd1977-05-08.shure57.stevenson.29303.flac16",
    "https://www.youtube.com/watch?v=xxxxxxxxxxx",
]
f.link.SetValue("\n".join(links))
f.on_download(None)
pump(5)
pump(400, until=lambda: not f.mgr.busy() and not f.pending_playlists)
pump(4)
print("TITLE:", f.GetTitle())
print("ROWS:")
for i in range(f.list.GetCount()):
    print("  ", f.list.GetString(i))
print("HEARD / SHOWN:")
for kind, t in said:
    print("  [%s] %s" % (kind, t))
f.list.SetSelection(0)
f.show_details()
print("DETAILS OF ROW 1:\n" + f.details.GetValue())
f.list.SetSelection(f.list.GetCount() - 1)
f.show_details()
print("DETAILS OF LAST ROW:\n" + f.details.GetValue())
f.timer.Stop()
f.mgr.shutdown()
f.Destroy()
