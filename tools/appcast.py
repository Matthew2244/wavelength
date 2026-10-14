"""Write Sparkle's update list for one release: python tools/appcast.py FILE VERSION URL [NOTES.md] [--windows] > appcast.xml

With --windows, FILE is the Windows installer and the list is for WinSparkle.

The zip is signed with the EdDSA key in this Mac's login Keychain (Sparkle's
sign_update finds it there); the signature goes into the appcast, and every copy
of the app checks it against SUPublicEDKey before installing anything.

NOTES.md is the release notes in the simple Markdown the release page uses
(paragraphs and "- " lists), turned into the HTML Sparkle's window shows.
"""
import html
import os
import re
import subprocess
import sys
from email.utils import formatdate

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from build_app_support import sparkle_bin  # noqa: E402

MIN_MACOS = "11.0"


def notes_html(md: str) -> str:
    out, items = [], []
    for block in re.split(r"\n\s*\n", md.strip()):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if all(ln.startswith("- ") for ln in lines):
            items = "".join("<li>%s</li>" % html.escape(ln[2:]) for ln in lines)
            out.append("<ul>%s</ul>" % items)
        else:
            out.append("<p>%s</p>" % html.escape(" ".join(lines)))
    text = "\n".join(out)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", text)


def main():
    windows = "--windows" in sys.argv
    argv = [a for a in sys.argv if a != "--windows"]
    zip_path, version, url = argv[1:4]
    notes = open(argv[4]).read() if len(argv) > 4 else ""
    sig = subprocess.run([os.path.join(sparkle_bin(), "sign_update"), zip_path],
                         capture_output=True, text=True, check=True).stdout.strip()
    if "sparkle:edSignature" not in sig:
        sys.exit("sign_update gave no signature: " + sig)
    item = """    <item>
      <title>Version {v}</title>
      <pubDate>{date}</pubDate>
      <sparkle:version>{v}</sparkle:version>
      <sparkle:shortVersionString>{v}</sparkle:shortVersionString>
      {minsys}
      <description><![CDATA[{notes}]]></description>
      <enclosure url="{url}" {sig} type="application/octet-stream"{win}/>
    </item>""".format(v=version, date=formatdate(usegmt=True), min=MIN_MACOS, notes=notes_html(notes),
                      url=html.escape(url, quote=True), sig=sig,
                      minsys="" if windows else "<sparkle:minimumSystemVersion>%s</sparkle:minimumSystemVersion>" % MIN_MACOS,
                      # WinSparkle runs the installer: quietly, and /relaunch=1 opens the app again after.
                      win=' sparkle:os="windows" sparkle:installerArguments="/SILENT /SP- /SUPPRESSMSGBOXES '
                          '/NORESTART /relaunch=1"' if windows else "")
    print("""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <title>Wavelength</title>
{item}
  </channel>
</rss>""".format(item=item))


if __name__ == "__main__":
    main()
