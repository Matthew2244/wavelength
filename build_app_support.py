"""Sparkle pieces shared by build_app.py and tools/appcast.py."""
import os
import subprocess
import sys

SPARKLE_URL = "https://github.com/sparkle-project/Sparkle/releases/download/2.10.0/Sparkle-2.10.0.tar.xz"
SPARKLE_SHA = "c2bf58aa8387266ac179357b1415d6f2635f044da8be41042af32425dae6da0c"
# The public half of the update-signing key. The private half is in the Studio's login
# Keychain (Sparkle's generate_keys); without it no Sparkle-installed copy accepts an update.
SPARKLE_PUBLIC_KEY = "TJlHNK3idLU77+cj97Pwh4xeuvFhhIVm32CLFwN5Dz0="
FEED = os.environ.get("MEDIA_DOWNLOAD_TEST_FEED") or \
    "https://github.com/Matthew2244/wavelength/releases/latest/download/appcast.xml"


def sparkle_dir() -> str:
    """Sparkle 2.10.0, downloaded once and checked against its known checksum."""
    import hashlib
    import urllib.request
    cache = os.path.join(os.path.expanduser("~"), "Library", "Caches", "media-download-build", "sparkle-2.10.0")
    tar = os.path.join(cache, "Sparkle.tar.xz")
    if not os.path.exists(tar):
        os.makedirs(cache, exist_ok=True)
        urllib.request.urlretrieve(SPARKLE_URL, tar + ".part")
        os.replace(tar + ".part", tar)
    if hashlib.sha256(open(tar, "rb").read()).hexdigest() != SPARKLE_SHA:
        os.remove(tar)
        sys.exit("Sparkle's download didn't match its checksum. Removed it; run the build again.")
    out = os.path.join(cache, "x")
    if not os.path.isdir(os.path.join(out, "Sparkle.framework")):
        os.makedirs(out, exist_ok=True)
        subprocess.run(["tar", "-xf", tar, "-C", out], check=True)
    return out


WINSPARKLE_URL = "https://github.com/vslavik/winsparkle/releases/download/v0.9.4/WinSparkle-0.9.4.zip"
WINSPARKLE_SHA = "6037df37fc263bd1650a1c4949681a9d40ffe991d01f35892a406cb5d103c976"


def winsparkle_dll() -> str:
    """WinSparkle 0.9.4's DLL for this Windows machine's architecture, checksum-verified."""
    import hashlib
    import platform
    import urllib.request
    import zipfile
    cache = os.path.join(os.path.expanduser("~"), ".cache", "media-download-build", "winsparkle-0.9.4")
    z = os.path.join(cache, "WinSparkle.zip")
    if not os.path.exists(z):
        os.makedirs(cache, exist_ok=True)
        urllib.request.urlretrieve(WINSPARKLE_URL, z + ".part")
        os.replace(z + ".part", z)
    if hashlib.sha256(open(z, "rb").read()).hexdigest() != WINSPARKLE_SHA:
        os.remove(z)
        sys.exit("WinSparkle's download didn't match its checksum. Removed it; run the build again.")
    arch = "ARM64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    member = "WinSparkle-0.9.4/%s/Release/WinSparkle.dll" % arch
    out = os.path.join(cache, arch, "WinSparkle.dll")
    if not os.path.exists(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with zipfile.ZipFile(z) as zf, zf.open(member) as src, open(out, "wb") as dst:
            dst.write(src.read())
    return out


def sparkle_bin() -> str:
    """Sparkle's command-line tools: sign_update, generate_keys."""
    return os.path.join(sparkle_dir(), "bin")
