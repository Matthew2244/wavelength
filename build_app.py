"""Build the app for the platform this runs on: python build_app.py

Mac:     dist/Wavelength.app, zipped to dist/Wavelength-mac.zip
Windows: dist/Wavelength/ (folder with the .exe), zipped to dist/Wavelength-windows.zip

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
SLUG = "Wavelength"
args = [
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", NAME,
    "--collect-data", "certifi", "--collect-all", "yt_dlp_ejs",
    # curl_cffi lets the engine look like a real browser to sites that turn others away.
    "--collect-all", "curl_cffi",
    # The app's own finish and fail sounds (system.sound_file).
    "--add-data", os.path.join("assets", "sounds") + os.pathsep + os.path.join("assets", "sounds"),
    "--hidden-import", "media_download.gui", "--hidden-import", "media_download.worker",
    "--hidden-import", "media_download.selftest",
]
if sys.platform == "win32":
    from build_app_support import winsparkle_dll
    args += ["--add-binary", winsparkle_dll() + os.pathsep + "."]  # updates for installed copies
    # Prism: speech through NVDA, JAWS, Narrator and others. Its compiled part loads cffi's
    # backend from C, so nothing names it and the packager would leave it out.
    # The compiled part (_prism_cffi.pyd) isn't a file type the packager collects on its own,
    # so the whole native folder is copied in by hand.
    import importlib.util
    native = os.path.join(importlib.util.find_spec("prism").submodule_search_locations[0], "_native")
    args += ["--collect-all", "prism", "--hidden-import", "_cffi_backend"]
    for f in os.listdir(native):
        args += ["--add-binary", os.path.join(native, f) + os.pathsep + "prism/_native"]
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

from build_app_support import FEED, SPARKLE_PUBLIC_KEY, sparkle_dir  # noqa: E402


def embed_sparkle(app: str, sign_id: str | None) -> None:
    fw_dir = os.path.join(app, "Contents", "Frameworks")
    os.makedirs(fw_dir, exist_ok=True)
    dest = os.path.join(fw_dir, "Sparkle.framework")
    shutil.rmtree(dest, ignore_errors=True)
    subprocess.run(["ditto", os.path.join(sparkle_dir(), "Sparkle.framework"), dest], check=True)
    # The XPC services are for sandboxed apps; this one isn't, so they're left out.
    shutil.rmtree(os.path.join(dest, "Versions", "B", "XPCServices"), ignore_errors=True)
    sign = ["codesign", "--force", "--sign", sign_id or "-"]
    if sign_id:
        sign += ["--options", "runtime", "--timestamp"]
    b = os.path.join(dest, "Versions", "B")
    for part in (os.path.join(b, "Autoupdate"), os.path.join(b, "Updater.app"), dest):
        subprocess.run(sign + [part], check=True)


os.chdir("dist")
if sys.platform == "darwin":
    plist = f"{NAME}.app/Contents/Info.plist"
    embed_sparkle(f"{NAME}.app", SIGN_ID)
    for key, kind, value in (("SUFeedURL", "-string", FEED), ("SUPublicEDKey", "-string", SPARKLE_PUBLIC_KEY),
                             ("SUEnableAutomaticChecks", "-bool", "YES"),
                             ("SUScheduledCheckInterval", "-integer", "86400")):
        subprocess.run(["plutil", "-replace", key, kind, value, plist], check=True)
    if os.environ.get("MEDIA_DOWNLOAD_TEST_FEED"):  # a local test feed is plain http
        subprocess.run(["plutil", "-replace", "NSAppTransportSecurity", "-json",
                        '{"NSAllowsLocalNetworking": true}', plist], check=True)
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
    # The installer: per-person, no administrator, Start menu, uninstall in Settings.
    iscc = shutil.which("ISCC") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if os.path.exists(iscc):
        iss = os.path.join("..", "packaging", "windows", "Wavelength.iss")
        subprocess.run([iscc, "/Q", f"/DAppVersion={__version__}", f"/DSourceDir={os.path.abspath(NAME)}", iss],
                       check=True)
        print("Built", os.path.abspath(f"{SLUG}-Setup.exe"))
    else:
        print("Inno Setup isn't installed, so no installer this time (the zip still works).")
# A file, not a pipe, with a time limit: a broken build can leave a helper
# holding a pipe open, and reading it would wait forever.
with tempfile.TemporaryFile("w+") as log:
    try:
        subprocess.run([exe, "--self-test"], stdout=log, stderr=subprocess.STDOUT, timeout=180)
    except subprocess.TimeoutExpired:
        sys.exit("Self-test: TIMED OUT")
    log.seek(0)
    lines = log.read().strip().splitlines()
    for line in lines[:-1]:
        print("  " + line)
    result = lines[-1:] or ["(no output)"]
print("Self-test:", result[0])
if "OK" not in result[0]:
    sys.exit("The built app failed its self-test.")
print("Built", os.path.abspath(out))
