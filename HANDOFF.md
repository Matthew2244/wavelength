# Handoff: ytdl-accessible (Wavelength, ytdl, ytdescribe)

Read this before changing anything. It describes the current state. `CLAUDE.md`
in Matthew's private notes has the `ytdl` and `ytdescribe` reasoning.

## The name: Wavelength (since 3.0.0, 2026-10-13)

**The repo is Matthew2244/wavelength** (renamed from ytdl-accessible the same day, at
Matthew's word). GitHub redirects every old address, release downloads included:
verified that the old appcast URL answers 301 to the new repo and serves 3.0.0, so
copies built with the old feed URL keep updating. **Never create a new repo called
ytdl-accessible**: it would end that redirect. The local checkout is still
`~/ytdl-accessible` (the `ytdl` symlinks point into it); only the remote changed.
`wx.Config` stays **"Media Download"**: it holds window places and the text size, and
renaming it with the app would have quietly reset someone's Bigger Text.

Matthew renamed it ("this grew into something bigger"). Everything people see says
Wavelength: windows, menus, messages, `Wavelength.app`, `Wavelength.exe`, the installer,
`Wavelength-mac.zip` / `-windows.zip` / `-Setup.exe`. **Deliberately unchanged:**
the bundle id `io.github.matthew2244.mediadownload` (Sparkle keeps updating old copies,
and Full Disk Access granted to the old name still applies), the Windows installer
AppId (an update replaces the old install; `[InstallDelete]` removes the old exe and
shortcuts), the `media_download`
package, the `MEDIA_DOWNLOAD_*` test variables, and the **Media Downloads** folder
(nobody's files move). Old copies move over by themselves: `engine._move_old_folders`
renames the support and cache folders once, and `update.rename_old_bundle` renames a
Sparkle-updated `Media Download.app` to `Wavelength.app` after it quits (never while
running: its files would vanish from under it). No Windows zip copies existed, so the
old zip updater got no bridge. Verified on the Studio 2026-10-13: the real
`Media Download` support folder (12 MB: list, engine) became `Wavelength`, with no copy
left behind. The MacBook's moves on its first launch.

## What exists

| thing | where | note |
|---|---|---|
| Wavelength (the app; Media Download until 3.0) | `media_download/` | wxPython, Mac and Windows; installed at `/Applications/Wavelength.app` on both Macs |
| `ytdl` | `ytdl` | the command; `~/bin/ytdl` is a symlink into the repo |
| `ytdescribe` | `ytdescribe` | audio description; `~/bin/ytdescribe` likewise |
| classic dialog app | `legacy/MediaDownload.applescript` | the old AppleScript app, kept compiling for anyone who prefers it |
| public repo | [Matthew2244/wavelength](https://github.com/Matthew2244/wavelength) | MIT |

**Where it stands (2026-10-14):** 3.3.1 is the latest release (saving Settings no longer crashes the Mac app; Settings closes before its message on both systems). 3.3.0 (the main window takes links only; searching is the Search window's). 3.2.2 (every message that comes as a dialog closes is its own window; Escape and the close box on the tour's last step finish it). 3.2.1: Control-Tab really works on the Mac, What Is Wavelength?. 3.2.0 made the tour a conversation and added the settings_saved sound. 3.1.1 kept focus put when the section changes. 3.1.0 brought Settings in sections, help
tags everywhere, the opening and closing tunes and the ear candy, and two rounds of fixes
from reviews as other users (see Tested). Signed and notarized; both appcasts serve it, the
old ytdl-accessible feed address included (checked). Installed on the Studio and the MacBook
from the notarized zip (neither had the app open; verified 3.1.0, Gatekeeper "Notarized
Developer ID", self-test OK; 3.1.1 the same way). Matthew's standing word: push and release
every update without asking. Check `CFBundleShortVersionString` before assuming
for any later release. No person has tried the Windows build yet: NVDA first, then the
installer, WinSparkle and the sounds.

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
  check list, Search. `system.py` announcements (VoiceOver on the Mac, Prism on
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
`~/Library/Application Support/Wavelength/engine/<version>/`, proved by
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
(YouTube search, 50 results a look (`VERSIONS_PAGE`), Look Further reads the
next 50 with the `find_versions` task for as long as results come; kept only if
they share a distinctive word with the title, `rank_candidates`), then offers to make one: a `describe` job in the list
downloads a ≤480p copy (or uses the downloaded video), samples frames at shot
changes plus every 12 s of an unchanging shot (every one, no cap: Matthew lifted
the old 60 on 2026-10-13), and runs `claude -p
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
**Check `git log -1` shows the release commit before tagging.** On 3.0.1 a `git add`
naming ignored paths failed, the commit never happened, and the tag went up on the
previous commit: CI built a release still numbered 3.0.0, which became "latest" with no
appcast, so every update check 404'd until the release and tag were deleted and redone.
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
5. **VoiceOver re-reads a check-list row before the check lands**, saying
   "unchecked" right after you check it. The check lists announce the new count.
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
21. **The app's sounds are files, in themes**: `assets/sounds/<theme>/<event>.mp3`
   (Mac, afplay, with `-v` for Settings' volume) and `.wav` (Windows, winsound).
   Themes `rhodes` (default), `kalimba`, `pizzicato` (Kenney Music Jingles, CC0)
   and `soft` (Kenney Interface Sounds, CC0), each
   Kenney set with its `LICENSE-kenney.txt`, all in `CREDITS.md`; plus `system`
   (macOS sounds). **Only CC0 or Matthew's own sounds go in**: the repo is
   public, so every file in it is redistributed. Epidemic Sound was offered on
   2026-10-13 (a friend's account) and declined for that reason; Matthew chose
   more CC0 packs instead. `test_every_sound_set_is_complete` checks every set.
   Seventeen events, listed in `system.SOUNDS` with their words and system fallback:
   opening, done, failed, item_done, added, stopped, waiting, results, no_more, copied,
   update, queue_end, tour_done, milestone, signed_in, settings_saved, closing. **Ear candy** (Matthew,
   2026-10-14): `tour_done` (the welcome tour's last button, Let's Do This, first time or any time, a warm hand
   bell), `milestone` (the 100th, 250th, 1,000th download and on, a tiny bell fanfare, after
   the Done sound), `signed_in` (a browser's sign-in checks out, a two-tone chime) and
   `settings_saved` (stamp and music box, picked 2026-10-14 from six). Made
   with ElevenLabs sound effects and picked by him by ear from fourteen candidates
   (auditions in iCloud, `Media Download Sounds/Ear candy/`). They're the same in every set,
   kept once in `assets/sounds/shared/` (`sound_file` looks there after the set); originals
   in `tools/sound_sources/`, levelled with `tools/finish_sound.py`. New ear candy: generate a
   spread, let him choose, finish it, drop it in `shared/`, add it to `SOUNDS` and `SHARED`. **Opening and closing** (Matthew, 2026-10-13) play when the
   app starts (`startup_checks`) and once a quit is certain (`_closing_sound`, after any
   Quit Anyway question); they follow the set, volume and Choose Sounds like the rest. On
   Windows the closing sound holds the quit up to 2 s so it isn't cut off; on the Mac
   afplay runs in its own session and outlives the app. They're built by
   `tools/make_open_close_sounds.py` (kept, unlike the earlier scripts): different notes for
   each, not one figure turned round (his ask), then "even catchier", then a round of
   tunes written per instrument that he passed on. **Chosen 2026-10-14:** opening is a quick
   run D G B D, a "doo-dit" C D, and a ringing G chord (the opening files are kept exactly as
   he heard them; the script skips them, see `KEEP`). Closing answers it: the doo-dit turned
   round and walked down, D B, C A, B G, then a soft G chord. In the Rhodes key; kalimba
   plays them in B. About 1.2 and 1.45 s; they get 1.8 s before the next sound. Soft
   clicks uses Kenney's open and close, 4 dB down at his word. **Mix overlapping notes in float with headroom.** The first build mixed straight
   into 16-bit, clipped 1,355 samples of the Rhodes figure, then normalised, so every meter
   read clean; Matthew heard it at once. The script now mixes at half level in 32-bit float
   and sets the level on the true peak. **He hasn't approved the new ones yet**: audition in
   iCloud, `Media Download Sounds/Opening and closing sounds - audition.mp3`. `app_sound_map` gives any action its own sound:
   `""` the set's, `"none"`, `"<set>:<event>"`, or `"custom:<file>"` from
   `system.custom_dir()` (imported with ffmpeg to a 16-bit WAV; a missing custom
   file falls back to the set, never silence). 2.5's `app_sounds_off` still reads
   as "none" (`system.sound_map`). Volume is a 0 to 1 slider (`app_sound_volume`;
   0 is silent, so never `or 1.0`); Windows gets it through a quieter copy of the
   WAV (`_scaled_wav`, cached). **Nothing ever plays by itself after speech**
   (Matthew, 2026-10-13: "how will the app know when voiceover is done talking?
   Just make it a play button"): Choose Sounds and Settings play only on Play or
   Return. `system.cue(kind)` plays one from any window through the
   main window's `_sound`, which applies Settings (on/off, the set, volume,
   `app_sound_map`). The short ones play at once (item_done at most every 2 s);
   the long ones queue 1.4 s apart. Rhodes done/failed are the pair Matthew chose
   by ear on 2026-10-13 from four families (masters, candidates and
   the audition in iCloud, `Media Download Sounds`); they are held chords, not
   figures. The nine other Rhodes sounds are single notes pulled out of those
   chords and re-pitched (at most a fifth); kalimba is built from hark's kalimba
   notes. **Matthew hasn't heard the new ones yet**: auditions are in iCloud,
   `Media Download Sounds/themes/`, one file per set, each name spoken before
   its sound. The build scripts were in the session scratchpad and are gone; rebuild the same
   way if he wants changes. MP3 on the Mac (afplay),
   WAV on Windows (winsound). Each is 10 ms of silence, a 3 ms fade-in, a
   150 ms fade-out and a 40 ms tail, leveled to -1.5 dBFS: the raw files
   started at full level and ended still sounding, which clicks. `_sound()`
   spaces them 1.4 s apart so a failure and the end of a batch don't play on
   top of each other. If the files are missing, the system's Glass and Basso
   play instead.
22. **Never open a window over a modal one, and never make a window that
   borrows another's menu bar.** Search used to be a modal dialog; Play Selected
   raised the player over it, the modal kept the whole app's keyboard, and
   Command-Q, Command-W, the close button and every shortcut did nothing while
   Search sat unseen behind (Matthew, 2026-10-13). As a modeless *dialog* on the
   Mac it would have borrowed the last menu bar shown: Command-Delete in the
   results removing a download from the main list, Command-W closing the player.
   So Search is a `wx.Frame` with its own menus (File, Edit, View), and every
   window carries Quit, Settings and About so Command-Q works from any of them.
   Audio Description stays modal but closes before the player opens
   (`wx.CallAfter`). Command-1 is the downloads window, Command-2 the player,
   from anywhere. Any new window: its own menu bar, or modal and opening nothing.
23. **Right-click menus** (`menus.py`): `menus.attach(ctrl, build)` on every list.
   build() returns items for the selected row; disabled items are left out, not
   dimmed (by ear, "dimmed" lines only get in the way). A wx list on the Mac
   offers VoiceOver **no actions**, so VO-Shift-M did nothing:
   `system.mac_menu_action` adds AXShowMenu to the table view's class through the
   Objective-C runtime (verified: System Events lists the action and performing
   it opens the menu). Command-K opens the same menu in each window, and Windows
   gets Shift-F10 or the Menu key free. `MEDIA_DOWNLOAD_TEST_MENU_LOG=FILE` makes
   a menu write its items to FILE instead of opening, for tests driven over
   accessibility against the built app (`open -g -n --env ...`). A plain
   `python -m media_download` window shows no windows to accessibility at all;
   test those things on the built app.
24. **Upload dates** (`worker.when`, `words.uploaded`, `words.views`). `tool_flags`
   passes `--extractor-args youtubetab:approximate_date`, so YouTube lists and
   search carry a time worked back from "2 years ago": marked `approx` and read
   "uploaded about 2 years ago". SoundCloud and podcast feeds give exact dates;
   a probe gives an exact `upload_date`. YouTube Music's song search gives nothing
   (no date, no length): Look Up Exact Date and Details (Command-I, or the row's
   menu) probes one result and rewrites its row. YouTube's own "sort by upload
   date" (`sp=CAI%3D`) is ignored now, so Search's Order sorts what's loaded.
   The saved download list no longer stops at 500 rows.
25. **Welcome tour and Set Up Accounts** (`dialogs.Guide`). **It's a conversation** (Matthew,
   2026-10-14): the app talks as "I", and Next is labelled as your answer to each step
   (`Guide.NEXT`: Let's Go, Looks Good, Got It, Sounds Good...). The leave button is
   "I'll Take It from Here" in the tour, "Maybe Later" in Set Up Accounts (`Guide.LEAVE`),
   hidden on the last step; leaving the tour early gets a line in the main window saying Help,
   Welcome Tour brings it back. Keep new tour wording in that voice, light, never an extra step. Offered once to someone new
   (`app_onboarded`; anyone with downloads in `app_stats` is marked done silently), and
   any time from Help, Welcome Tour and File, Set Up Accounts. Each page's words sit in a
   read-only text box that takes the focus, so a screen reader reads the step on arrival
   (no timed announcements). Browsers come from `accounts.installed()`: every browser the
   engine supports that's on this computer, with profiles (Chrome-family `Local State`
   names, Firefox profile folders), the default browser first (LaunchServices on the Mac,
   UserChoice on Windows, xdg-settings on Linux). `permission_steps` and
   `settings_page_url` say what each system needs: Safari's Full Disk Access on the Mac,
   the keychain "Safe Storage" prompt for Chromium browsers on the Mac, closing the
   browser on Windows, where newer Chrome, Edge and Brave lock their sign-in (App-Bound
   Encryption) and Firefox is offered instead; `signin_check` counts cookies it couldn't
   decrypt and names the lock. **Lists and Your Accounts have no default action**
   (Matthew): Return presses nothing; Your Accounts offers Play All, Choose What to Play
   (a list whose main button plays) and Download only from its menu.
26. **Your accounts** (`accounts.py`, `dialogs.AccountsDialog`, Settings,
   Signing in). Browser sign-in only (`--cookies-from-browser`), never a
   password: `app_signin` makes `_job_from_ui`, search, stream, the player's
   list probe and find_description all carry it. Collections are plain URLs
   (`accounts.COLLECTIONS`), opened through `add_links` or `play_links` after
   the modal closes. Verified 2026-10-13: SoundCloud likes with Safari's sign-in
   (208 items); YouTube LL/WL/feeds refused because Matthew's Safari is signed
   in to Google but not youtube.com (no LOGIN_INFO or __Secure-3PSID cookies on
   .youtube.com), and the app says exactly that. **The installed app can't read
   Safari's cookies without Full Disk Access** ("Operation not permitted" on
   Containers/com.apple.Safari/.../Cookies.binarycookies, shown with
   `--signin-check safari OUTFILE` started by `open`, so macOS judges the app,
   not a terminal). A terminal-run python reads them fine, which proves
   nothing. The app tests a newly chosen browser at once (`signin_check`
   worker task) and offers the Full Disk Access page. **Never test with
   Chrome from a script**: reading its cookies raises a Keychain prompt on
   Matthew's screen. Vimeo likes (410) and Bandcamp collections (unsupported)
   are deliberately absent.
27. **Search has no ceiling** (Matthew, 2026-10-13: "I wanna make sure the app
   has no limits"). It used to stop at 25. Now it fetches a page of
   `SEARCH_PAGE` (25) at a time with `--playlist-items start-end`, and the next
   page comes from More Results (Command-Shift-M) or by itself on reaching the
   last row. Only an **empty** page ends it: YouTube repeats results between
   pages (a page often adds 15 to 24 new), so a page of nothing but repeats moves
   on by itself, and `next_start` counts positions fetched, not results kept.
   Deep pages get slower, because the engine re-reads the earlier pages (SoundCloud results
   101 to 125: 16 s). Nothing else caps results: playlists, feeds and albums
   expand whole, and the `ytdl` command's `--list-items` lists every item (it
   used to stop at 300; CrashCourse's 1,705 all listed). **No caps on results
   anywhere is a standing decision** (Matthew, 2026-10-13): where a search
   can't be unlimited in one go, it pages.
28. **The words are "check", "checked", "unchecked", never "tick"** (Matthew,
   2026-10-13): Download Checked, Check All, Uncheck All, "3 checked". The
   classic app's lists are selection lists, so it says "select" there.
29. From the classic app, still true for the command: a GUI-launched process gets
   a minimal PATH; `--sub-langs "en.*"` earns HTTP 429; playlists need
   `--flat-playlist`; a named stream must never be converted.

30. **Settings is in sections** (Matthew, 2026-10-13): General, Downloads, Sounds, Player,
   Signing In. A Sections list on the left (made first, so it reads first), the section
   beside it in a `wx.Simplebook`, each section scrolling on its own. Up and Down in the
   list choose; Tab goes in; Control-Tab and Control-Shift-Tab move section from anywhere
   (the real Control key, `RawControlDown`, on both systems). It reopens where it was left.
   **Changing section never moves focus** (Matthew, 2026-10-14): wx's page switch moves it to
   the new section's first control by itself, on both systems, so `show_section` puts it back;
   only focus on a control in the section being hidden goes to the Sections list.
   `test_choosing_a_section_never_moves_focus` covers the list, Control-Tab and
   Control-Shift-Tab without showing a window (a shown, focused test window takes the
   keyboard and VoiceOver from whoever is at the Mac).
   Every control in it has a help tag; `test_settings_sections` fails on one without.
   **Control-Tab says the section** ("Downloads, section 2 of 5."; Matthew, 2026-10-14).
   **On the Mac, Control-Tab never reaches a wx window.** Logged with real keys on 2026-10-14:
   Control and Shift arrive as key events, the Tab pressed with Control never does, not as
   EVT_CHAR_HOOK, not as EVT_KEY_DOWN, not through an AcceleratorTable. Something in AppKit
   takes it first. The fix is an app-wide NSEvent local monitor (`system.add_key_monitor`, a
   ctypes block), which sees every key the app receives before any window; Settings adds a
   handler while it's open and in front (`_on_mac_key`) and removes it in `Destroy`.
   **The native monitor is installed once and never removed** (3.3.1). Removing it crashed
   the app when Settings was saved with a real key press (Matthew, 2026-10-14; segfault in
   `-[_NSEventObserver dealloc]` from an autorelease pool drain): AppKit holds the observer
   in a copy of its monitor list for the key event, releases it later, and by then Python had
   freed the block it points at. Handlers come and go from a plain list instead. Faked keys
   and even zeroing the freed block did not reproduce it; only a real key press takes that path. The tests that
   passed before called `_on_key` directly, which skips AppKit: **a faked key event proves
   nothing about a real one.** Windows still uses `_on_key` (untested by a person).
   Saving Settings shows "Settings saved." as a message window (below) and plays
   `settings_saved` (shared ear candy, follows the volume, the set's on/off and Choose Sounds).
30a. **A message that must be heard before the window behind it is a small window of its own**
   (`dialogs.message`, Matthew, 2026-10-14). Speaking it as an announcement while a dialog
   closes put it after, or on top of, the screen reader reading the main window. Timing the
   close to the speech was tried and dropped: the app can't know anyone's speaking rate, and
   "not everyone has their screen reader set fast". The message's words sit in a focused
   read-only box (read on arrival, like the tour's steps); its one button answers it (his
   word: not always OK: "Great" for Settings saved, "Got It" for leaving the tour); Return
   and Escape close it. `MainFrame.tell_in_window` is the one way in. **Every message that
   comes as a dialog closes uses it** (his choice, 2026-10-14, knowing it costs a key press
   after each playlist add): Settings saved, leaving the tour, items added from a playlist or
   your accounts list, nothing added, the More Options summary, Retry Using a Browser's
   Sign-in, a new download folder, the helper tools and update answers. Announcements inside
   a window stay announcements. **Tests set `dialogs.message_log = []`** (the gui fixture does)
   so a message is recorded, never shown: a real one waits for a key press in front of
   whoever is at the Mac, and hung the test run once on 2026-10-14.
   On Windows the words are plain text and the button has the focus: NVDA and JAWS read only
   the caret's line of a text box, but read a new window's text by themselves.
   **Help, What Is Wavelength?** and the README's "What it is" say what the app is, what it
   won't do (DRM) and the legal position in plain words (`words.WHAT_IT_IS`; the tour's first
   step says the short version). Matthew approved the wording; keep them saying the same.
30b. **The main window takes links; the Search window searches** (Matthew, 2026-10-14, to make
   the two distinct). The field is just "Link". Words in it, with Return, Download or Play
   Link, or dropped text with no links, say `words.NOT_A_LINK` and open nothing; the words
   stay in the field, and Search (Command-F) takes them with it. The Search window's opening
   line says what it's for. Don't quietly bring back searching from the Link field.
31. **Help tags everywhere** (2026-10-13): every button, checkbox, popup, slider, field and
   list says what it does and its shortcut, checked against the bindings. Windows wording
   says Control and Enter. Keep it so: a new control needs a tip in the same voice.
   **The same goes for GitHub** (Matthew, 2026-10-14: "everyone shouldn't feel left out"):
   every key the README or a release note names gives the Windows key too. The README's
   keyboard tables have a Mac and a Windows column; the player's from-anywhere keys differ
   on Windows (`menus.PLAYER_KEYS`), so never write "read Control for Command" as a rule.
   All earlier release notes were brought into line the same day.
32. **The clipboard offer**: also at launch (a link copied before opening the app), never for
   a link already added or already in the list, an untouched earlier offer gives way to a
   newer link, it stays quiet if you've moved on while the link was being recognised, and
   when focus isn't in the Link field it says "Command-L, then Return".

## Tested

- **3.2.0 to 3.3.0** (2026-10-14, all with Matthew at the Mac): Control-Tab was found dead
  on the Mac with a key-logging copy of Settings and real keys (Control arrived, the Tab with
  it never did; an accelerator table didn't catch it either; an NSEvent local monitor did), and
  he confirmed the fix in the real app. He chose the order "speak, wait, then close" from four
  played back to back, then dropped timing altogether for message windows ("not everyone has
  their screen reader set fast"); he tried the message windows, the conversational tour and
  its leave button in the real app. A review agent read the whole day's diff: no crash or
  ctypes fault; four small bugs fixed in 3.2.2 (Escape dead on the tour's last step, the
  close box there counting as leaving, message windows clipping at Bigger Text, Settings
  holding up extra downloads). **Not tried by a person:** any of it on Windows (Control-Tab
  through `_on_key`, message windows with NVDA and JAWS), and 3.3.0's links-only Link field
  by ear.
- **Lesson:** a test that fakes a key inside the app skips AppKit, so it can pass while the
  real key never arrives. Keys the app handles itself need one real-key check.

- **3.1.0, second round** (2026-10-14): a review of the tour, accounts, the player and
  audio description. Fixed: **an unreadable browser sign-in no longer fails downloads**: the
  download goes once more without it and says so in its note (`Manager._without_signin`,
  `words.cookie_store_unreadable`); Retry by hand brings the sign-in back. That covers Chrome
  or Edge left open on Windows, Safari without Full Disk Access, and a denied Keychain prompt,
  whatever the tour or Settings chose. Sign-in explanations: the Mac Keychain case says what
  the prompt says ("security" asking for "<browser> Safe Storage", `accounts.keychain_name`),
  and "permission denied" only means the sign-in when the error is about cookies. Close,
  Escape and the close box in the tour keep the page's choice; Return on a step's text goes
  on; the permission step is skipped when nothing needs allowing; running the tour again with
  a sign-in set no longer says "No accounts". Open It in the Browser opens the chosen profile.
  The player: skipping during a description carries on playing; descriptions pick up from a
  resumed position; the sleep timer waits through a pause, ends when the player closes or a
  new queue starts, and refuses "end of this item" on live radio; a file that never starts
  is reported after 60 s. Audio description: a downloaded file can be described from the
  player (its link is kept as `page`); a failed lookup says why; Make needs ffmpeg as well
  as Claude and says which is missing; a signed-out Claude says so; stretches Claude didn't
  answer are named in the finished note. Windows wording says Enter. **Not yet tried by a
  person:** Return on the tour's step text with NVDA and VoiceOver, and whether reading a
  description on Windows stops early (`speech.Reader.speaking()` relies on Prism's backend
  having `.speaking`).
- **3.1.0, first round** (2026-10-13): Settings in sections, help tags everywhere,
  opening and closing sounds, and a review from other users' points of view. Fixed from it:
  a failed search no longer reads "Nothing found" or ends the paging (`SearchPage.error`);
  the closed player can't be started hidden from the Player menu; a normal quit now gets
  "N didn't finish last time", and Resume Unfinished resumes only what a quit cut off
  (`manager.CLOSED_EARLY`), never a row stopped by hand; an unwritable or unplugged download
  folder is explained and never waits on an engine update first; removing a running download
  asks first; Bigger Text grows the main window's controls on Windows and the main window
  and Search grow to fit; Windows screen readers hear the player's position and volume as
  words (`system._windows_value`, untried by a person). `tools/train.py` 23 of 23.

- **3.0.1** (2026-10-13): a full sweep by three independent reviews (screen readers
  on both systems; low vision, sighted and first run; bugs and the rename), about 40
  fixes. Among them: the Windows installer now really removes the old Media Download
  exe and shortcuts (the first try was skipped by an existing [InstallDelete]
  section); the bundle rename waits for any Sparkle install; settings write back only
  what the app changed (a `ytdl --set` made meanwhile survives); lookups time out at
  15 minutes; a worker that can't start says so; questions never pop up over another
  modal window; Bigger Text grows Windows controls too; long lines re-wrap
  (`WrapText`); windows fit a 1366x768 screen; Windows dark mode; Windows-safe player
  keys; the new icon (one bold wave). **Return decisions** (Matthew left them to the
  builder): Return opens the file in the downloads list and plays the item in the
  player's queue, like Finder and any playlist; the Guide's Next stays default. Lists
  that offer downloads or play-everything have no default.
- **3.0.0** (2026-10-13): renamed Wavelength; welcome tour and Set Up Accounts;
  every browser and profile; play-first Your Accounts; no default action in lists.
- **2.7.0** (2026-10-13): your accounts: browser sign-in for everything, File,
  Your Accounts, Check Sign-in, the Full Disk Access offer; a quick test of a
  newly chosen browser.
- **2.7.0** (2026-10-13): your accounts: browser sign-in for everything, File,
  Your Accounts, Check Sign-in, the Full Disk Access offer; a quick test of a
  newly chosen browser. `tools/train.py` 23 of 23 (one run before it was 22:
  a transient miss that wasn't captured).
- **2.6.1** (2026-10-13): player speeds a quarter to 3x (AVFoundation measured
  2.98x at 3.0, pitch kept), M mute (session only), V says speed and volume,
  Shift for small volume steps, and a Player menu (`menus.PLAYER_KEYS`,
  Command-Option keys) in the main window and Search, the same keys bound in
  the player. `check.sh` now catches a menu letter taking a control's Alt key
  (it missed "&Player" until its pattern was fixed).
- **2.6.0** (2026-10-13): Choose Sounds gives every action any sound, your own
  file or none; volume slider; steel, sax and retro removed. A full review for
  low vision, sighted and Windows users: Bigger Text in every window
  (`textsize.py`), Settings scrolls, the player grows to fit, Windows Alt keys
  no longer collide with the menu bar (`check.sh` now checks), OK and Cancel
  in Windows order, list names on Windows, finish times in Details, a drag hint.
  **Matthew tried it with VoiceOver the same day and all of it worked**: Tab
  into and out of the volume slider (read as a percentage), Choose Sounds with
  Play and Return, and importing his own sound file.
- **2.5.1** (2026-10-13): four more sound sets from Kenney's Music Jingles
  (pizzicato, steel, sax, retro). Matthew liked pizzicato and not the others;
  steel, sax and retro came out again in 2.6.0 at his word.
- **2.5.0** (2026-10-13): upload dates and views on every result, Order in
  Search, right-click menus everywhere (VO-Shift-M verified on the built app),
  three sound sets of eleven sounds, Settings, Sounds. Real lookups: a YouTube
  Music song with no date came back "10 seconds, uploaded February 4, 2015".
- **2.4.8** (2026-10-13): no caps left. Described versions: Encanto's trailer
  found 8 in the first 50 results (the old 10 found fewer), and Look Further
  ran on cleanly; `ytdl --list-items` listed all 1,705 of a channel; made
  descriptions keep every moment. "Tick" is "check" everywhere.
- **2.4.7** (2026-10-13): Search pages with no ceiling. Real searches on
  YouTube, SoundCloud and YouTube Music each returned results 101 to 125; an
  empty page ends cleanly; the real window went past 100 results with checks
  kept.
- **2.4.6** (2026-10-13): Stop now retires the run (`job.run += 1`): a quick
  Retry during a lookup used to let the killed lookup call the retry Failed
  (CI caught it once; `test_a_killed_lookup_never_fails_its_retry` catches it
  every time). 2.4.5 was tagged but never signed or offered; 2.4.6 carries it.
- **2.4.5** (2026-10-13): the stuck-window fix above. A real off-screen window
  with Search open and the player playing quits on Command-Q in 3 s with no
  window left; Command-W in Search closes only Search; Quit from the player's
  menu quits. An independent keyboard, NVDA, mouse and first-run read found the
  borrowed-menu and Audio Description faults, both fixed. Keyboard Shortcuts in
  Help is now read from the menus, so it can't fall behind them (it was missing
  more than a dozen).

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
  tag, a download by keyboard, Search, the playlist question and check list,
  Escape, Command-J, Command-D, Command-E.

## Not done

**Parked here on 2026-10-13 at Matthew's word**, with 3.0.1 on both Macs and the
family band trying it. Open threads, none started:

- **YouTube through Your Accounts hasn't worked end to end yet.** Matthew's Safari is
  signed in to Google but not youtube.com, and Wavelength has no Full Disk Access yet;
  both are his to do. SoundCloud likes worked with Safari's sign-in (208 items).
- **The welcome tour and Set Up Accounts haven't been tried with VoiceOver by a
  person.** Driven over accessibility in the built app: the step text takes focus and
  reads first, steps count right, Next and Close work.
- **Nobody has used the Windows build yet**, now including the installer's cleanup of
  the old name, the Windows player keys, dark mode and Bigger Text on controls.

- Audio description hasn't been heard by a person yet, and making one has only
  been tried on short videos. With no cap on moments, a two-hour film is
  hundreds of moments, so dozens of Claude calls and a long wait.
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
