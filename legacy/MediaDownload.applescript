-- Media Download — a launcher for the ytdl command (found at launch, wherever install.sh put it).
--
-- Not YouTube-only: yt-dlp handles about 1,750 sites.
--
-- KEYBOARD. Command-Q and Command-W do nothing in an osacompile applet: the
-- bundle has no menu bar for them to bind to, and `display dialog` runs a modal
-- session that blocks menus anyway. Escape is the way out, and it behaves as
-- follows — measured, not assumed:
--
--   one button, set as BOTH default and cancel  ->  Escape does NOTHING
--   one button, set as cancel only              ->  Escape and Space work
--   two buttons, default and cancel different   ->  Escape and Return work
--
-- And separately, measured the same way: `choose from list` ignores Escape and
-- Command-period completely, even when the app is frontmost. Its Cancel button
-- is clickable but no key reaches it. So every list here also carries a plain
-- "Back" item, because a menu you can enter and not leave by keyboard is a
-- trap.
--
-- The first shape is the trap, and it is the obvious thing to write. Every
-- one-button dialog here therefore sets `cancel button` and no default.
--
-- Escape never closes the app. It means back or dismiss everywhere; on the
-- link box it does nothing, because there is nothing behind it. Quit is a
-- button press only, since Escape is easy to hit by accident.
--
-- WORDING. Buttons say what they do, so the body does not have to explain
-- them. Earlier versions listed every button with a description and became a
-- wall of text — costly when you are listening rather than looking. The long
-- explanations live in Help, once, where they can be read on purpose.
--
-- A GUI-launched app gets a minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin), so
-- Homebrew is invisible to it and yt-dlp would not be found. Hence the
-- explicit PATH on every shell call.

property shellPrefix : "export PATH=$HOME/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH; "
-- Resolved at every launch by locateYtdl(), never assumed. install.sh links
-- ytdl into whichever personal folder is on the PATH (~/bin on one Mac,
-- ~/.local/bin on another), so a fixed "$HOME/bin/ytdl" was wrong on any
-- machine but the one it was written on, and every setting change failed with
-- "No such file or directory".
property ytdlPath : ""
property appTitle : "Media Download"
property welcomeFlag : "$HOME/.config/ytdl/.welcomed"

on run
	if not locateYtdl() then return
	greetOnce()
	repeat
		try
			if not mainScreen() then exit repeat
		on error errText number errNum
			-- One `on error` per try — AppleScript allows no more — so the
			-- cases are sorted here rather than in separate clauses.
			if errNum is -128 then
				-- Escape that got past a closer handler. Never closes the app.
			else if errNum is -1712 then
				my tell_("That took too long and was given up on." & return & return & ¬
					"Nothing was damaged. If it was an update, try again — " & ¬
					"Homebrew is sometimes slow the first time.")
			else
				my tell_("Something went wrong:" & return & return & errText)
			end if
		end try
	end repeat
end run

-- An information dialog: one button, cancel-only so Escape and Space both work.
on tell_(theText)
	try
		display dialog theText with title appTitle buttons {"OK"} cancel button "OK"
	on error number -128
	end try
end tell_

on greetOnce()
	try
		do shell script "test -f " & welcomeFlag
		return
	end try
	try
		display dialog "I download things from the web so you can keep them." & return & return & ¬
			"Copy a link, open me, press Return twice. That's it." & return & return & ¬
			"About 1,750 sites work, not just YouTube. Several links at once are fine — put spaces between them." & return & return & ¬
			"I never open or play what I download." & return & return & ¬
			"Settings and Help are behind the Settings button. You'll only see this once." ¬
			with title "Hello from " & appTitle buttons {"Start"} cancel button "Start"
	on error number -128
	end try
	do shell script "mkdir -p $HOME/.config/ytdl && touch " & welcomeFlag
end greetOnce

on pick(theList)
	return item (random number from 1 to (count of theList)) of theList
end pick

-- Apple events time out after 120 seconds by default. Matthew hit
-- "AppleEvent timed out. (-1712)" from this app, and the calls that can
-- plausibly run that long are `--update` (a brew upgrade takes minutes) and
-- `--info` on a slow link (yt-dlp waits up to 180 seconds of its own).
--
-- Raising the timeout here is the documented remedy. Worth being straight
-- about the evidence though: a short-timeout reproduction did not fire, so
-- this is the known fix for the known cause rather than something reproduced
-- from first principles. It costs nothing if the cause was elsewhere, and the
-- -1712 handler below means a recurrence reports itself in words either way.
-- Find the ytdl command. Looks in the personal bin folders first, then
-- anything on the (extended) PATH. Returns false, after explaining, if it is
-- nowhere; the app cannot do anything without it.
on locateYtdl()
	set found to ""
	try
		set found to do shell script shellPrefix & ¬
			"for c in \"$HOME/bin/ytdl\" \"$HOME/.local/bin/ytdl\" /opt/homebrew/bin/ytdl /usr/local/bin/ytdl; do " & ¬
			"[ -x \"$c\" ] && { printf %s \"$c\"; exit 0; }; done; command -v ytdl"
	end try
	if found is "" then
		my tell_("I can't find the ytdl command on this Mac, so there's nothing I can do yet." & return & return & ¬
			"Run install.sh from the ytdl-accessible folder in Terminal. It links ytdl onto your PATH and rebuilds this app. " & ¬
			"If you already ran it, it said which folder it used; make sure that folder is on your PATH.")
		return false
	end if
	set ytdlPath to quoted form of found
	return true
end locateYtdl

on ytdl(argsText)
	with timeout of 1800 seconds
		return do shell script shellPrefix & ytdlPath & " " & argsText
	end timeout
end ytdl

-- The same, but reports a timeout in words instead of a number.
on ytdlSlow(argsText, whatItIs)
	try
		return my ytdl(argsText)
	on error errText number errNum
		if errNum is -1712 then
			return whatItIs & " took too long and was given up on."
		end if
		error errText number errNum
	end try
end ytdlSlow

on settingValue(theKey)
	try
		return my ytdl("--get " & theKey)
	on error
		return "?"
	end try
end settingValue

-- Only offer a link yt-dlp actually recognises. Asking yt-dlp's own matchers
-- beats guessing from the hostname, and it runs offline, so it costs about a
-- third of a second. Without it, any article or search page got offered.
on clipboardLink()
	try
		set clipText to (the clipboard as text)
		set trimmed to do shell script "printf %s " & quoted form of clipText & ¬
			" | head -1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'"
		if trimmed does not start with "http" then return {"", ""}
		try
			return {trimmed, my ytdl("--check-url " & quoted form of trimmed)}
		on error
			return {"", ""}
		end try
	end try
	return {"", ""}
end clipboardLink

on mainScreen()
	set found to my clipboardLink()
	set startURL to item 1 of found
	set siteName to item 2 of found

	if startURL is not "" then
		set shown to startURL
		if (count of shown) > 60 then set shown to (text 1 thru 60 of shown) & "..."
		try
			set ans to button returned of (display dialog ¬
				"You copied a " & siteName & " link:" & return & return & shown & ¬
				return & return & "Download this one?" ¬
				with title appTitle ¬
				buttons {"Quit", "Type a different link", "Download this"} ¬
				default button "Download this" cancel button "Type a different link")
		on error number -128
			set ans to "Type a different link"
		end try
		if ans is "Quit" then return false
		if ans is "Type a different link" then set startURL to ""
	end if

	set opener to my pick({"What would you like?", "Give me a link.", ¬
		"What are we downloading?", "Paste a link and I'll fetch it."})

	try
		set reply to display dialog opener & return & ¬
			"Several at once? Put spaces between them." ¬
			default answer startURL with title appTitle ¬
			buttons {"Quit", "Settings", "Download"} default button "Download"
	on error number -128
		return true
	end try

	set pressed to button returned of reply
	if pressed is "Quit" then return false
	if pressed is "Settings" then
		settingsScreen()
		return true
	end if

	set theURL to text returned of reply
	if theURL is "" then
		my tell_("I need a link first.")
		return true
	end if

	set defFmt to my settingValue("format")
	set formatNames to {"My usual, which is " & defFmt, ¬
		"Best quality — never converts, no quality lost", ¬
		"M4A — plays in anything", ¬
		"Opus — smallest file for the quality", ¬
		"WAV — uncompressed, for REAPER", ¬
		"MP3 — plays in anything, older format", ¬
		"FLAC — lossless", "Video — MP4 with picture", "Back"}
	set chosen to choose from list formatNames with prompt ¬
		"Which format?" default items {item 1 of formatNames} ¬
		OK button name "Use this" cancel button name "Back"
	if chosen is false then return true
	set chosenName to item 1 of chosen
	if chosenName is "Back" then return true

	set theFlag to ""
	if chosenName starts with "Best" then set theFlag to " --format best"
	if chosenName starts with "M4A" then set theFlag to " --format m4a"
	if chosenName starts with "Opus" then set theFlag to " --format opus"
	if chosenName starts with "WAV" then set theFlag to " --format wav"
	if chosenName starts with "MP3" then set theFlag to " --format mp3"
	if chosenName starts with "FLAC" then set theFlag to " --format flac"
	if chosenName starts with "Video" then set theFlag to " --format video"

	set quoted_urls to ""
	set AppleScript's text item delimiters to " "
	set parts to text items of theURL
	set AppleScript's text item delimiters to ""
	set howMany to 0
	repeat with aPart in parts
		if (aPart as text) is not "" then
			set quoted_urls to quoted_urls & " " & quoted form of (aPart as text)
			set howMany to howMany + 1
		end if
	end repeat

	if theURL contains "list=" and howMany is 1 then
		try
			set plAnswer to button returned of (display dialog ¬
				"That link has a whole playlist attached." & return & return & ¬
				"Pick the ones I want lets you tick individual episodes." ¬
				with title appTitle ¬
				buttons {"Just this one", "Pick the ones I want", "All of it"} ¬
				default button "Just this one")
		on error number -128
			set plAnswer to "Just this one"
		end try

		if plAnswer is "All of it" then
			set theFlag to theFlag & " --playlist"

		else if plAnswer is "Pick the ones I want" then
			set picked to my pickEpisodes(quoted_urls)
			if picked is "" then return true
			set theFlag to theFlag & " --playlist --items " & picked
		end if
	end if

	if howMany is 1 then
		try
			set infoText to my ytdlSlow(quoted_urls & theFlag & " --info", "Reading that link")
		on error errText
			my tell_("That didn't work." & return & return & errText & return & return & ¬
				"Nothing was downloaded.")
			return true
		end try
		set summary to paragraph 1 of infoText
		try
			set summary to summary & return & paragraph 2 of infoText
		end try
	else
		set summary to (howMany as text) & " links, one after another."
	end if

	-- Detached on purpose: the app must never sit blocking on a long download.
	-- The ytdl-done and ytdl-fail tones are the completion signal, which is why
	-- --notify is not optional here.
	do shell script shellPrefix & "nohup " & ytdlPath & quoted_urls & theFlag & ¬
		" --notify > $HOME/.ytdl-app.log 2>&1 &"

	set sendoff to my pick({"Off I go.", "On it.", "Right, downloading.", "Say no more."})
	try
		set answer2 to button returned of (display dialog sendoff & return & return & summary & ¬
			return & return & "You'll hear a tone when it's done." ¬
			with title appTitle ¬
			buttons {"Quit", "Check progress", "Another link"} ¬
			default button "Another link")
	on error number -128
		set answer2 to "Another link"
	end try
	if answer2 is "Quit" then return false
	if answer2 is "Check progress" then progressScreen()
	return true
end mainScreen

-- Tick the episodes you want. A multi-select list is the right control here:
-- it is one pass, it reads item by item under VoiceOver, and it beats typing a
-- range of numbers at something you cannot see. Returns an --items value, or
-- "" if nothing was chosen.
on pickEpisodes(quotedURL)
	try
		set raw to my ytdl("--list-items " & quotedURL & " --plain")
	on error errText
		my tell_("Could not read that playlist." & return & return & errText)
		return ""
	end try
	if raw is "" then
		my tell_("That link has no list behind it.")
		return ""
	end if

	set AppleScript's text item delimiters to tab
	set shownList to {}
	repeat with aLine in paragraphs of raw
		set aLine to aLine as text
		if aLine is not "" then
			set bits to text items of aLine
			set label_ to (item 1 of bits) & ". " & (item 2 of bits)
			if (count of bits) > 2 then set label_ to label_ & " (" & (item 3 of bits) & ")"
			set end of shownList to label_
		end if
	end repeat
	set AppleScript's text item delimiters to ""

	if (count of shownList) is 0 then
		my tell_("That list came back empty.")
		return ""
	end if

	set chosenItems to choose from list shownList with prompt ¬
		"Tick the ones you want. " & (count of shownList) & " to choose from." ¬
		with multiple selections allowed ¬
		OK button name "Download these" cancel button name "Back"
	if chosenItems is false then return ""
	if (count of chosenItems) is 0 then return ""

	-- Rebuild the --items value from the leading number of each ticked line.
	set numbers to ""
	repeat with anItem in chosenItems
		set t to anItem as text
		set AppleScript's text item delimiters to "."
		set n to first text item of t
		set AppleScript's text item delimiters to ""
		if numbers is "" then
			set numbers to n
		else
			set numbers to numbers & "," & n
		end if
	end repeat
	return numbers
end pickEpisodes

-- Re-checking is a button, never a timer: a dialog that refreshed itself would
-- talk over VoiceOver mid-sentence.
on progressScreen()
	repeat
		try
			set ans to button returned of (display dialog my ytdl("--jobs") ¬
				with title appTitle buttons {"Back", "Check again"} ¬
				default button "Check again" cancel button "Back")
		on error number -128
			return
		end try
		if ans is "Back" then return
	end repeat
end progressScreen

on settingsScreen()
	repeat
		set sTo to my settingValue("to")
		set AppleScript's text item delimiters to "/"
		set shortTo to last text item of sTo
		set AppleScript's text item delimiters to ""
		set opts to {"Check progress", ¬
			"Downloads folder: " & shortTo, ¬
			"Format: " & my settingValue("format"), ¬
			"Notify my phone: " & my settingValue("notify"), ¬
			"Speak progress: " & my settingValue("progress"), ¬
			"Auto-update: " & my settingValue("auto_update"), ¬
			"Show all settings", "Check if a site works", ¬
			"Update yt-dlp now", "Help", "Back"}
		set choice to choose from list opts with prompt ¬
			"Settings. Each line shows what it is set to." ¬
			default items {item 1 of opts} ¬
			OK button name "Open" cancel button name "Back"
		if choice is false then return
		set what to item 1 of choice
		if what is "Back" then return

		try
			if what is "Check progress" then
				progressScreen()

			else if what is "Help" then
				helpScreen()

			else if what is "Show all settings" then
				my tell_(my ytdl("--settings"))

			else if what starts with "Downloads folder" then
				set theFolder to choose folder with prompt "Where should downloads go?"
				my ytdl("--set to=" & quoted form of (POSIX path of theFolder))
				my tell_("Downloads now go to " & (POSIX path of theFolder) & ".")

			else if what starts with "Format" then
				set fmts to {"best — never converts anything", "m4a — plays in anything", ¬
					"opus — smallest for the quality", "mp3 — older, always converts", ¬
					"wav — uncompressed", "flac — lossless", "video — MP4", "Back"}
				set f to choose from list fmts with prompt ¬
					"Format, currently " & my settingValue("format") & "." ¬
					default items {item 1 of fmts} ¬
					OK button name "Use this" cancel button name "Back"
				if f is not false and (item 1 of f) is not "Back" then
					set AppleScript's text item delimiters to " "
					set justFmt to first text item of (item 1 of f)
					set AppleScript's text item delimiters to ""
					my ytdl("--set format=" & justFmt)
					my tell_("Format is now " & justFmt & ".")
				end if

			else if what starts with "Notify my phone" then
				my toggle("notify", "Send a notification to your phone when a download finishes?")

			else if what starts with "Speak progress" then
				my toggle("progress", "Say a percentage every ten seconds while downloading?")

			else if what starts with "Auto-update" then
				my toggle("auto_update", "Let yt-dlp update itself when a download fails?")

			else if what starts with "Check if a site" then
				set q to text returned of (display dialog "Which site?" ¬
					default answer "bandcamp" with title appTitle ¬
					buttons {"Cancel", "Check"} default button "Check" cancel button "Cancel")
				my tell_(my ytdl("--sites " & quoted form of q))

			else if what starts with "Update yt-dlp" then
				display dialog "This can take a few minutes. Nothing will happen on screen while it runs." ¬
					with title appTitle buttons {"Cancel", "Update"} ¬
					default button "Update" cancel button "Cancel"
				my tell_(my ytdlSlow("--update", "The update"))
			end if
		on error number -128
			-- Escape inside any of the above just returns to this list.
		end try
	end repeat
end settingsScreen

on helpScreen()
	my tell_("How it works." & return & return & ¬
		"Paste a link and press Download. Several links at once work if you put spaces between them." & return & return & ¬
		"If you copied a link before opening me, I offer it — but only if it's a site that actually works, so an article or a search page won't be suggested." & return & return & ¬
		"Downloads run in the background. You can close me and they carry on. A tone plays when one finishes, and a different tone if one fails.")

	my tell_("Formats." & return & return & ¬
		"Best quality never converts anything, so nothing is lost." & return & return & ¬
		"Choosing a specific format guarantees the file type, but converts the file when it isn't already that format — which loses a little quality for MP3 and M4A." & return & return & ¬
		"WAV and FLAC lose nothing. WAV is the one for a REAPER session.")

	my tell_("The rest." & return & return & ¬
		"Check progress shows what's downloading and what just finished. It only updates when you ask, so it never talks over you." & return & return & ¬
		"Playlists: I always ask first, and the whole playlist goes into its own numbered folder. Running it again picks up where it left off." & return & return & ¬
		"Escape goes back, and never closes the app. Quit is a button." & return & return & ¬
		"I never open or play anything I download.")
end helpScreen

-- A yes/no setting, always saying what it is now before asking.
on toggle(theKey, question)
	try
		set a to button returned of (display dialog question & return & return & ¬
			"Currently " & my settingValue(theKey) & "." with title appTitle ¬
			buttons {"Cancel", "No", "Yes"} cancel button "Cancel")
	on error number -128
		return
	end try
	if a is "Cancel" then return
	my ytdl("--set " & theKey & "=" & a)
	my tell_("Set to " & a & ".")
end toggle
