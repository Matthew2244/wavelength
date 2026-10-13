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
    "https://github.com/Matthew2244/ytdl-accessible/releases/latest/download/appcast.xml"


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


def sparkle_bin() -> str:
    """Sparkle's command-line tools: sign_update, generate_keys."""
    return os.path.join(sparkle_dir(), "bin")
