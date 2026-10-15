"""Windows keyboard layouts: what AltGr types on a key. No wx here, so the tests run without it."""
from __future__ import annotations

_VK = {".": 0xBE, ",": 0xBC}  # VK_OEM_PERIOD, VK_OEM_COMMA


def vk_of(keys: str) -> int | None:
    """The Windows virtual key of a shortcut's last key, for keys AltGr can type on: letters,
    digits, period and comma. None for Home, Page Up and the like, which type nothing."""
    k = keys.split("+")[-1]
    if len(k) == 1 and k.isalnum():
        return ord(k.upper())
    return _VK.get(k)


def altgr_char(vk: int, hkl=None) -> str:
    """What AltGr plus this key types on a keyboard layout (the current one by default), or ""
    when it types nothing. A dead key (an accent waiting for its letter) counts as typing."""
    import ctypes
    u = ctypes.windll.user32
    u.GetKeyboardLayout.restype = ctypes.c_void_p
    u.MapVirtualKeyExW.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
    u.ToUnicodeEx.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_char_p, ctypes.c_wchar_p,
                              ctypes.c_int, ctypes.c_uint, ctypes.c_void_p]
    if hkl is None:
        hkl = u.GetKeyboardLayout(0)
    state = bytearray(256)
    for k in (0x11, 0x12, 0xA2, 0xA5):  # Control, Alt, left Control, right Alt: what AltGr sends
        state[k] = 0x80
    buf = ctypes.create_unicode_buffer(8)
    scan = u.MapVirtualKeyExW(vk, 0, hkl)
    n = u.ToUnicodeEx(vk, scan, bytes(state), buf, 8, 4, hkl)  # 4: leave the keyboard state alone
    if n < 0:
        u.ToUnicodeEx(vk, scan, bytes(state), buf, 8, 4, hkl)  # clear the waiting accent
        return "\u0301"  # something typed, nothing to insert by hand
    return buf.value[:n] if n > 0 else ""
