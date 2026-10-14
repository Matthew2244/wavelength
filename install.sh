#!/bin/bash
# Install ytdl, ytdescribe and the Wavelength app (from the latest release).
#
# Plain sentences, one per line, no progress bars — the whole project exists
# because scrolling output is useless when you are listening to it.
#
# Never uses sudo. If something needs a permission this script does not have,
# it says so and stops rather than escalating.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNINSTALL=no
[ "${1:-}" = "--uninstall" ] && UNINSTALL=yes

say() { printf '%s\n' "$*"; }
fail() { printf '%s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- uninstall

if [ "$UNINSTALL" = yes ]; then
  say "Removing ytdl-accessible."
  for d in "$HOME/bin" "$HOME/.local/bin" /usr/local/bin; do
    for t in ytdl ytdescribe; do
      if [ -L "$d/$t" ] && [ "$(readlink "$d/$t")" = "$HERE/$t" ]; then
        rm -f "$d/$t" && say "  removed $d/$t"
      fi
    done
  done
  for a in "/Applications/Wavelength.app" "$HOME/Applications/Wavelength.app"; do
    [ -d "$a" ] && rm -rf "$a" && say "  removed $a"
  done
  say ""
  say "Done. Your settings in ~/.config/ytdl and anything you downloaded were left alone."
  say "yt-dlp and ffmpeg were left installed; remove them with: brew uninstall yt-dlp ffmpeg"
  exit 0
fi

say "Installing ytdl-accessible."
say ""

# ---------------------------------------------------------------- 1. checks

[ "$(uname)" = "Darwin" ] || fail "This installer is for macOS. On Linux, ytdl itself still works — link it onto your PATH by hand."

if ! command -v brew >/dev/null 2>&1; then
  say "Homebrew is not installed, and it is how yt-dlp and ffmpeg get on your Mac."
  say "Install it first, from https://brew.sh, then run this again."
  exit 1
fi

# ------------------------------------------------------------ 2. the tools

say "Step 1 of 4. Checking yt-dlp and ffmpeg."
MISSING=""
command -v yt-dlp  >/dev/null 2>&1 || MISSING="$MISSING yt-dlp"
command -v ffmpeg  >/dev/null 2>&1 || MISSING="$MISSING ffmpeg"

if [ -n "$MISSING" ]; then
  say "  Installing:$MISSING. This can take a few minutes."
  # shellcheck disable=SC2086
  brew install $MISSING >/dev/null 2>&1 || fail "  Homebrew could not install$MISSING. Try it by hand: brew install$MISSING"
  say "  Done."
else
  say "  Both already installed."
fi

# deno arrives as a yt-dlp dependency and is what answers YouTube's player
# challenge. Worth naming, because if it ever goes missing YouTube breaks in a
# way that does not obviously point at it.
if command -v deno >/dev/null 2>&1; then
  say "  deno is present, which is what YouTube's player challenge needs."
else
  say "  Note: deno is missing. YouTube may fail. Fix with: brew install deno"
fi

# ------------------------------------------------- 3. somewhere on your PATH

say ""
say "Step 2 of 4. Finding somewhere on your PATH to put the commands."

BINDIR=""
for d in "$HOME/bin" "$HOME/.local/bin"; do
  case ":$PATH:" in *":$d:"*) BINDIR="$d"; break;; esac
done

PATH_NOTE=""
if [ -z "$BINDIR" ]; then
  # Nothing personal is on the PATH yet. Make the conventional choice and say
  # plainly what has to be added, rather than editing a shell profile behind
  # someone's back.
  BINDIR="$HOME/.local/bin"
  PATH_NOTE="yes"
fi
mkdir -p "$BINDIR" || fail "  Could not create $BINDIR"
say "  Using $BINDIR"

# --------------------------------------------------------------- 4. link it

say ""
say "Step 3 of 4. Linking the commands."
for t in ytdl ytdescribe; do
  [ -f "$HERE/$t" ] || fail "  $t is missing from $HERE"
  chmod +x "$HERE/$t"
  ln -sfn "$HERE/$t" "$BINDIR/$t" || fail "  Could not link $t into $BINDIR"
  say "  $t"
done

# ------------------------------------------------------------------ 5. app

say ""
say "Step 4 of 4. Getting the Wavelength app."
APPDIR="/Applications"
[ -w "$APPDIR" ] || APPDIR="$HOME/Applications"
mkdir -p "$APPDIR"
ZIPURL="https://github.com/Matthew2244/ytdl-accessible/releases/latest/download/Wavelength-mac.zip"
TMPD="$(mktemp -d)"
if curl -fsSL -o "$TMPD/app.zip" "$ZIPURL" && ditto -x -k "$TMPD/app.zip" "$TMPD/x" && [ -d "$TMPD/x/Wavelength.app" ]; then
  rm -rf "$APPDIR/Wavelength.app"
  ditto "$TMPD/x/Wavelength.app" "$APPDIR/Wavelength.app"
  say "  Wavelength is in $APPDIR. It updates itself from now on."
  LSREG="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
  [ -x "$LSREG" ] && "$LSREG" -f "$APPDIR/Wavelength.app" >/dev/null 2>&1
else
  say "  Couldn't download the app. Get it by hand from:"
  say "  https://github.com/Matthew2244/ytdl-accessible/releases/latest"
  say "  The ytdl command works either way."
fi
rm -rf "$TMPD"

# -------------------------------------------------------------- 6. verify

say ""
if "$BINDIR/ytdl" --settings >/dev/null 2>&1; then
  say "Installed, and working."
else
  say "Installed, but ytdl did not run cleanly. Try: $BINDIR/ytdl --help"
fi

say ""
if [ -n "$PATH_NOTE" ]; then
  say "One thing left to do. $BINDIR is not on your PATH, so your shell cannot"
  say "find the ytdl command yet. Add this line to your ~/.zshrc:"
  say ""
  say "    export PATH=\"\$HOME/.local/bin:\$PATH\""
  say ""
  say "Then open a new terminal."
  say ""
fi

say "To get started:"
say "  Open Wavelength from your Applications folder, or"
say "  copy a link and run:  ytdl"
say ""
say "  ytdl --setup     choose where downloads go and what format you want"
say "  ytdl --help      everything it can do"
say ""
say "To remove it all later:  $HERE/install.sh --uninstall"
