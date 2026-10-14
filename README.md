# Wavelength

**Wavelength finds, plays and saves audio and video from about 1,750 sites. It works the same whether you look at it or listen to it.**

YouTube, Bandcamp, SoundCloud, Vimeo, the BBC, archive.org, Mixcloud, podcasts, and plain links to a media file. Search them without a browser, play them without downloading, keep the ones you want, hear audio description for video, and open your own likes and playlists through the sign-in your browser already has. Nothing plays or downloads on its own.

It was called Media Download until version 3.0. Updating keeps everything: your list, settings, sounds and permissions.

What's here:

- **Wavelength**, an app for Mac and Windows
- **`ytdl`**, the same downloader as a command that talks in whole sentences
- **`ytdescribe`**, audio description for a video (at the end)

## Get the app

**Mac:** download `Wavelength-mac.zip` from the [latest release](https://github.com/Matthew2244/wavelength/releases/latest), open it, and drag Wavelength into Applications. It's signed and notarized by Apple, so it opens without a warning.

**Windows:** download `Wavelength-Setup.exe` from the same page and run it. It installs just for you, with no administrator password, adds Wavelength to the Start menu, and can be removed from Settings, Apps. Windows may say it doesn't recognise the app; choose More info, then Run anyway. (`Wavelength-windows.zip` is there too, if you'd rather not install anything.)

The app updates itself, with [Sparkle](https://sparkle-project.org) on the Mac and its twin WinSparkle on Windows: once a day it checks, shows what's new, and offers Install Update, Remind Me Later or Skip This Version (Help, Check for App Updates asks right away). Every update is signed, and the app refuses one that isn't, so nobody but the author can push an update to you. (The zip version on Windows updates itself in place instead.) The download engine inside the app, [yt-dlp](https://github.com/yt-dlp/yt-dlp), keeps itself current too, without waiting for a new app.

On first launch it checks for three helper tools: ffmpeg (converting), ffprobe (inspecting files) and deno (YouTube needs it). If you already have them, from Homebrew for example, it uses yours. If not, it offers to fetch them once, about 100 MB, into its own folder.

## Using the app

![The Wavelength window, in dark mode. Its title says Wavelength: 3 downloading, 1 waiting, 44 percent. At the top, a Link field holding a SoundCloud link, with Download, Play Link and Search buttons. Below it, Format set to Best audio, as the site sends it, and Video quality, greyed out until Video is chosen. Then Saving to: Downloads > Media Downloads, with a Change Folder button, and Next download: no extra options, with a More Options button. A Filter search field sits beside the Downloads label. The Downloads list shows seven rows, each starting with its status: two Done, two Downloading with percent and time left, one Adding cover art, one Waiting, one Failed with the reason. Below the list, Details for the selected row: title, status, channel, length, format, site, how much has arrived and the speed. At the bottom, Play Selected, Open, Show in Finder, Stop, Retry and Remove from List buttons, and an overall progress bar.](assets/screenshot.png)

1. Paste a link into the Link field and press Return (Enter on Windows), or drag links onto the window. Paste several at once and each gets its own row.
2. Or type some words and press Return or Enter to search YouTube, SoundCloud or YouTube Music. Check the results you want.
3. Choose a format before you add the link. "Best audio, as the site sends it" never converts anything. MP3, M4A, Opus, WAV and FLAC convert. Video saves an MP4 that plays everywhere unless you ask for higher than 1080.

Each row says its status first, then the title: "Downloading, 45 percent, about 2 minutes left: Green Onions". A long title gets cut off at the end of a row, so the part you need comes first. Select a row and Details below says everything known about it, including where the file went or, if it failed, why, in a plain sentence.

A link to a playlist or album asks whether you want all of it, some of it (check the ones you want), or just the one item the link pointed at. Each item gets its own row, numbered, in a folder named after the set.

**More Options** sets things for the next download only: just a section (from 1:30 to 3:45), one file per chapter, English subtitles, a text transcript, a browser's sign-in for members-only or age-checked videos, an exact stream chosen from a list, a file name, or any raw yt-dlp option.

**Transcripts.** "Also save a text transcript" turns the captions into plain paragraphs you can read, search or send to a braille display. YouTube's automatic captions repeat every line two or three times as they scroll; the transcript has each line once, with a new paragraph at each pause. If something has no captions, it says so.

**Podcasts.** Paste a podcast's RSS feed, or an Apple Podcasts show link, and you get its episodes to check. A big set starts with nothing checked, so picking three of 400 episodes doesn't mean unchecking 397.

**When things go wrong, it sorts itself out where it can.** A dropped connection or a server hiccup tries again by itself, after 15 seconds and then a minute. When a site says "too many requests", every download from that site waits a few minutes, the row says when it will try again, and it carries on without you, so a long playlist can finish overnight. When a site wants you signed in, select the row and choose Retry Using a Browser's Sign-in: it borrows the sign-in from the browser you choose, and remembers which. If the browser's sign-in can't be read at all (Chrome open on Windows, say, or Safari without Full Disk Access), the download tries once more without it and tells you. Spotify, Apple Music and Netflix use copy protection (DRM), and the app says so plainly rather than looking broken.

**When things were uploaded.** Every search result, playlist item and described version says when it was uploaded and how many have watched or listened: "uploaded March 4, 2024, 402 thousand views". YouTube's lists only say "2 years ago", so those read "uploaded about 2 years ago". For the exact date, right-click a result and choose Look Up Exact Date and Details (Command-I in Search, Control-I on Windows). Select a download and Details has the exact date too. Search's **Order** menu sorts the results you've loaded: newest first, oldest first, most viewed, longest or shortest. What you've checked stays checked.

**Search keeps going.** It shows 25 results, and the next 25 load by themselves when you reach the end of the list, for as long as the site has more. More Results (Command-Shift-M, or Control-Shift-M on Windows) does the same.

**Right-click menus** are on every list: the downloads, search results, a playlist's items, the player's queue and audio description. With VoiceOver, press VO-Shift-M. On Windows, press Shift-F10 or the Menu key. Command-K (Control-K on Windows) opens the same menu from the keyboard. Each menu only lists what makes sense for that row: Play, Open the Web Page, Copy Link, Copy Title, Download Again As another format, Download This One Now while Search stays open, Everything from This Channel, Check from Here to the End, and more.

**Sounds.** The app plays a sound for each thing that happens: opening, finished, failed, one of several finished, added, stopped, trying again by itself, search results, nothing more found, copied, an update ready, the end of the player's queue, and closing. It comes with four sets: a Rhodes electric piano (the default), a kalimba, pizzicato strings made from [Kenney's Music Jingles](https://kenney.nl/assets/music-jingles), and soft clicks from [Kenney's Interface Sounds](https://kenney.nl/assets/interface-sounds). Kenney's packs are CC0, free for anyone to use. Settings, Sounds picks the set, and a slider sets how loud they are (all the way down is silent); Play a Sample plays one. **Choose Sounds** lists every action. For each, pick any sound from any set, a sound file of your own, or no sound at all. **Import a Sound File** takes MP3, WAV, AIFF, M4A, FLAC, Ogg and more, and copies it into the app's own folder. Nothing plays by itself while you choose: press Play, or Return (Enter on Windows). That way a sound never talks over your screen reader. Each action has its own sound, so you can tell them apart by ear.

A few more are there just for fun, the same in every set: a bell when you finish the welcome tour, a little fanfare at your 100th, 250th and 1,000th download, a chime when a browser's sign-in checks out, and a little sound when Settings are saved. They're in Choose Sounds like the rest.

**Bigger Text** (Command-Plus, or Control-Plus on Windows) reaches every window: Search, Settings, the player, every dialog and the status bar. Each section of Settings scrolls when it's taller than the screen, with Save and Cancel always in view. The player grows to fit its controls instead of cutting them off.

**Your accounts.** In Settings, choose the browser you're signed in with, under Use a browser's sign-in. From then on every download, search and stream borrows that sign-in, so members-only, private and age-checked things work on any site that has them. Wavelength never asks for a password and never keeps one: the download engine reads your browser's sign-in when it needs it, and sends it only to the site it belongs to.

**File, Your Accounts** (Command-U, or Control-U on Windows) opens the things that only exist when you're signed in: YouTube's Liked videos, Watch Later, new from your subscriptions, your playlists and history; YouTube Music's liked music; and your SoundCloud likes, tracks and playlists. Open one as a list to check what to download, or play it all. Check Sign-in tests it and says plainly what's wrong if something is. If your browser is signed in to Google but not to YouTube itself, sign in at youtube.com in that browser.

On a Mac, reading **Safari's** sign-in needs Full Disk Access for Wavelength (System Settings, Privacy & Security, Full Disk Access). The app tells you and offers to open that page. Chrome and the others ask once for permission to use their stored key.

**A long list** can be filtered: type in Filter (Command-Shift-F, or Control-Shift-F on Windows) to show only rows containing those words, like "failed" or part of a title. Escape shows everything again.

Downloads go to **Downloads > Media Downloads** on your computer until you choose somewhere else with Change Folder. While anything is downloading, the computer won't go to sleep (so an overnight playlist finishes; Settings can turn that off). If the folder isn't there, say on a drive that's unplugged, or a download won't fit on the disk, it tells you before starting.

While anything is downloading, the Dock icon shows how many (on Windows, the taskbar button shows progress), so you can see it from another app.

**Quitting** while something is downloading asks first. Whatever didn't finish comes back next time, stopped, and Resume Unfinished picks up where it left off.

### The player

Wavelength plays things too: what you've downloaded, and links you haven't.

- **Play a link without downloading it.** Paste it and press Play. YouTube video comes with picture, sound and captions; SoundCloud, podcasts and plain audio links play as audio; live radio and live streams play live. In Search, Play Selected lets you hear a result before deciding to keep it.
- **Play a whole album, playlist or podcast without downloading:** paste the link and press Play, and its items play in turn.
- **Play what you've downloaded:** select a row and press Play (Command-P, or Control-P on Windows), or Play All Finished (Command-Shift-P, or Control-Shift-P) to queue everything. Download This keeps a copy of something you're streaming.
- **By keyboard:** Space plays and pauses. Left and Right skip back and forward (10 seconds, or what you choose in Settings), with Shift for a minute. Command-Left and Command-Right change item (Control-Left and Control-Right on Windows). [ and ] change speed, from a quarter to three times, without changing pitch, and backslash puts it back to normal. Command-Up and Command-Down change the volume (Control-Up and Control-Down on Windows; with Shift, in small steps), M mutes and unmutes, and V says the speed and volume. T says the time ("12 seconds of 19 seconds. 6 seconds left."). C turns captions on and off. D changes how audio description is read. Escape closes the player. All of it is also in the Playback menu.
- **From any window:** the Player menu in the main window and Search controls the player without going to it, with the same keys in every window. On Windows they're different from the Mac's, because Control-Alt with an arrow can rotate the screen there and Control-Alt with some letters types characters on many keyboards.

  | Does | Mac | Windows |
  |---|---|---|
  | Play or pause | Command-Option-P | Control-Alt-P |
  | Previous, next item | Command-Option-Left, Right | Control-Alt-Page Up, Page Down |
  | Back, forward | Command-Option-Comma, Period | Control-Alt-Home, End |
  | Louder, quieter | Command-Option-Up, Down | Control-Alt-U, D |
  | Mute or unmute | Command-Option-0 | Control-Alt-K |
  | Faster, slower | Command-Option-], [ | Control-Alt-Period, Comma |
  | Normal speed | Command-Option-Backslash | Control-Alt-N |
  | Say the time | Command-Option-T | Control-Alt-T |
  | Say the speed and volume | Command-Option-V | Control-Alt-V |

- **It picks up where you stopped** in each item, so a long podcast, lecture or audiobook carries on next time. A **sleep timer** (15 minutes to an hour, or the end of the item) fades out and pauses.
- **Captions** show in large type under the picture, from subtitles you downloaded or the stream's own.
- Nothing is spoken unless you ask (T), a new item starts while the player is in the background, or the queue runs out. Speed, volume and where you put the window are remembered.

Windows plays MP4 and M4A streams; video from sites that only offer the Mac-style streaming format plays after downloading.

### Audio description

Select a download, or put a link in the Link field, and choose Audio Description (Command-Shift-A, or Control-Shift-A on Windows; it's also in the player's Playback menu). It looks, in order of how far each can be trusted:

1. **A described track on the video itself**, written by a person. Play it or download it.
2. **A described version someone has published**, usually on YouTube. Only candidates that share a real word with the title are shown, and you choose.
3. **Make one**, when there's nothing else. Claude reads the picture at each change of shot and writes what it sees, with continuity ("he turns to the camera"). It takes about a minute for a short video, runs in the downloads list like any download, and is saved beside your downloads as a text file you can read and a timed file the player uses. It's labelled everywhere as machine-made and unchecked. Making one needs the [Claude command-line tool](https://claude.com/code); without it, the first two still work.

**The player reads description at its moment.** By default it pauses the video while reading (extended description, so nothing is talked over); it can also read over the video with the sound lowered, or not at all. Press D to change it. Space while a description is being read skips the rest of it. It reads with the system voice, so it knows exactly when to carry on, or with your screen reader, in your own voice and rate (Settings). Sighted people see each description on screen as it's read.

### With a screen reader

Built with wxPython, so every control is the system's own and VoiceOver, NVDA, JAWS and Narrator read it natively. Every control has a spoken name and a help tag.

- Finishes and failures are spoken as they happen, without moving focus. A big batch, like an album, becomes a short tally ("12 of 40 done") at most every 20 seconds rather than forty separate announcements. Failures are always named.
- Progress isn't spoken unless you ask for it in Settings (every 10, 30 or 60 seconds).
- Command-J (Control-J on Windows) says what's happening right now: how many are downloading, waiting, done and failed.
- The list and Details never jump under you. A row's text changes in place, and Details only rewrites itself while you're reading it when something real happens, never for a percentage.
- On Windows the same messages are spoken through whichever screen reader is running: NVDA, JAWS, ZDSR, System Access, ZoomText and others, or Narrator through UI Automation. That's done with [Prism](https://github.com/ethindp/prism). With no screen reader running nothing is spoken, so a sighted person is never suddenly talked at. Everything spoken also appears in the status bar.

### With low vision

View, Bigger Text (Command-Plus, or Control-Plus on Windows) makes the link field, the list, Details and every label larger, up to 48 points, and it's remembered. Command-0 (Control-0) goes back to normal. Colors follow the system, including Increase Contrast and dark mode. Status is always written in words, never shown by color alone.

### Keyboard

Everything is in the menus with its shortcut, and Help, Keyboard Shortcuts lists every one in the words your system uses.

| Does | Mac | Windows |
|---|---|---|
| Download the link, or search if it's words | Return in the Link field | Enter in the Link field |
| Search | Command-F | Control-F |
| Download every link on the clipboard | Command-Shift-V | Control-Shift-V |
| Download the links in a text file | Command-O | Control-O |
| Go to the Link field, the Downloads list, Details | Command-L, Command-D, Command-E | Control-L, Control-D, Control-E |
| Say what's happening | Command-J | Control-J |
| Filter the list | Command-Shift-F | Control-Shift-F |
| Play the selected download | Command-P | Control-P |
| Play everything finished | Command-Shift-P | Control-Shift-P |
| Play the link without downloading | Command-Shift-Return | Control-Shift-Enter |
| Audio description: find it, or make it | Command-Shift-A | Control-Shift-A |
| Your accounts | Command-U | Control-U |
| Open the file | Return in the list, or Command-Down Arrow | Enter in the list, or Control-Down Arrow |
| Remove the row (the file stays) | Delete in the list, or Command-Delete | Delete or Backspace in the list, or Control-Backspace |
| Show the file | Command-R (in Finder) | Control-R (in File Explorer) |
| Stop, Stop All | Command-Period, Command-Shift-Period | Control-Period, Control-Shift-Period |
| Retry | Command-Shift-R | Control-Shift-R |
| Move a download up or down the queue | Command-Shift-Up and Down | Control-Shift-Up and Down |
| Clear finished downloads from the list | Command-Shift-K | Control-Shift-K |
| The selected row's menu | Command-K, or VO-Shift-M | Control-K, Shift-F10 or the Menu key |
| Go to the downloads window, the player | Command-1, Command-2 | Control-1, Control-2 |
| Text size: bigger, smaller, normal | Command-Plus, Command-Minus, Command-0 | Control-Plus, Control-Minus, Control-0 |
| Settings | Command-Comma | Control-Comma |
| Next or previous section in Settings | Control-Tab, Control-Shift-Tab | Control-Tab, Control-Shift-Tab |
| Close the window, quit | Command-W, Command-Q | Control-W, Control-Q |

You can also drop links, a text file of links, or a web location onto the window, or on a Mac onto the Dock icon.

Help, About keeps a running tally of what you've downloaded ("Since October 13, 2026: 214 downloads, 18.3 GB, about 41 hours of listening and watching"), and the hundredth, thousandth and so on get a quiet mention in the "Done" sentence that was being said anyway.

### Settings

Settings comes in five sections, listed on the left. Up and Down Arrow choose one, Tab goes into it, and Control-Tab moves to the next section from anywhere in the window, Control-Shift-Tab to the one before (Control on both systems, not Command). Changing section never moves you out of where you are. Every setting has a help tag that says what it does.

- **General:** offering a link you've copied when you switch to the app (also when you open it), spoken progress, and keeping the download engine up to date.
- **Downloads:** downloads at once (automatic is half your computer's cores, between two and eight), how many from the same site at once (three, so sites don't start refusing), pieces fetched at once within one download, a speed limit for shared or slow connections, cover art for audio files, and keeping the computer awake.
- **Sounds:** the sound set, the volume, a sample, and Choose Sounds.
- **Player:** how far Left and Right skip, playing the next item, remembering where you stopped, captions, and how audio description is read.
- **Signing In:** which browser's sign-in to borrow.

The format, quality and folder in the main window are remembered too, and shared with the `ytdl` command.

### Fast on a big computer

Every download runs in its own process, so several download and convert at once on separate cores. One that crashes can't take the window with it, and Stop is immediate. On a 20-core Mac Studio, eight songs from an archive.org concert converted to MP3 in 51 seconds, against 171 seconds one at a time. Long videos also arrive in several pieces at once.

When a download fails in a way a newer engine might fix, the app checks for one, updates, and tries once more by itself.

## The command line: `ytdl`

The same downloader, for a terminal.

```bash
git clone https://github.com/Matthew2244/wavelength.git
cd wavelength
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
which shows every episode in a list you select from. Selecting beats typing a range of
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

Downloads default to Downloads > Media Downloads on the computer itself.
`ytdl --setup` offers iCloud Drive and others; `ytdl --set-default --to ~/Music` changes it
for good; `--to` changes it for one run.

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

`tools/train.py` downloads a matrix of real links and options all at once and checks every result: run it after anything that touches downloading. `tools/screenshot.py` has the window draw itself into a PNG, at any text size, with no screen capture. `tools/drive.py` runs the real window through real downloads off-screen and prints every row and every spoken message, so the wording can be checked by reading it. Releases: tag `vX.Y.Z` and GitHub Actions builds both apps; `tools/release_mac.py vX.Y.Z` then signs and notarizes the Mac one on a Mac holding the Developer ID.

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

`legacy/MediaDownload.applescript` is the first Wavelength: a chain of AppleScript dialogs over the `ytdl` command. It still compiles (`check.sh` makes sure) for anyone who prefers it:

    osacompile -o "Wavelength (classic).app" legacy/MediaDownload.applescript

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
