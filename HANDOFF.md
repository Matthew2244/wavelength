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

**Where it stands (2026-10-13):** 2.4.4 is the latest release, signed and
notarized on the Mac, with both appcasts serving it. The Studio took it
through Sparkle (Matthew, the same day; verified 2.4.4, signature valid).
So did the MacBook (verified 2.4.4). Check `CFBundleShortVersionString`
before assuming for any later release. No person has tried the Windows
build yet: NVDA first, then the installer, WinSparkle and the sounds.

Downloads go to **Downloads > Media Downloads on the computer itself** by default,
Mac and Windows (`engine.default_folder`; Windows asks for the real Downloads
folder with SHGetKnownFolderPath). Never a cloud folder by default (Matthew,
2026-10-13): Change Folder is the person's choice. Matthew's own config keeps
the iCloud folder he chose. The command's default and `--setup` order match.

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
- `sparkle.py` app updates on the Mac: Sparkle 2.10.0 in Contents/Frameworks,
  driven through the Objective-C runtime with ctypes. `update.py` (from MIDI
  Tempo Fix) does Windows, and the Mac when run from source.

**Sparkle.** `build_app_support.py` downloads Sparkle once (sha256 pinned),
`build_app.py` embeds the framework without its XPC services (they're for
sandboxed apps), signs it, and writes `SUFeedURL`, `SUPublicEDKey`, daily
checks into Info.plist. The feed is
`releases/latest/download/appcast.xml`; `tools/release_mac.py` writes it with
`tools/appcast.py`, signing the notarized zip with the **EdDSA private key in
the Studio's login Keychain** ("Private key for signing Sparkle updates",
account ed25519, made 2026-10-13; sign_update has Always Allow). **Lose that key
and no Sparkle-installed copy will accept another update.** Back it up with
`~/Library/Caches/media-download-build/sparkle-2.10.0/x/bin/generate_keys -x FILE`
into somewhere safe, never the repo. The Always Allow is tied to sign_update's
path, so a new Sparkle version asks once more. To rehearse an update, build
with `MEDIA_DOWNLOAD_TEST_FEED=http://127.0.0.1:8765/appcast.xml` (adds a
localhost exception), serve a signed appcast and zip, run the copy from a
scratch folder, and afterwards delete the `SU*` keys from
`io.github.matthew2244.mediadownload` defaults: every copy shares that domain.
Windows will use WinSparkle once there's an installer; WinSparkle runs an
installer and can't install a zip.
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

**The player** (`player.py`, `PlayerFrame`, one window, `main.player`). Plays
files and links through `wx.media.MediaCtrl`: AVFoundation on the Mac (verified:
MP3, M4A, Opus, FLAC, MP4, a direct M4A stream URL, YouTube's HLS master
playlist with picture and sound, an Icecast radio stream), WMP10 on Windows.
Links go through the worker's `stream` task first: video on the Mac takes the
HLS master playlist (YouTube no longer offers combined MP4), audio takes M4A/
MP3; it returns English caption cues too. Links the stream task finds to be lists (album, playlist, feed) are listed with
the probe task and queued item by item, each with the list's own title. No
duration from the site means live:
the Mac's player invents a length for live radio (18 hours). Positions per item
in `positions.json` (not the first or last 30 s); speed, volume, captions,
skip length in settings (`app_*`). Plain keys come through `EVT_CHAR_HOOK` and
are written into the Playback menu's names; Tab is handled there too. The video picture is drawn by the
GPU, so `tools/snap.py` draws it black; test playback by state, not pictures.
Test the player muted (`app_volume` 0) at night.

**Audio description** (`describe.py`; worker tasks `find_description` and
`describe`; `dialogs.DescribeDialog`; reading in `player.py` with `speech.Reader`).
Finds the video's own described track, then published described versions
(YouTube search, kept only if they share a distinctive word with the title,
`rank_candidates`), then offers to make one: a `describe` job in the list
downloads a ≤480p copy (or uses the downloaded video), samples frames at shot
changes plus every 12 s of an unchanging shot (≤60), and runs `claude -p
--allowedTools Read` in batches of 10 with the frames' folder as cwd. Output:
"<title> - audio description.srt/.txt" beside the downloads, both labelled
machine-made; `descriptions.json` maps a link to its .srt for streaming. The
player reads each cue at its time: "pause" (default, extended description),
"over" (sound at 35%), "off"; D cycles. `Reader` uses NSSpeechSynthesizer
in-process on the Mac (`say` takes ~2.4 s to start with 442 voices), Prism's
OneCore/SAPI on Windows, or the screen reader with an estimated pause.
`MEDIA_DOWNLOAD_SILENT_SPEECH=1` mutes it for night tests. Me at the zoo: 23 s
from link to a 2-line description.

**Looking after the computer.** While anything downloads, the computer is kept
from sleeping (`system.keep_awake`: `caffeinate -i -w <pid>` on the Mac,
SetThreadExecutionState on Windows), so an overnight playlist finishes; a
setting turns it off. A download folder that can't be written (an unplugged
drive) is caught before anything is added, with Choose Folder offered. After
the lookup knows the size, a download too big for the free space fails at once
with both numbers (WAV and FLAC conversions counted at six times).

**Small things that are deliberate.** Windows come back where they were left
(`geometry.py`; a position on a missing display is ignored). The welcome uses
the account's first name (`words.first_name`). Help, About carries a running
tally (`app_stats`), and milestones (100th, 250th, 1000th...) are folded into
the "Done" sentence already being said, never a message of their own: the
`ytdl` rule that character lives in wording that was going to be said anyway.
Windows Alt letters in the main window must be unique; `check.sh` fails on a
repeat (Filter and Retry both had R until 2.4.2).

**Trying again by itself** (`Manager._try_later`). Network trouble or a 5xx
waits 15 s then 60 s (`net_retries`, at most 2). A 429 pauses the whole site
(`site_pause`) for 5, 10, then 15 minutes and announces it once; jobs wait
with `not_before`, a timer pumps when the earliest wait ends, and a hand
Retry clears the site's pause. Only after these does the engine-update retry
run, then failure.

**Transcripts** (`words.srt_to_text`, `worker.make_transcripts`): captions
fetched as for subtitles, each line kept once (YouTube's rolling captions repeat
every line), paragraphs at pauses over 2.5 s or about 70 words; the .srt is
deleted unless subtitles were also asked for; no captions means a note.

**Apple Podcasts show links** go through the iTunes lookup API to the show's
RSS feed (`worker.podcast_feed`); single episodes (`?i=`) go to the engine.

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
    .venv/bin/python tools/train.py WORKDIR [--only NAME...]  real-world matrix: 19 links and options at once, each result checked
    .venv/bin/python tools/time_play.py WORKDIR FILE cold 5   how long Play takes, in the real event loop
    .venv/bin/python tools/make_icon.py         redraw assets/icon.*
    .venv/bin/python tools/release_mac.py vX.Y.Z  sign, notarize, staple, replace the Mac zip, attach the signed appcast

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
9. **Every download has its own temporary folder** (`Job.tmp`, kept across
   Stop and Retry so a retry resumes, deleted when it finishes or the row is
   removed). One shared folder let the same video in two formats at once
   overwrite each other's partial files.
10. **yt-dlp reports only the main file.** Chapter files and subtitles are found
   beside it afterwards (same name start, written during this run).
11. **Never destroy the player window while the app runs.** wxWidgets' Mac
   media backend crashes (segfault in `QueuePauseEvent`) when AVFoundation
   sends a late notice to a destroyed media control: close-and-reopen crashed
   every time. Closing hides it; the app's own quit calls `shutdown()`, which
   stops and lets those notices drain for half a second first.
12. **Never time media with a loop of `wx.SafeYield()`.** It disables and
   repaints every window on each call, and that starves AVFoundation: a first
   Play that really takes **0.4 s** measured 7 to 27 s that way, and a whole
   night (2026-10-12/13) went on explaining slowness that wasn't there (blamed
   on coreaudiod, on DASH streams, on the player). Time with
   `tools/time_play.py`, which uses the real event loop. Real numbers, Studio,
   2026-10-13: a local MP3 0.4 s; YouTube, SoundCloud and live radio streams
   1.5 to 2 s including finding the stream (one YouTube outlier, 13.8 s). The
   player's "Still getting ready" at 8 s and fresh-link retry at 30 s stay as
   safety nets; neither fires normally.
13. **AVFoundation reads YouTube's direct M4A (DASH) at twice its length** (38 s
   for 19). Streaming prefers HLS audio on the Mac, and the site's duration
   wins over the player's. (That DASH sometimes "never starts" was measured
   with the SafeYield harness above, so it isn't established.)
14. **wx sliders take keyboard focus only the Mac's way**: `system.mac_focus`
   (makeFirstResponder) and `mac_has_focus`; wx's SetFocus and FindFocus don't
   see them.
15. **Only files that exist at the end are reported**: the cover image is
   downloaded, embedded and deleted, and was once counted as a third file.
16. **curl_cffi must be inside the app** (pinned to yt-dlp's version, 0.16.0) or
   sites that check for a real browser turn the engine away; the self-test
   asks the frozen worker how many browsers it can pass as.
17. **A slider says only its number** ("3") unless given a value description:
   `system.mac_value_description` sets what VoiceOver says ("3 seconds of 19
   seconds", "40 percent"). Any new slider needs one.
18. **On the Mac a window reads in the order its controls were created.** A
   field made before its label is heard before the label, and moving it in the
   tab order doesn't change that. `labelled()` takes the label made first.
19. **Menu shortcuts beat a focused text field on both systems.** Command-Delete
   (Ctrl-Backspace), Command-Down and Command-Shift-Up/Down are list commands,
   and they used to fire while typing in the Link field: Command-Delete there
   removed the selected download. `_typing()` makes those four do the editing
   instead when a field has focus. Any new shortcut that a text field also
   uses needs the same check.
20. **On Windows a label names, and its Alt key focuses, the next control
   *created*.** The list was made right after the Filter box, so it had no name
   and Alt-W went to Filter. Controls are created label-then-control even
   where the layout puts them elsewhere; `system.windows_name` names anything
   with no label before it (the progress bar).
21. **The app's sounds are files**, `assets/sounds/done.*` and `fail.*`: a Rhodes
   electric piano pair, rising for done and falling for failed, chosen by
   Matthew by ear on 2026-10-13 from four families (masters, candidates and
   the audition in iCloud, `Media Download Sounds`). MP3 on the Mac (afplay),
   WAV on Windows (winsound). Each is 10 ms of silence, a 3 ms fade-in, a
   150 ms fade-out and a 40 ms tail, leveled to -1.5 dBFS: the raw files
   started at full level and ended still sounding, which clicks. `_sound()`
   spaces them 1.4 s apart so a failure and the end of a batch don't play on
   top of each other. If the files are missing, the system's Glass and Basso
   play instead.
22. From the classic app, still true for the command: a GUI-launched process gets
   a minimal PATH; `--sub-langs "en.*"` earns HTTP 429; playlists need
   `--flat-playlist`; a named stream must never be converted.

## Tested

- **2.4.4** (2026-10-13): an independent read of the whole app for Windows and
  Mac faults found 14, all fixed with tests where wx allows: a "Just That One"
  playlist answer left stuck on "Looking up"; a finish never announced when
  another download in the batch was stopped; list shortcuts firing while
  typing; the list nameless on Windows; console windows flashing while a
  description is made; Windows paths in extra options losing their
  backslashes; player settings ignored until restart; paths too long for
  Windows; Details pointing at a playlist folder that didn't exist; focus left
  on a dimmed button; two announcements for one action; a closed More Options
  dialog crashing on a late answer; a closed player starting the next item by
  itself; Search adding duplicates and skipping the folder check. Downloads
  with no title yet are said by name ("a vimeo.com link"), never as a whole
  web address. `tools/train.py` 23 of 23 afterwards, and the real window
  driven with a good and a failing link.
- **2.4.3** sounds: each file's first and last samples are silent, there are no
  jumps in the first or last 10 ms, and the sound starts at 10 ms. Checked on
  the decoded MP3s as well as the WAVs.
- **2.4.0** (2026-10-13): audio description made end to end off-screen (Me at
  the zoo: described at 0.1 s and 12 s with the video paused for each, then it
  carried on); the sliders take focus with VoiceOver ("Position, 36 seconds of
  3 minutes 34", arrows step by the skip length; "Volume, 20 percent"); eight
  open-and-close cycles of the player and a clean quit without the crash.
- **Player, with VoiceOver** (2026-10-13, 2.3.2): Command-Shift-Return from the
  link opens it ("Loading: Player window, Play button"); T, Right, ], C, Space
  and Escape all work and speak. It found a **keyboard trap**: wx's Tab stuck
  on Speed because the volume slider refuses focus; the player now keeps its
  own Tab order (`PlayerFrame._tab`) and skips controls that won't take focus.
  And **AVFoundation reports YouTube streams at twice their length** (38 s for
  19 s): the site's duration wins (`item["duration"]`).
- Player off-screen and muted: files (Opus with captions, MP4), YouTube video
  with captions, SoundCloud, live radio (no site length = live), a whole
  archive.org album and a 355-episode podcast (feed or Apple show link) played
  as a queue, a dead link explained. A podcast feed used to take 3 minutes to
  fail as one item; the stream task now asks "is this a list?" first (0.9 s).
- `tools/train.py`, 23 of 23 (2026-10-13, 2.2.0): the 19 below plus a
  transcript, an NPR podcast feed, an Apple Podcasts show link and Spotify's
  DRM refusal.
- `tools/train.py`, 19 of 19 (2026-10-13): YouTube as best, MP3, FLAC, 720p
  H.264, a 5-second WAV cut, subtitles, chapters (9 files), youtu.be and YouTube
  Music links, an exact stream, an awkward file name; SoundCloud, Bandcamp,
  archive.org, a plain MP3 link; and four failures that must explain themselves
  (removed video, sign-in wanted, not media, bad extra options). Its first run
  found five real bugs.
- Load: 400 downloads through the window, slowest refresh 12 ms, six spoken
  tallies in two minutes.
- 50 tests (one hammers Stop and Retry; `test_gui_speech.py` pins the exact
  spoken sentences and needs wx) (`tests/`, fake worker, offline); CI runs them on
  Mac, Windows and Linux.
- Real downloads: YouTube to MP3, H.264 and AV1 video, a 5-second WAV cut,
  SoundCloud, archive.org FLAC, an archive.org playlist of 8 to MP3 (51 s at
  all cores against 171 s one at a time, 0 failures), a dead link explained.
- The frozen app's worker and engine probe; engine update from PyPI in a
  sandbox, including loading the newer engine over an older bundled one.
- Get Helper Tools for real (sandbox, 6 s, ~95 MB): ffmpeg 9.0.2, ffprobe,
  deno 2.9.7, each signature-checked; then a YouTube video downloaded with
  only those, Homebrew hidden.
- **First real Sparkle update** (2026-10-13): the Studio's 2.1.0 found 2.1.1 on
  GitHub, Install Update, Install and Relaunch, running 2.1.1 seconds later,
  Gatekeeper-accepted, signature intact. The MacBook (2.1.0) was left for
  Sparkle's own daily check to offer it; whether it did is worth a look.
- Sparkle rehearsal (2026-10-13), signed test copies 2.1.0 to 2.1.1 from a
  local feed: VoiceOver reads the window ("A new version of Media Download is
  available", the version sentence, the release notes as a list), Tab reaches
  the checkbox and all three buttons, Install Update is the default, Escape
  closes it. Install Update, then "Ready to Install", then Install and
  Relaunch: 2.1.1 running about 2 seconds later, signature intact.
- The self-updater, for real (2026-10-13): the Studio's 2.0.0 found 2.0.1,
  Install was pressed, and about 6 seconds later 2.0.1 was in /Applications,
  running, Gatekeeper-accepted, no old copy left behind.
- v2.0.1: the Windows self-test loads Prism inside the packaged app and lists
  NVDA, JAWS, ZDSR, ZoomText, System Access, UIA and others. It took two
  tries: the packager left out `_prism_cffi.pyd` until its folder was added by
  hand (`build_app.py`), and `load_prism()` loads it by path.
- v2.0.0: CI green on all eight jobs, Windows app built and self-tested on
  CI, Mac app signed, notarized, stapled, Gatekeeper "Notarized Developer ID".
  Installed on the Studio and the MacBook (self-test OK there; the MacBook has
  no Homebrew tools, so it is the realistic first-run case).
- VoiceOver on the installed app (2026-10-12): tab order and every name and help
  tag, a download by keyboard, Search, the playlist question and tick list,
  Escape, Command-J, Command-D, Command-E.

## Not done

- Audio description hasn't been heard by a person yet, and making one has only
  been tried on short videos. A long film would take many minutes and many
  Claude calls (60 moments at most).
- Windows can't play HLS, so YouTube video on Windows plays after downloading.

- **Windows has not been tried by a person.** Speech there goes through Prism
  (`prismatoid`, MPL-2.0, bundles NVDA's controller client, LGPL): the first
  running reader of NVDA, JAWS, ZDSR, System Access, ZoomText, Sense Reader,
  PC-Talker, BoyPC, else UI Automation notifications (Narrator). Never SAPI or
  OneCore, so nobody without a screen reader gets talked at. The order is
  unit-tested with a fake Prism and the Windows self-test checks Prism loads
  with a UIA backend, but no reader has heard it yet. NVDA is the first to try.
- The Windows build is unsigned, so SmartScreen warns once.
- `.opus` still has no default app on Matthew's Mac, and "best" is often Opus.
  One Get Info, Open With, Change All on any `.opus` file settles it.
