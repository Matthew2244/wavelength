# ytdl-accessible

**Media Download saves audio and video from about 1,750 sites. It works the same whether you look at it or listen to it.**

YouTube, Bandcamp, SoundCloud, Vimeo, the BBC, archive.org, Mixcloud, and plain links to a media file. It saves the file where you tell it and never plays anything on its own.

What's here:

- **Media Download**, an app for Mac and Windows
- **`ytdl`**, the same downloader as a command that talks in whole sentences
- **`ytdescribe`**, audio description for a video (at the end)

## Get the app

**Mac:** download `Media-Download-mac.zip` from the [latest release](https://github.com/Matthew2244/ytdl-accessible/releases/latest), open it, and drag Media Download into Applications. It's signed and notarized by Apple, so it opens without a warning.

**Windows:** download `Media-Download-windows.zip` from the same page, unzip it anywhere, and run `Media Download.exe`. Windows may say it doesn't recognise the app. Choose More info, then Run anyway.

The app updates itself (Help, Check for App Updates). The download engine inside it, [yt-dlp](https://github.com/yt-dlp/yt-dlp), keeps itself current too, without waiting for a new app.

On first launch it checks for three helper tools: ffmpeg (converting), ffprobe (inspecting files) and deno (YouTube needs it). If you already have them, from Homebrew for example, it uses yours. If not, it offers to fetch them once, about 100 MB, into its own folder.

## Using the app

![The Media Download window. At the top, a Link field holding a SoundCloud link, with Download and Search buttons. Below it, Format set to Best audio, as the site sends it, and Video quality, greyed out until Video is chosen. Then Saving to: iCloud Drive > Media Downloads, with a Change Folder button, and Next download: no extra options, with a More Options button. The Downloads list shows seven rows, each starting with its status: two Done, two Downloading with percent and time left, one Adding cover art, one Waiting, one Failed with the reason. Below the list, Details for the selected row: title, status, channel, length, format, site, how much has arrived and the speed. At the bottom, Open, Show in Finder, Stop, Retry and Remove from List buttons, and an overall progress bar.](assets/screenshot.png)

1. Paste a link into the Link field and press Return. Paste several at once and each gets its own row.
2. Or type some words and press Return to search YouTube, SoundCloud or YouTube Music. Tick the results you want.
3. Choose a format before you add the link. "Best audio, as the site sends it" never converts anything. MP3, M4A, Opus, WAV and FLAC convert. Video saves an MP4 that plays everywhere unless you ask for higher than 1080.

Each row says its status first, then the title: "Downloading, 45 percent, about 2 minutes left: Green Onions". A long title gets cut off at the end of a row, so the part you need comes first. Select a row and Details below says everything known about it, including where the file went or, if it failed, why, in a plain sentence.

A link to a playlist or album asks whether you want all of it, some of it (tick the ones you want), or just the one item the link pointed at. Each item gets its own row, numbered, in a folder named after the set.

**More Options** sets things for the next download only: just a section (from 1:30 to 3:45), one file per chapter, English subtitles, a browser's sign-in for members-only or age-checked videos, an exact stream chosen from a list, a file name, or any raw yt-dlp option.

**Quitting** while something is downloading asks first. Whatever didn't finish comes back next time, stopped, and Resume Unfinished picks up where it left off.

### With a screen reader

Built with wxPython, so every control is the system's own and VoiceOver, NVDA, JAWS and Narrator read it natively. Every control has a spoken name and a help tag.

- Finishes and failures are spoken as they happen, without moving focus. A big batch, like an album, becomes a short tally ("12 of 40 done") at most every 20 seconds rather than forty separate announcements. Failures are always named.
- Progress isn't spoken unless you ask for it in Settings (every 10, 30 or 60 seconds).
- Command-J (Control-J on Windows) says what's happening right now: how many are downloading, waiting, done and failed.
- The list and Details never jump under you. A row's text changes in place, and Details only rewrites itself while you're reading it when something real happens, never for a percentage.
- On Windows, messages go to the status bar, where NVDA (NVDA+End) and JAWS (Insert+Page Down) read them. Spoken announcements there are on the list to do.

### With low vision

View, Bigger Text (Command-Plus) makes the link field, the list, Details and every label larger, up to 48 points, and it's remembered. Command-0 goes back to normal. Colors follow the system, including Increase Contrast and dark mode. Status is always written in words, never shown by color alone.

### Keyboard

Everything is in the menus with its shortcut. On Windows read Control for Command.

| Keys | Does |
|---|---|
| Return in the Link field | Download the link, or search if it's words |
| Command-F | Search |
| Command-Shift-V | Download every link on the clipboard |
| Command-O | Download the links in a text file |
| Command-L, Command-D, Command-E | Go to the Link field, the Downloads list, Details |
| Command-J | Say what's happening |
| Return in the list | Open the file |
| Delete in the list | Remove the row (the file stays) |
| Command-R | Show the file in Finder or File Explorer |
| Command-Period | Stop |
| Command-Shift-R | Retry |
| Command-Shift-Up and Down | Move a download up or down the queue |
| Command-Shift-K | Clear finished downloads from the list |
| Command-Plus, Command-Minus, Command-0 | Text size |
| Command-Comma | Settings |

You can also drop links, a text file of links, or a web location onto the window or the Dock icon.

### Settings

Downloads at once (automatic is half your computer's cores, between two and eight), how many from the same site at once (three, so sites don't start refusing), pieces fetched at once within one download, cover art for audio files, sounds, spoken progress, offering a link you've copied when you switch to the app, and keeping the download engine up to date. The format, quality and folder in the main window are remembered too, and shared with the `ytdl` command.

### Fast on a big computer

Every download runs in its own process, so several download and convert at once on separate cores. One that crashes can't take the window with it, and Stop is immediate. On a 20-core Mac Studio, eight songs from an archive.org concert converted to MP3 in 51 seconds, against 171 seconds one at a time. Long videos also arrive in several pieces at once.

When a download fails in a way a newer engine might fix, the app checks for one, updates, and tries once more by itself.

## The command line: `ytdl`

The same downloader, for a terminal.

```bash
git clone https://github.com/Matthew2244/ytdl-accessible.git
cd ytdl-accessible
./install.sh
```

That checks for [Homebrew](https://brew.sh), installs `yt-dlp` and `ffmpeg` if you don't have them, puts the commands on your PATH, and installs the app from the latest release. It never uses `sudo`, and if you need to do something yourself, like adding a folder to your PATH, it says so at the end.

To remove everything later: `./install.sh --uninstall`

Copy a link and run:

```bash
ytdl
```

`ytdl --setup` walks you through where downloads go and what format you want.

### Why the command exists

yt-dlp is excellent. Its **output** is the problem if you listen to your computer
rather than look at it.

The default progress display rewrites a single terminal line many times a second
using a carriage return. A screen reader re-announces on every write, so it spends
the entire download interrupting itself and never finishes a sentence. You get a
stream of noise, and no usable information.

`ytdl` runs yt-dlp with progress suppressed and prints **one line per event** instead:

```
Journey Uptown — Matthew Whitaker
6 minutes 42 seconds. About 8 MB.
Downloading...

Done. Saved to Media Downloads as Journey Uptown.opus (7.9 MB)
```

`--progress` adds a percentage line at most **every 10 seconds** — slow enough that
a screen reader can finish speaking it before the next one arrives.

Everything else here follows from the same idea: errors are sentences rather than
tracebacks, durations are "6 minutes 42 seconds" rather than `402`, and anything
that would need a glance at a progress bar is instead reported when it matters.

### What it needs

macOS and [Homebrew](https://brew.sh) for the command. The installer handles the rest. The app needs nothing.

`ytdescribe` additionally wants the `claude` CLI on your PATH to read the video
frames, and an ElevenLabs key in the Keychain as `elevenlabs-api-key` if you want
the description spoken. Both are optional — `ytdl` does not need either.

### Usage

```
ytdl                       URL from the clipboard
ytdl <url>                 your default format, into your default folder
ytdl <url> --info          what you would get, downloads nothing
```

**Settings**

```
ytdl --setup                 walk through every setting, one question at a time
ytdl --settings              show what is set
ytdl --set notify=yes        change one setting directly
```

`--setup` asks seven questions — where downloads go, default format, whether to
ping your phone, whether to announce progress, auto-update, browser cookies, and a
video height cap. Enter keeps whatever is already set, Control-C leaves without
saving. **A flag always beats a saved setting**, so nothing you save locks you in.

The first run mentions `--setup` exactly once, and only *after* a download has
already worked. A setup prompt standing between someone and their first file is the
fastest way to make a tool feel like homework.

**Choosing a format**

```
  --format KIND            best, m4a, opus, mp3, wav, flac or video
  --video --mp3 --wav      shorthand for the same
  --pick                   list the real formats and choose by number
  --list-formats           list them and stop
  --max-height 720         cap video height
  --format-id 251          an exact yt-dlp format id
  --set-default wav        remember a format, so you stop typing the flag
  --settings               show what you have saved
```

**Several at once**

```
ytdl <url> <url> <url>       several links, one after another
  --batch links.txt          a file of links, one per line
  --jobs                     what is downloading now, what just finished
```

They run in sequence rather than in parallel, which keeps sites from
rate-limiting you, and **one failure never abandons the rest** — the run reports
how many made it. `--jobs` works from anywhere, including while a download
started by the app is still going.

**Anything this does not cover**

```
  --yt-dlp="--write-thumbnail"    raw arguments straight to yt-dlp
  --yt-dlp-help                   every yt-dlp option there is
```

yt-dlp has roughly 200 options. Giving each one a wrapper flag would make
`--help` unreadable by ear — which is precisely the problem this tool exists to
solve. So the common ones are curated above and everything else passes straight
through. Full coverage, no bloat. (The equals sign is required: a value starting
with a dash looks like a flag to the argument parser.)

**Part of a video**

```
  --from 1:30              start there (also accepts 90 or 1:02:03)
  --to-time 3:45           stop there
  --chapters               also split into one file per chapter
  --subtitles              also fetch English subtitles as .srt
```

**Playlists**

```
  --playlist               the whole list, into its own numbered folder
  --list-items <url>       number every episode, so you can see what to pick
  --items 1-10             or 3,5,7 — just those
  --no-resume              re-fetch items already downloaded
```

In the app, a playlist link offers a third choice: **Pick the ones I want**,
which shows every episode as a tick list. Ticking beats typing a range of
numbers at something you cannot see, and it reads item by item under VoiceOver.
`--list-items` is the same thing on the command line — numbers are useless until
you can see what they refer to.

**Everything else**

```
  --sites bandcamp         is a site supported? (about 1,750 are)
  --to PATH                a different folder, just this once
  --name "..."             filename, without extension
  --progress               a percentage line every 10 seconds, no faster
  --cookies [BROWSER]      sign-in cookies, for "confirm you're not a bot"
  --notify                 Pushover ping on finish and on failure
  --quiet                  print the final path and nothing else
  --update                 upgrade yt-dlp now, and say what actually changed
  --no-auto-update         never upgrade yt-dlp on its own
```

Downloads default to `~/Library/Mobile Documents/com~apple~CloudDocs/Media Downloads`
(iCloud Drive). `ytdl --set-default --to ~/Music` changes that for good; `--to` changes
it for one run.

**`best` never converts; a named format sometimes must.** `--format best` keeps the
source codec, so a Bandcamp FLAC stays FLAC and an MP3 stays an MP3. Naming a format
(`m4a`, `mp3`, `wav`) guarantees the file type but converts when the source is not
already that codec — a lossy generation for the lossy ones. Measured on a plain MP3:
`best` kept it at 32 KB, `--format m4a` re-encoded it to 67 KB. Bigger *and* lossier.

**Nothing here ever opens a file.** Downloads are written and left alone, so whatever
app owns the format on your Mac is never launched. If double-clicking a download opens
something you don't want, that is macOS file association, not this tool — and
`--set-default` lets you pick a format whose association you're happy with.

## Working on it

```bash
python3 -m venv .venv && .venv/bin/pip install wxPython pyinstaller certifi "yt-dlp[default]" pytest pillow
.venv/bin/python -m media_download      # run the app from source
./check.sh                              # before every commit
.venv/bin/python build_app.py           # build the app for this computer
```

`check.sh` parses the Python, confirms every command-line option has help text, runs the tests and the app's self-test, and checks that every dialog closes with Escape and every control has a spoken name. It also still compiles the classic dialog app. It exits non-zero if anything fails. It exists because a broken build once got committed and pushed when an error scrolled past.

`tools/screenshot.py` has the window draw itself into a PNG, at any text size, with no screen capture. `tools/drive.py` runs the real window through real downloads off-screen and prints every row and every spoken message, so the wording can be checked by reading it. Releases: tag `vX.Y.Z` and GitHub Actions builds both apps; `tools/release_mac.py vX.Y.Z` then signs and notarizes the Mac one on a Mac holding the Developer ID.

## Design notes

The parts that are less obvious than they look.

**Part-files never touch the destination.** yt-dlp writes `.part` files, per-fragment
chunks, and separate audio and video streams that ffmpeg merges afterwards. Written
straight into a synced folder — iCloud Drive, Dropbox — every one of those syncs to
your other devices and is then deleted. yt-dlp solves this itself with split paths,
so `ytdl` uses `-P temp:` for a local scratch directory and `-P home:` for the real
destination. Only the finished file ever appears there.

**The default never re-encodes.** `-x --audio-format best` keeps the source codec and
only changes the container: AAC lands as `.m4a`, Opus as `.opus`. Preferring `.m4a`
for tidiness would give you the *worse* stream — YouTube's Opus is typically ~106 kbps
against the AAC's ~130 kbps, and Opus wins comfortably at that bitrate. `--mp3` and
`--wav` are conversions, and the help text says so.

**Playlist detection cannot key on `list=`.** That is a YouTube URL parameter, so a
Bandcamp album or a SoundCloud set sailed straight past the guard. Every other site
announces itself in the metadata instead, and YouTube is the one that does *not* —
`--no-playlist` collapses it to a single video before you can see it. So both signals
are checked. Error messages name the actual extractor too; blaming YouTube for a
Bandcamp failure is both wrong and confusing.

**`--info` asks yt-dlp what it would pick** rather than ranking the formats itself.
It passes the same `-f` selector the download will use into the `-J` call and reads
the selection back. An earlier version re-implemented the ranking and confidently
reported the 130 kbps AAC while the download quietly took the 106 kbps Opus.

**Playlists are refused unless asked for.** A URL copied from a queue carries `&list=`
on the end. Honouring that silently would drop a few hundred files on you. The count
comes from `--flat-playlist --playlist-items 0`, which reports `playlist_count`
without fetching the entries.

**A playlist must be listed flat, not extracted.** With `--playlist`, the metadata
call uses `--flat-playlist`. Without it, `-J` extracts every entry in full — for a
channel's uploads that is hundreds of round trips, and it simply times out before
anything downloads. Flat returns the list and its titles in one request and leaves
per-video work to the download itself.

**Partial playlist success is reported as partial success.** `--ignore-errors` keeps
yt-dlp going past a bad item, and it still exits non-zero afterwards. Treating that as
total failure would throw away news of every file that *did* arrive, leaving re-running
as the only way to find out. Each item is announced as it starts, an archive file beside
the downloads records what completed, and re-running the same command resumes rather
than starting over.

**`--sub-langs "en.*"` is a trap.** It looks like "any English track" and actually
matches every auto-*translated* variant YouTube offers — `en-de`, `en-fr`, and dozens
more. That is enough requests to earn an HTTP 429 instead of a subtitle file. The real
English tracks are named explicitly. `-i` goes with it, because subtitles are a bonus
and a bonus must never cost the download: without it, one failed subtitle fetch aborts
the run and you get no media at all.

**An exact format id is taken as it comes.** `--format-id 251` (Opus) once landed as a
fatter, lossier `.m4a`, because a *saved default* of m4a was still being applied on top
of the stream that had been explicitly named. A saved default must never silently
transcode a stream you went to the trouble of asking for; an explicit flag still wins.

**Auto-update is triggered by failure, not by a timer.** YouTube breaks yt-dlp
periodically, and the moment a newer version is worth having is the moment a download
fails. So that is the primary trigger: on a failure, if a newer release exists, `ytdl`
upgrades and retries once — turning "it failed, go update, try again" into one command
that just works.

Two guards make that safe to leave on. It only fires for failures an upgrade could
plausibly fix — a private, removed or members-only video will fail identically on
every version ever released, and spending a minute on `brew` to prove that is worse
than just saying so. And it only retries when the version genuinely moved, so a
Homebrew that has nothing newer costs you one no-op rather than a pointless second
attempt.

The secondary trigger is a once-a-day check **after a successful download**, so the
upgrade has usually already happened before a break can reach you. Neither check ever
runs *before* a download — nothing should stand between you and the file you asked
for. `--no-auto-update` turns both off.

**No age-based staleness check.** An early version warned when yt-dlp was more than
30 days old. But yt-dlp releases irregularly, so this called a perfectly current
install stale — the warning fired on every failure and pointed at `--update`, which
correctly replied "already up to date". Version comparison is against the GitHub
releases API, and **stays silent when it cannot reach it**: "could not check" and
"you are behind" must never look the same.

**The app exports PATH before doing anything.** A GUI-launched macOS app inherits a
minimal `PATH` of `/usr/bin:/bin:/usr/sbin:/sbin`, with no Homebrew in it — so yt-dlp
is invisible and every download fails while the identical command works fine in a
terminal. This is the classic way a working script dies as an app.

## The classic dialog app

`legacy/MediaDownload.applescript` is the first Media Download: a chain of AppleScript dialogs over the `ytdl` command. It still compiles (`check.sh` makes sure) for anyone who prefers it:

    osacompile -o "Media Download (classic).app" legacy/MediaDownload.applescript

## Optional: Pushover

`--notify` sends a [Pushover](https://pushover.net) notification on completion, and on
failure at priority 1 so it beats quiet hours. It shells out to a `pushover` script on
your `PATH` and **silently does nothing if you don't have one**, so this costs you
nothing if you don't use it.

If you do, note that Pushover rejects the *entire* notification for an unknown sound
name — so `notify()` retries without `--sound` rather than losing the message. Upload
custom sounds named `ytdl-done` and `ytdl-fail`, or edit those constants.

## License

MIT — see [LICENSE](LICENSE).

## `ytdescribe` — audio description

```
ytdescribe <url>              find or make a description
ytdescribe <url> --spoken     also render it as speech
ytdescribe <url> --mix        also mix that speech under the original audio
```

Three sources, in descending order of how much they are worth trusting.

**1. A descriptive audio track on the video itself.** Rare, but real human
description. Checked first, always, and across every metadata field that has carried
it — the shape differs by site and has changed more than once, and a missed track
means inventing description that a person already wrote.

**2. A separate video that IS the described version.** This is where audio description
actually lives on YouTube. Searching "audio described" turns up whole channels of them,
published as their own videos rather than as alternate tracks — which is worth knowing,
because looking only for alternate tracks finds almost nothing. You are shown the
candidates and pick one; a title match is not treated as proof.

**3. Generated, only when the first two come up empty.** Frames are sampled at *shot
changes* rather than on a fixed clock — a fixed interval either misses a cut or
describes the same shot five times. They are then read **in order and in batches**, so
the description has continuity and can refer back ("the same room") instead of being a
list of disconnected stills.

It is invented description, and **every file it writes says so at the top.** A
confident wrong description is worse than an honest gap.

The spoken mix **ducks the original rather than fitting the gaps.** Real audio
description goes strictly in the pauses, but choosing which line matters more than
which sentence of dialogue is an editorial judgement this cannot make. Ducking is the
honest compromise, and it is named as one.
