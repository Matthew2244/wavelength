"""Build, sign, notarize and publish the Mac app: python tools/release_mac.py v2.0.0

Run on a Mac that holds a "Developer ID Application" certificate in its
Keychain. It never runs in GitHub Actions on purpose: the signing key and the
notarization key stay on that Mac.

Steps, each checked before the next:
1. Build with PyInstaller, signing every binary inside with the Developer ID
   and the hardened runtime (build_app.py, MEDIA_DOWNLOAD_SIGN_ID set).
2. Verify the signature strictly.
3. Send it to Apple's notary service and wait for the verdict.
4. Staple the approval to the app, so it opens without a warning even offline.
5. Check that Gatekeeper accepts it, zip it, and replace the release's Mac zip
   (the one CI attached unsigned) with this one.
6. Sign that zip for Sparkle (EdDSA key in the Keychain) and attach appcast.xml.

Notarization uses an App Store Connect API key, read from the Keychain entry
named by --keychain-service (account = key ID, password = base64 .p8), the way
this repository's author keeps it. --key-id and --issuer say which key.
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "Media Download"
ZIP = "Media-Download-mac.zip"


def run(cmd, **kw):
    print("$", " ".join(cmd) if isinstance(cmd, list) else cmd, flush=True)
    return subprocess.run(cmd, check=True, text=True, **kw)


def developer_id() -> str:
    out = subprocess.run(["security", "find-identity", "-v", "-p", "codesigning"],
                         capture_output=True, text=True).stdout
    ids = re.findall(r'"(Developer ID Application: [^"]+)"', out)
    if not ids:
        sys.exit("No Developer ID Application certificate in the Keychain. Create one first "
                 "(Xcode, Settings, Accounts, Manage Certificates, +, Developer ID Application).")
    return ids[0]


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("tag", help="The release to publish to, for example v2.0.0. Must already exist on GitHub.")
    p.add_argument("--key-id", default="44L73HXU2W")
    p.add_argument("--issuer", default="4eeb658c-79f1-4dc6-bb6f-54db15d61ce8")
    p.add_argument("--keychain-service", default="asc-api-key")
    p.add_argument("--no-upload", action="store_true", help="Do everything except replacing the release's zip.")
    a = p.parse_args()

    ident = developer_id()
    print("Signing as:", ident)
    os.chdir(ROOT)
    env = dict(os.environ, MEDIA_DOWNLOAD_SIGN_ID=ident)
    run([sys.executable, "build_app.py"], env=env)
    app = os.path.join("dist", f"{NAME}.app")
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", app])

    with tempfile.TemporaryDirectory() as tmp:
        p8 = os.path.join(tmp, f"AuthKey_{a.key_id}.p8")
        b64 = subprocess.run(["security", "find-generic-password", "-s", a.keychain_service, "-a", a.key_id, "-w"],
                             capture_output=True, text=True, check=True).stdout.strip()
        with open(p8, "wb") as f:
            f.write(base64.b64decode(b64))
        os.chmod(p8, 0o600)
        upload = os.path.join(tmp, "notarize.zip")
        run(["ditto", "-c", "-k", "--keepParent", app, upload])
        res = subprocess.run(["xcrun", "notarytool", "submit", upload, "--key", p8, "--key-id", a.key_id,
                              "--issuer", a.issuer, "--wait"], capture_output=True, text=True)
        print(res.stdout, res.stderr)
        if "status: Accepted" not in res.stdout:
            sub = re.search(r"id: ([0-9a-f-]{36})", res.stdout)
            if sub:
                subprocess.run(["xcrun", "notarytool", "log", sub.group(1), "--key", p8, "--key-id", a.key_id,
                                "--issuer", a.issuer])
            sys.exit("Apple did not accept the app. The log above says why.")

    run(["xcrun", "stapler", "staple", app])
    run(["spctl", "--assess", "--type", "execute", "--verbose=2", app])
    out = os.path.join("dist", ZIP)
    if os.path.exists(out):
        os.remove(out)
    run(["ditto", "-c", "-k", "--keepParent", app, out])
    with tempfile.TemporaryFile("w+") as log:  # a file, not a pipe (see build_app.py)
        test = subprocess.run([os.path.join(app, "Contents", "MacOS", NAME), "--self-test"],
                              stdout=log, stderr=subprocess.STDOUT, timeout=120)
        log.seek(0)
        text = log.read()
    print(text.strip().splitlines()[-1] if text.strip() else "(no self-test output)")
    if test.returncode != 0 or "OK" not in text:
        sys.exit("The signed app did not pass its self-test.")
    # Sparkle's update list: this release, its download, and the EdDSA signature of exactly
    # this zip. Installed copies read it from releases/latest/download/appcast.xml.
    version = a.tag.lstrip("v")
    url = f"https://github.com/Matthew2244/ytdl-accessible/releases/download/{a.tag}/{ZIP}"
    notes = subprocess.run(["gh", "release", "view", a.tag, "--json", "body", "--jq", ".body"],
                           capture_output=True, text=True).stdout
    notes_file = os.path.join("dist", "release-notes.md")
    with open(notes_file, "w") as f:
        f.write(notes)
    appcast = os.path.join("dist", "appcast.xml")
    with open(appcast, "w") as f:
        run([sys.executable, os.path.join("tools", "appcast.py"), out, version, url, notes_file], stdout=f)
    uploads = [out, appcast]
    # Windows: CI attached the installer; sign it here (the key never leaves this Mac) and
    # publish WinSparkle's update list beside it.
    setup = os.path.join("dist", "Media-Download-Setup.exe")
    if os.path.exists(setup):
        os.remove(setup)
    got = subprocess.run(["gh", "release", "download", a.tag, "-p", "Media-Download-Setup.exe", "-D", "dist"],
                         capture_output=True, text=True)
    if got.returncode == 0 and os.path.exists(setup):
        win_url = f"https://github.com/Matthew2244/ytdl-accessible/releases/download/{a.tag}/Media-Download-Setup.exe"
        win_cast = os.path.join("dist", "appcast-windows.xml")
        with open(win_cast, "w") as f:
            run([sys.executable, os.path.join("tools", "appcast.py"), setup, version, win_url, notes_file,
                 "--windows"], stdout=f)
        uploads.append(win_cast)
    else:
        print("No Windows installer on the release yet, so no Windows update list this time.")
    if not a.no_upload:
        run(["gh", "release", "upload", a.tag, *uploads, "--clobber"])
    print(f"Done: {out} is signed, notarized, stapled" + ("." if a.no_upload else
          f", and attached to {a.tag} with its signed appcast.xml."))


if __name__ == "__main__":
    main()
