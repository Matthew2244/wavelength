"""Sign in inside Wavelength: a window with the site's own sign-in page, so nobody needs Full
Disk Access, keychain prompts or System Settings to use their accounts (Rocco, 2026-10-16:
"much more seamless, regardless of browser").

The page is the system's own web view: WKWebView on the Mac (the engine behind Safari, so
VoiceOver reads it as it reads Safari), WebView2 on Windows (Edge's, read by NVDA, JAWS and
Narrator). Nothing typed into it reaches Wavelength. What Wavelength keeps afterwards is what
any browser keeps: the site's sign-in cookies, in accounts.own_file(), readable only by you.

On the Mac the cookies come straight from WKHTTPCookieStore (document.cookie can't see the
HttpOnly ones a sign-in actually lives in). On Windows the window runs in its own process
(`--signin`), with its WebView2 folder inside Wavelength's; when it closes, the engine reads that
folder like any Chromium browser (worker task signin_save). Its own process because WebView2
keeps its cookie file locked for as long as the process that opened it is alive.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading

import wx
import wx.html2

from . import accounts, engine, textsize

# name, address, what to say about it
SERVICES = [
    ("YouTube", "https://accounts.google.com/ServiceLogin?service=youtube&passive=true&continue="
                "https%3A%2F%2Fwww.youtube.com%2Fsignin%3Faction_handle_signin%3Dtrue%26app%3Ddesktop%26next%3D%252F",
     "YouTube and YouTube Music share one sign-in, your Google account."),
    ("SoundCloud", "https://soundcloud.com/signin", "Your SoundCloud account."),
]
OTHER = "Another Site..."

# Google turns away sign-ins from pages that don't say which browser they are. This is the
# engine underneath (WebKit on the Mac, Edge on Windows), named the way that browser names itself.
MAC_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/18.5 Safari/605.1.15")


def available() -> bool:
    """Can this computer show a sign-in window? (A Mac, or Windows with WebView2, which ships
    with Windows 10 and 11.)"""
    if sys.platform not in ("darwin", "win32"):
        return False
    try:
        if sys.platform == "win32":
            return wx.html2.WebView.IsBackendAvailable(wx.html2.WebViewBackendEdge)
        return True
    except Exception:  # noqa: BLE001
        return False


def webview_folder() -> str:
    """Windows: where the sign-in window's WebView2 keeps its data (never Edge's own)."""
    return os.path.join(accounts.own_folder(), "webview")


def webview_profile() -> str:
    return os.path.join(webview_folder(), "EBWebView", "Default")


# ---------------------------------------------------------------- the Mac's cookie store

def _objc():
    import ctypes
    import ctypes.util
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]

    def send(obj, sel, *args, restype=ctypes.c_void_p, argtypes=()):
        f = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)(("objc_msgSend", objc))
        return f(obj, objc.sel_registerName(sel.encode()), *args)
    return ctypes, objc, send


_blocks = []  # every block handed to WebKit stays alive here: it may be called after we return


def _block(fn, argtypes):
    """An Objective-C block calling `fn`, for WebKit's completion handlers. A global block: WebKit
    copies it, and copying a global block hands back the same one, which this list keeps alive."""
    import ctypes
    lib = ctypes.CDLL(None)
    isa = ctypes.c_void_p.in_dll(lib, "_NSConcreteGlobalBlock")

    class Desc(ctypes.Structure):
        _fields_ = [("reserved", ctypes.c_ulong), ("size", ctypes.c_ulong)]

    class Block(ctypes.Structure):
        _fields_ = [("isa", ctypes.c_void_p), ("flags", ctypes.c_int), ("reserved", ctypes.c_int),
                    ("invoke", ctypes.c_void_p), ("desc", ctypes.POINTER(Desc))]
    invoke = ctypes.CFUNCTYPE(None, ctypes.c_void_p, *argtypes)(fn)
    desc = Desc(0, ctypes.sizeof(Block))
    blk = Block(ctypes.addressof(isa), 1 << 28, 0, ctypes.cast(invoke, ctypes.c_void_p), ctypes.pointer(desc))
    _blocks.append((invoke, desc, blk))
    del _blocks[:-16]
    return ctypes.addressof(blk)


def _mac_store(webview):
    ctypes, objc, send = _objc()
    view = int(webview.GetNativeBackend())
    data = send(send(view, "configuration"), "websiteDataStore")
    return ctypes, send, data


def mac_cookies(webview, done) -> None:
    """Every cookie the sign-in window holds, HttpOnly ones included, as dicts; `done(list)` is
    called on the main thread."""
    ctypes, send, data = _mac_store(webview)
    store = send(data, "httpCookieStore")

    def text(obj):
        if not obj:
            return ""
        p = send(obj, "UTF8String", restype=ctypes.c_char_p)
        return p.decode("utf-8", "replace") if p else ""

    def got(_blk, array):
        out = []
        try:
            for i in range(send(array, "count", restype=ctypes.c_ulong)):
                c = send(array, "objectAtIndex:", i, argtypes=(ctypes.c_ulong,))
                when = send(c, "expiresDate")
                out.append({"name": text(send(c, "name")), "value": text(send(c, "value")),
                            "domain": text(send(c, "domain")), "path": text(send(c, "path")) or "/",
                            "secure": bool(send(c, "isSecure", restype=ctypes.c_bool)),
                            "expires": int(send(when, "timeIntervalSince1970", restype=ctypes.c_double)) if when else 0})
        except Exception:  # noqa: BLE001 - a half-read store is still worth keeping
            pass
        wx.CallAfter(done, out)
    send(store, "getAllCookies:", _block(got, (ctypes.c_void_p,)), argtypes=(ctypes.c_void_p,))


def mac_forget(webview, done) -> None:
    """Sign out of everything the sign-in window ever signed in to: its cookies and site data."""
    ctypes, send, data = _mac_store(webview)
    objc = _objc()[1]
    types = send(objc.objc_getClass(b"WKWebsiteDataStore"), "allWebsiteDataTypes")
    past = send(objc.objc_getClass(b"NSDate"), "distantPast")
    send(data, "removeDataOfTypes:modifiedSince:completionHandler:", types, past,
         _block(lambda _b: wx.CallAfter(done), ()), argtypes=(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p))


# ---------------------------------------------------------------- the window

class SignInWindow(wx.Dialog):
    """The site's sign-in page, and around it: which site, Go Back, and I'm Done. Closing it any
    way at all (I'm Done, Escape, the close box) keeps whatever sign-in it made."""

    def __init__(self, parent, service: int = 0, url: str = "", keep=None, hidden: bool = False):
        super().__init__(parent, title="Sign In", size=(900, 760),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
        from .system import mac_accessibility_label, windows_name
        self.keep = keep  # Mac: called with the services signed in to, after the cookies are kept
        self.services = []
        self.closing = False
        s = wx.BoxSizer(wx.VERTICAL)
        row = wx.BoxSizer(wx.HORIZONTAL)
        lab = wx.StaticText(self, label="Sign in to:")
        self.site = wx.Choice(self, choices=[n for n, _, _ in SERVICES] + [OTHER])
        self.site.SetSelection(service if 0 <= service < len(SERVICES) else 0)
        self.site.SetToolTip("Which site's sign-in page to show. YouTube's sign-in also covers YouTube Music. "
                             "Another Site asks for an address, for any other site you use.")
        mac_accessibility_label(self.site, "Sign in to")
        windows_name(self.site, "Sign in to")
        row.Add(lab, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        row.Add(self.site, 0, wx.RIGHT, 12)
        self.back = wx.Button(self, label="Go Back a Page")
        self.back.SetToolTip("Goes back to the page before, as a browser's Back button does.")
        row.Add(self.back, 0, wx.RIGHT, 6)
        self.done = wx.Button(self, wx.ID_CANCEL, "I'm Done")
        self.done.SetToolTip("Closes this window and keeps the sign-in (Escape does the same). Wavelength uses "
                             "it for every download, search and stream from then on.")
        row.AddStretchSpacer()
        row.Add(self.done, 0)
        s.Add(row, 0, wx.EXPAND | wx.ALL, 8)
        self.status = wx.StaticText(self, label="")
        s.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.web = wx.html2.WebView.New(self, backend=wx.html2.WebViewBackendEdge if sys.platform == "win32"
                                        else wx.html2.WebViewBackendDefault)
        if sys.platform == "darwin":
            self.web.SetUserAgent(MAC_AGENT)
        self.web.SetToolTip("The site's own sign-in page. Sign in as you would in a browser.")
        s.Add(self.web, 1, wx.EXPAND)
        self.SetSizer(s)
        textsize.apply(self)
        self.SetEscapeId(wx.ID_CANCEL)
        self.site.Bind(wx.EVT_CHOICE, lambda e: self.go_to(self.site.GetSelection()))
        self.back.Bind(wx.EVT_BUTTON, lambda e: self.web.CanGoBack() and self.web.GoBack())
        self.done.Bind(wx.EVT_BUTTON, lambda e: self.finish())
        self.Bind(wx.EVT_CLOSE, lambda e: self.finish())
        self.web.Bind(wx.html2.EVT_WEBVIEW_LOADED, self._loaded)
        self.web.Bind(wx.html2.EVT_WEBVIEW_NEWWINDOW, self._new_window)
        self.web.Bind(wx.html2.EVT_WEBVIEW_TITLE_CHANGED, lambda e: self._title())
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        # On the Mac the page keeps its keys from wx; the app's key monitor still sees them first.
        from .system import add_key_monitor
        self._monitor = add_key_monitor(self._on_mac_key)
        if url:
            self.site.SetSelection(len(SERVICES))
            self.web.LoadURL(url)
        else:
            self.go_to(self.site.GetSelection(), say=False)
        if hidden:  # the self-test: a real window, kept off the screen
            self.SetPosition((-5000, -5000))
        else:
            self.CentreOnParent()
            # The title is read as the window opens; the line saying what to do follows it.
            wx.CallLater(900, lambda: self and not self.closing and self._show(self.status.GetLabel()))

    def _on_key(self, event):
        # The page has the keys while it has the focus; Escape still leaves, and Command-W
        # (Control-W) closes the window as it would a browser tab.
        k = event.GetKeyCode()
        if k == wx.WXK_ESCAPE or (event.CmdDown() and k in (ord("W"), ord("w"))):
            self.finish()
            return
        event.Skip()

    def _on_mac_key(self, code, flags) -> bool:
        from .system import MAC_COMMAND, MAC_CONTROL, MAC_OPTION, MAC_SHIFT
        if not self or not self.IsActive() or self.closing:
            return False
        plain = not flags & (MAC_COMMAND | MAC_OPTION | MAC_SHIFT | MAC_CONTROL)
        if (code == 53 and plain) or (code == 13 and flags & MAC_COMMAND  # Escape; Command-W
                                      and not flags & (MAC_OPTION | MAC_SHIFT | MAC_CONTROL)):
            wx.CallAfter(lambda: self and self.finish())
            return True
        return False

    def _drop_monitor(self):
        if getattr(self, "_monitor", None):
            from .system import remove_key_monitor
            remove_key_monitor(self._monitor)
            self._monitor = None

    def Destroy(self):  # noqa: N802 - wx's name
        self._drop_monitor()
        return super().Destroy()

    def go_to(self, i: int, say: bool = True):
        if i >= len(SERVICES):
            dlg = wx.TextEntryDialog(self, "The address of the site to sign in to, such as vimeo.com:",
                                     "Another Site")
            ok = dlg.ShowModal() == wx.ID_OK
            addr = dlg.GetValue().strip() if ok else ""
            dlg.Destroy()
            if not addr:
                return
            self.web.LoadURL(addr if "://" in addr else "https://" + addr)
            self._show("Opening %s. Sign in there as you would in a browser, then press I'm Done." % addr, say)
            return
        name, url, about = SERVICES[i]
        self.web.LoadURL(url)
        self._show("%s's sign-in page. %s Sign in as you would in a browser; I'll say when it worked." % (name, about),
                   say)
        self.web.SetFocus()

    def _show(self, text, say=True):
        self.status.SetLabel(text)
        self.status.Wrap(max(300, self.GetClientSize().width - 20))
        self.Layout()
        if say:
            from .system import announce
            announce(text, polite=True)

    def _title(self):
        t = self.web.GetCurrentTitle()
        self.SetTitle("Sign In: %s" % t if t else "Sign In")

    def _new_window(self, event):
        # A sign-in that opens a new window (SoundCloud's "Continue with Google") stays in this one.
        url = event.GetURL()
        if url:
            self.web.LoadURL(url)

    def _loaded(self, _event):
        self.back.Enable(self.web.CanGoBack())
        if sys.platform == "darwin":
            mac_cookies(self.web, self._have)

    def _have(self, cookies):
        """Mac: after every page, see which sites the window is signed in to now, and keep it."""
        if not self:
            return
        services = accounts.save_own(cookies) if cookies else []
        fresh = [s for s in services if s not in self.services]
        self.services = services
        if fresh and not self.closing:
            from .system import cue
            cue("signed_in")
            self._show("You're signed in to %s, and I've kept it. Press I'm Done, or choose another site to sign "
                       "in to." % accounts.and_list(fresh))
            self.done.SetFocus()

    def finish(self):
        if self.closing:
            return
        self.closing = True
        self._drop_monitor()
        if sys.platform == "darwin":
            def kept(cookies):
                services = accounts.save_own(cookies) if cookies else accounts.own_services()
                if self.keep:
                    self.keep(services)
                if self:
                    self.EndModal(wx.ID_OK) if self.IsModal() else self.Destroy()
            mac_cookies(self.web, kept)
        elif self.IsModal():
            self.EndModal(wx.ID_OK)
        else:
            self.Destroy()


# ---------------------------------------------------------------- opening it

def sign_in(parent, service: int, done) -> None:
    """Show the sign-in window for SERVICES[service]; `done(services, error)` afterwards, on the
    main thread, with the services the kept sign-in covers."""
    if sys.platform == "win32":
        _windows(service, done)
        return
    got = {}
    dlg = SignInWindow(parent, service, keep=lambda s: got.__setitem__("services", s))
    dlg.ShowModal()
    dlg.Destroy()
    wx.CallAfter(done, got.get("services", accounts.own_services()), "")


def _windows(service: int, done, test_url: str = "") -> None:
    from .manager import run_task, worker_command
    cmd = worker_command()[:-1] + ["--signin", str(service)]
    env = dict(os.environ, WEBVIEW2_USER_DATA_FOLDER=webview_folder())
    if test_url:
        env["MEDIA_DOWNLOAD_SIGNIN_TEST"] = test_url

    def work():
        try:
            subprocess.run(cmd, env=env, creationflags=0x08000000, timeout=120)
        except (OSError, subprocess.SubprocessError) as exc:
            wx.CallAfter(done, accounts.own_services(), str(exc))
            return
        if not os.path.isdir(webview_profile()):
            wx.CallAfter(done, accounts.own_services(), "")
            return
        got = {"log": []}

        def on(ev):
            if ev.get("ev") == "saved":
                got["services"] = ev.get("services") or []
            elif ev.get("ev") == "log":
                got["log"].append(ev.get("text", ""))
        run_task({"task": "signin_save", "profile": webview_profile()}, on, timeout=60)
        wx.CallAfter(done, got.get("services", accounts.own_services()),
                     "" if "services" in got else "\n".join(got["log"])[-300:])
    threading.Thread(target=work, daemon=True).start()


def run_window(argv) -> int:
    """`--signin N`: the Windows sign-in window, in its own process (see the module's words)."""
    os.makedirs(webview_folder(), exist_ok=True)
    os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER", webview_folder())
    app = wx.App(False)
    app.SetAppName("Wavelength")
    try:
        service = int(argv[0]) if argv else 0
    except ValueError:
        service = 0
    test_url = os.environ.get("MEDIA_DOWNLOAD_SIGNIN_TEST")  # the self-test's own page, never a real site
    dlg = SignInWindow(None, service, url=test_url or "", hidden=bool(test_url))
    if test_url:
        def loaded(event):
            event.Skip()
            if event.GetURL().startswith(test_url):
                wx.CallLater(1500, dlg.finish)
        dlg.web.Bind(wx.html2.EVT_WEBVIEW_LOADED, loaded)
        wx.CallLater(30000, dlg.finish)
    dlg.ShowModal()
    dlg.Destroy()
    return 0


def forget(parent, done) -> None:
    """Sign out of everything signed in to inside Wavelength: the kept cookies, and the sign-in
    window's own memory of the sites, so the next sign-in starts fresh."""
    accounts.forget_own()
    if sys.platform == "win32":
        import shutil
        shutil.rmtree(webview_folder(), ignore_errors=True)
        wx.CallAfter(done)
        return
    if sys.platform != "darwin":
        wx.CallAfter(done)
        return
    holder = wx.Frame(parent, size=(10, 10), pos=(-2000, -2000))
    web = wx.html2.WebView.New(holder)

    def gone():
        holder.Destroy()
        done()
    try:
        mac_forget(web, gone)
    except Exception:  # noqa: BLE001
        gone()


def round_trip() -> str:
    """The self-test: a page on this computer sets an HttpOnly cookie in the real sign-in window,
    and the sign-in Wavelength keeps must hold it. "" when it does, else what went wrong. Needs a
    running wx.App. Never touches a real site."""
    import http.server
    import time
    import uuid
    secret = uuid.uuid4().hex

    class Page(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Set-Cookie", "selftest=%s; HttpOnly; Path=/; Max-Age=20" % secret)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<title>Wavelength self-test</title><p>Self-test</p>")

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/" % srv.server_port
    state = {"done": False, "error": ""}

    def kept(*_a):
        state["done"] = True
        if len(_a) > 1 and _a[1]:
            state["error"] = _a[1]
    try:
        if not available():
            return "no web view on this computer"
        if sys.platform == "win32":
            _windows(0, kept, test_url=url)
        else:
            w = SignInWindow(None, url=url, keep=kept, hidden=True)
            w.ShowWithoutActivating()

            def look():
                if any(c["value"] == secret for c in accounts.read_netscape(accounts.own_file())):
                    w.finish()
                else:
                    wx.CallLater(200, look)
            wx.CallLater(200, look)
        loop = wx.GUIEventLoop()
        end = time.time() + 90
        timer = wx.Timer()
        timer.Bind(wx.EVT_TIMER, lambda e: (state["done"] or time.time() > end) and loop.Exit())
        timer.Start(100)
        loop.Run()
        timer.Stop()
        if not state["done"]:
            return "the sign-in window never finished"
        if not any(c["value"] == secret for c in accounts.read_netscape(accounts.own_file())):
            return "the HttpOnly cookie wasn't kept" + (": " + state["error"] if state["error"] else "")
        return ""
    finally:
        srv.shutdown()
