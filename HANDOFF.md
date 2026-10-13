# Handoff: ytdl-accessible

Read this before changing anything. It describes the current state. `CLAUDE.md`
in Matthew's private notes has the `ytdl` and `ytdescribe` reasoning.

## What exists

| thing | where | note |
|---|---|---|
| Media Download (the app) | `media_download/` | wxPython, Mac and Windows; installed at `/Applications/Media Download.app` on the Studio |
| `ytdl` | `ytdl` | the command; `~/bin/ytdl` is a symlink into the repo |
| `ytdescribe` | `ytdescribe` | audio description; `~/bin/ytdescribe` likewise |
| classic dialog app | `legacy/MediaDownload.applescript` | the old AppleScript app, kept compiling for anyone who prefers it |
| public repo | [Matthew2244/ytdl-accessible](https://github.com/Matthew2244/ytdl-accessible) | MIT |

The app and the command share one settings file, `~/.config/ytdl/config.json`.
The app's own keys start with `app_`; `save_settings()` keeps any key it doesn't
know. Video quality lives in `app_max_height`, not `max_height`, because the app
has a value (-1, any codec) the command would misread.

## How the app is built

- `gui.py` the window; `dialogs.py` More Options, Settings, playlist question,
  tick list, Search. `system.py` announcements (VoiceOver on the Mac, Prism on
  Windows), reveal/open, sounds, Pushover. It must import without wx: the
  Linux CI tests import it and don't install wx.
- `manager.py` the download list and scheduler, no wx, fully testable.
  Limits: downloads at once (automatic = half the cores, 2 to 8), per site (3,
  counting only rows downloading, not converting), lookups (4).
- `worker.py` one process per download or lookup, started as `<app> --worker`
  (frozen) or `python -m media_download --worker`. Task as one JSON line on
  stdin; events as JSON lines on stdout; `ev: end` always last. Its own process
  group, so Stop kills ffmpeg too.
- `options.py` builds yt-dlp **command-line flags** and lets
  `yt_dlp.parse_options()` turn them into options, so the app and `ytdl` mean
  the same thing by every choice and raw flags under More Options just work.
- `engine.py` paths, settings, helper tools, and keeping yt-dlp current.
- `words.py` every sentence the app says. Rows are status first.
- `update.py` the app's own updates from GitHub releases (from MIDI Tempo Fix).
- `launch.py` the one entry point: `--worker`, `--probe-engine`, `--self-test`,
  else the window.

**The engine.** yt-dlp and yt-dlp-ejs are bundled. Newer ones are fetched from
PyPI (wheels, sha256 checked, yt-dlp-ejs at the exact version yt-dlp pins) into
`~/Library/Application Support/Media Download/engine/<version>/`, proved by
starting it (`--probe-engine`), and preferred when newer than the bundled copy.
Two are kept. Daily check at launch; also on a failure that a newer engine could
fix (`worth_updating_for`), then one retry.

**Helper tools.** ffmpeg, ffprobe and deno are taken from Homebrew or PATH when
present. Otherwise "Get Helper Tools" fetches them once into `.../tools/`. Mac:
Martin Riedl's signed static ffmpeg builds, deno's GitHub release (sha256
checked); each must pass `codesign --verify` and run. Windows: yt-dlp's own
FFmpeg-Builds and deno's release.

**Playlists** are expanded into one row per item, numbered, into a folder named
after the set. When the listing already holds a whole item (archive.org does),
it's saved as an info file and the item downloads from that. Fetching the item
again made the engine re-download whole files just to identify them, and
archive.org answered HTTP 500 under load. Items are named from the listing title,
which beats archive.org's file ids.

## Commands

    .venv/bin/python -m media_download          run from source
    ./check.sh                                  before every commit (tests, self-test, Escape, labels)
    .venv/bin/python build_app.py               build for this computer, runs the self-test
    .venv/bin/python tools/screenshot.py X.png [POINTS]   window draws itself, no screen capture
    .venv/bin/python tools/drive.py WORKDIR [links...]    real window, real downloads, off-screen
    .venv/bin/python tools/make_icon.py         redraw assets/icon.*
    .venv/bin/python tools/release_mac.py vX.Y.Z  sign, notarize, staple, replace the release's Mac zip

The venv is `.venv` (Python 3.14, wxPython 4.3.1). `MEDIA_DOWNLOAD_TEST_DIR`
puts every file the app writes (settings, list, engine, tools) inside one folder.
Use it for any test, so Matthew's real settings and list are never touched.

Release: bump `media_download/__init__.py`, commit, tag `vX.Y.Z`, push the tag.
CI (`.github/workflows/build.yml`) tests on three systems and attaches both
zips to the release. Then run `tools/release_mac.py vX.Y.Z` on the Studio to
replace the unsigned Mac zip with the signed, notarized one. Watch CI to green.

## Things that bite

1. **On the Mac, a button's "&D" also answers Command-D.** It stole View, Go to
   Downloads List. `M()` drops mnemonics on the Mac; Windows keeps them for Alt.
2. **A popup menu (wx.Choice) draws blank with a bigger font**, and sizes itself
   to its first label. Popups and buttons keep the system size; `_fit_choices()`
   sets their width.
3. **The phone ping must not echo on the Mac.** With `notify` on, `pushover`'s
   local echo spoke through VoiceOver on top of the app's own announcement and
   VoiceOver stopped answering until restarted. The app sends with
   `PUSHOVER_NO_LOCAL_ECHO=1`; it already speaks and plays a sound.
4. **YouTube's best video is AV1 or VP9**, which QuickTime on many Macs can't
   play. Video prefers H.264 up to 1080; "Highest available, any codec" and
   1440/4K take whatever is best.
5. **VoiceOver re-reads a check-list row before the tick lands**, saying
   "unchecked" right after you tick it. The tick lists announce the new count.
6. **Tab skips plain text**, so "Saving to" and "Next download" are also in the
   help text of the buttons beside them.
7. **Message dialogs need a button titled exactly "Cancel"** for Escape on the
   Mac (`check.sh` enforces it), and every custom dialog sets an Escape button.
8. **`ytmsearch:` doesn't exist.** YouTube Music search uses its search page,
   songs section.
9. From the classic app, still true for the command: a GUI-launched process gets
   a minimal PATH; `--sub-langs "en.*"` earns HTTP 429; playlists need
   `--flat-playlist`; a named stream must never be converted.

## Tested

- 22 unit and scheduler tests (one hammers Stop and Retry) (`tests/`, fake worker, offline); CI runs them on
  Mac, Windows and Linux.
- Real downloads: YouTube to MP3, H.264 and AV1 video, a 5-second WAV cut,
  SoundCloud, archive.org FLAC, an archive.org playlist of 8 to MP3 (51 s at
  all cores against 171 s one at a time, 0 failures), a dead link explained.
- The frozen app's worker and engine probe; engine update from PyPI in a
  sandbox, including loading the newer engine over an older bundled one.
- Get Helper Tools for real (sandbox, 6 s, ~95 MB): ffmpeg 9.0.2, ffprobe,
  deno 2.9.7, each signature-checked; then a YouTube video downloaded with
  only those, Homebrew hidden.
- v2.0.0: CI green on all eight jobs, Windows app built and self-tested on
  CI, Mac app signed, notarized, stapled, Gatekeeper "Notarized Developer ID".
  Installed on the Studio and the MacBook (self-test OK there; the MacBook has
  no Homebrew tools, so it is the realistic first-run case).
- VoiceOver on the installed app (2026-10-12): tab order and every name and help
  tag, a download by keyboard, Search, the playlist question and tick list,
  Escape, Command-J, Command-D, Command-E.

## Not done

- The self-updater is MIDI Tempo Fix's, unchanged apart from names, but has
  not yet replaced this app with a newer release. The first real test is
  2.0.1: install it through Help, Check for App Updates on both Macs.

- **Windows has not been tried by a person.** Speech there goes through Prism
  (`prismatoid`, MPL-2.0, bundles NVDA's controller client, LGPL): the first
  running reader of NVDA, JAWS, ZDSR, System Access, ZoomText, Sense Reader,
  PC-Talker, BoyPC, else UI Automation notifications (Narrator). Never SAPI or
  OneCore, so nobody without a screen reader gets talked at. The order is
  unit-tested with a fake Prism and the Windows self-test checks Prism loads
  with a UIA backend, but no reader has heard it yet. NVDA is the first to try.
- The Windows build is unsigned, so SmartScreen warns once.
- `ytdescribe` is still command-line only. A "Describe this video" item in the
  app would bring it to everyone.
- `.opus` still has no default app on Matthew's Mac, and "best" is often Opus.
  One Get Info, Open With, Change All on any `.opus` file settles it.
