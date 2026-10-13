"""Reading audio description aloud during playback.

Two voices, chosen in Settings:
- The system voice (default): `say` on the Mac, Windows' own voices through Prism. The player
  knows exactly when it has finished, so pausing the video to read (extended description)
  resumes at the right moment.
- The screen reader: VoiceOver, NVDA or JAWS, in the person's own voice and rate. Their
  speech can't be timed from here, so the pause is estimated from the length of the text.
"""
from __future__ import annotations

import subprocess
import sys
import time

from .system import announce


class Reader:
    def __init__(self, voice: str = "system", rate: int = 0):
        self.voice = voice
        self.rate = rate
        self.proc = None
        self.until = 0.0
        self.win_backend = None

    def speak(self, text: str) -> None:
        self.stop()
        if self.voice == "screen reader":
            announce(text)
            # Generous: a screen reader at a typical rate reads about 3 words a second.
            self.until = time.time() + 0.8 + len(text.split()) / 2.8
            return
        if sys.platform == "darwin":
            # In-process NSSpeechSynthesizer: `say` takes ~2.4 s just to start on a Mac with
            # hundreds of voices installed, which would land every description late.
            if self._mac_speak(text):
                return
            cmd = ["say"] + (["-r", str(self.rate)] if self.rate else []) + ["--", text]
            try:
                self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                self.proc = None
                self.until = time.time() + 0.8 + len(text.split()) / 2.5
        elif sys.platform == "win32":
            try:
                if self.win_backend is None:
                    from .system import load_prism
                    prism = load_prism()
                    ctx = prism.Context()
                    for name in ("ONE_CORE", "SAPI"):
                        bid = getattr(prism.BackendId, name)
                        if ctx.exists(bid):
                            try:
                                self.win_backend = ctx.acquire(bid)
                                break
                            except Exception:  # noqa: BLE001
                                continue
                    self._ctx = ctx
                self.win_backend.speak(text, interrupt=True)
                self.until = time.time() + 0.5
            except Exception:  # noqa: BLE001
                announce(text)
                self.until = time.time() + 0.8 + len(text.split()) / 2.5
        else:
            try:
                self.proc = subprocess.Popen(["spd-say", "-w", text], stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL)
            except OSError:
                announce(text)
                self.until = time.time() + 0.8 + len(text.split()) / 2.5

    _synth = None

    def _objc(self):
        import ctypes
        import ctypes.util
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        ctypes.cdll.LoadLibrary("/System/Library/Frameworks/AppKit.framework/AppKit")
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        def send(o, sel, *a, restype=ctypes.c_void_p, argtypes=()):
            f = objc.objc_msgSend
            f.restype = restype
            f.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
            return f(o, objc.sel_registerName(sel.encode()), *a)
        return ctypes, objc, send

    def _mac_speak(self, text: str) -> bool:
        try:
            ctypes, objc, send = self._objc()
            if Reader._synth is None:
                synth = send(send(objc.objc_getClass(b"NSSpeechSynthesizer"), "alloc"), "initWithVoice:", None,
                             argtypes=(ctypes.c_void_p,))
                if not synth:
                    return False
                Reader._synth = synth
            if self.rate:
                send(Reader._synth, "setRate:", float(self.rate), restype=None, argtypes=(ctypes.c_float,))
            import os
            if os.environ.get("MEDIA_DOWNLOAD_SILENT_SPEECH"):  # tests at night
                send(Reader._synth, "setVolume:", 0.0, restype=None, argtypes=(ctypes.c_float,))
            ns = send(objc.objc_getClass(b"NSString"), "stringWithUTF8String:", text.encode(),
                      argtypes=(ctypes.c_char_p,))
            return bool(send(Reader._synth, "startSpeakingString:", ns, restype=ctypes.c_bool,
                             argtypes=(ctypes.c_void_p,)))
        except Exception:  # noqa: BLE001
            return False

    def _mac_speaking(self) -> bool:
        if Reader._synth is None:
            return False
        try:
            ctypes, objc, send = self._objc()
            return bool(send(Reader._synth, "isSpeaking", restype=ctypes.c_bool))
        except Exception:  # noqa: BLE001
            return False

    def speaking(self) -> bool:
        if sys.platform == "darwin" and self.voice != "screen reader" and self._mac_speaking():
            return True
        if self.proc is not None:
            if self.proc.poll() is None:
                return True
            self.proc = None
            return False
        if self.win_backend is not None and time.time() >= self.until:
            try:
                return bool(self.win_backend.speaking)
            except Exception:  # noqa: BLE001
                return False
        return time.time() < self.until

    def stop(self) -> None:
        if Reader._synth is not None:
            try:
                ctypes, objc, send = self._objc()
                send(Reader._synth, "stopSpeaking", restype=None)
            except Exception:  # noqa: BLE001
                pass
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
        self.proc = None
        self.until = 0.0
        if self.win_backend is not None:
            try:
                self.win_backend.stop()
            except Exception:  # noqa: BLE001
                pass
