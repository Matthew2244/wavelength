"""Have a wx window draw itself into a PNG (NSView cacheDisplayInRect). No screen capture,
so no screen-recording prompt. The window must have been shown (off-screen is fine)."""
import ctypes
import ctypes.util


def snap(frame, out):
    win_handle = frame
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]


    def send(o, sel, *a, restype=ctypes.c_void_p, argtypes=()):
        fn = objc.objc_msgSend
        fn.restype = restype
        fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
        return fn(o, objc.sel_registerName(sel.encode()), *a)


    class R(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("w", ctypes.c_double), ("h", ctypes.c_double)]


    win = send(frame.GetChildren()[0].GetHandle(), "window")
    content = send(send(win, "contentView"), "superview") or send(win, "contentView")
    bounds = send(content, "bounds", restype=R)
    rep = send(content, "bitmapImageRepForCachingDisplayInRect:", bounds, argtypes=(R,))
    send(content, "cacheDisplayInRect:toBitmapImageRep:", bounds, rep, restype=None, argtypes=(R, ctypes.c_void_p))
    props = send(objc.objc_getClass(b"NSDictionary"), "dictionary")
    data = send(rep, "representationUsingType:properties:", 4, props, argtypes=(ctypes.c_ulong, ctypes.c_void_p))
    path = send(objc.objc_getClass(b"NSString"), "stringWithUTF8String:", out.encode(), argtypes=(ctypes.c_char_p,))
    ok = send(data, "writeToFile:atomically:", path, True, restype=ctypes.c_bool, argtypes=(ctypes.c_void_p, ctypes.c_bool))
    return ok, bounds.w, bounds.h
