"""Build the app for the platform this runs on: python build_app.py

Mac:     dist/Media Download.app, zipped to dist/Media-Download-mac.zip
Windows: dist/Media Download/ (folder with the .exe), zipped to dist/Media-Download-windows.zip

The download engine (yt-dlp and its YouTube solver) is bundled so the app works
the moment it opens; newer engines arrive later on their own (engine.py).
"""
import os
import shutil
import subprocess
import sys
import tempfile

from media_download import APP_NAME, __version__

NAME = APP_NAME
SLUG = "Media-Download"
args = [
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", NAME,
    "--collect-data", "certifi", "--collect-all", "yt_dlp_ejs",
    "--hidden-import", "media_download.gui", "--hidden-import", "media_download.worker",
    "--hidden-import", "media_download.selftest",
]
icon = os.path.join("assets", "icon.icns" if sys.platform == "darwin" else "icon.ico")
if os.path.exists(icon):
    args += ["--icon", icon]
SIGN_ID = os.environ.get("MEDIA_DOWNLOAD_SIGN_ID")  # set by tools/release_mac.py; empty means ad-hoc
if sys.platform == "darwin":
    args += ["--osx-bundle-identifier", "io.github.matthew2244.mediadownload"]
    if SIGN_ID:
        args += ["--codesign-identity", SIGN_ID]
args.append("app.py")
subprocess.run(args, check=True)

os.chdir("dist")
if sys.platform == "darwin":
    plist = f"{NAME}.app/Contents/Info.plist"
    for key in ("CFBundleShortVersionString", "CFBundleVersion"):
        subprocess.run(["plutil", "-replace", key, "-string", __version__, plist], check=True)
    # Text files and web locations dropped on the Dock icon add their links.
    subprocess.run(["plutil", "-insert", "CFBundleDocumentTypes", "-json",
                    '[{"CFBundleTypeName":"Links","CFBundleTypeRole":"Viewer",'
                    '"LSItemContentTypes":["public.plain-text","com.apple.web-internet-location","public.url"],'
                    '"LSHandlerRank":"Alternate"}]', plist], check=True)
    subprocess.run(["plutil", "-replace", "NSHumanReadableCopyright", "-string",
                    "Free and open source, MIT license.", plist], check=True)
    if SIGN_ID:
        subprocess.run(["codesign", "--force", "--options", "runtime", "--timestamp",
                        "--sign", SIGN_ID, f"{NAME}.app"], check=True)
    else:
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", f"{NAME}.app"], check=True)
    out = f"{SLUG}-mac.zip"
    if os.path.exists(out):
        os.remove(out)
    subprocess.run(["ditto", "-c", "-k", "--keepParent", f"{NAME}.app", out], check=True)
    exe = f"{NAME}.app/Contents/MacOS/{NAME}"
else:
    out = f"{SLUG}-windows"
    shutil.make_archive(out, "zip", ".", NAME)
    out += ".zip"
    exe = os.path.join(NAME, NAME + ".exe")
# A file, not a pipe, with a time limit: a broken build can leave a helper
# holding a pipe open, and reading it would wait forever.
with tempfile.TemporaryFile("w+") as log:
    try:
        subprocess.run([exe, "--self-test"], stdout=log, stderr=subprocess.STDOUT, timeout=180)
    except subprocess.TimeoutExpired:
        sys.exit("Self-test: TIMED OUT")
    log.seek(0)
    result = log.read().strip().splitlines()[-1:] or ["(no output)"]
print("Self-test:", result[0])
if "OK" not in result[0]:
    sys.exit("The built app failed its self-test.")
print("Built", os.path.abspath(out))
