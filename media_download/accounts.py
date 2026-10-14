"""Your accounts: what you can open once Media Download borrows your browser's sign-in.

No password is ever asked for or kept. The download engine reads the sign-in your browser
already has (--cookies-from-browser) each time it needs it, and sends it only to that site.
With a browser chosen in Settings, every download, search and stream uses it, so members-only,
age-checked and private things work on any of the sites; this file adds the places that only
exist when you're signed in: Liked videos, Watch Later, your subscriptions, your likes.

Checked against the engine, 2026-10-13: YouTube's feeds and LL/WL lists answer only to a real
youtube.com sign-in (a browser signed in to Google but never to YouTube itself is refused);
SoundCloud's likes, tracks and playlists work by profile name; Vimeo's likes page is gone
(HTTP 410) and Bandcamp collections aren't supported, so neither is offered.
"""
from __future__ import annotations

import re

# key, service, what, address ({user} = the profile name asked for once), needs a profile name
COLLECTIONS = [
    ("youtube_liked", "YouTube", "Liked videos", "https://www.youtube.com/playlist?list=LL", None),
    ("youtube_later", "YouTube", "Watch Later", "https://www.youtube.com/playlist?list=WL", None),
    ("youtube_subs", "YouTube", "New from your subscriptions", "https://www.youtube.com/feed/subscriptions", None),
    ("youtube_playlists", "YouTube", "Your playlists", "https://www.youtube.com/feed/playlists", None),
    ("youtube_history", "YouTube", "Watch history", "https://www.youtube.com/feed/history", None),
    ("ytmusic_liked", "YouTube Music", "Liked music", "https://music.youtube.com/playlist?list=LM", None),
    ("soundcloud_likes", "SoundCloud", "Your likes", "https://soundcloud.com/{user}/likes", "soundcloud"),
    ("soundcloud_tracks", "SoundCloud", "Your tracks", "https://soundcloud.com/{user}/tracks", "soundcloud"),
    ("soundcloud_sets", "SoundCloud", "Your playlists", "https://soundcloud.com/{user}/sets", "soundcloud"),
]

PROFILE_WORDS = {"soundcloud": "your SoundCloud profile name (the part after soundcloud.com/ in your page's address)"}


def signin(cfg: dict) -> str:
    """The browser whose sign-in to borrow, or "" for none."""
    return cfg.get("app_signin", "") or ""


def profile_name(text: str, service: str) -> str:
    """'https://soundcloud.com/matthew-whitaker/likes' or '@matthew-whitaker' -> 'matthew-whitaker'."""
    text = (text or "").strip()
    m = re.search(r"%s\.com/([^/?#\s]+)" % service, text)
    if m:
        text = m.group(1)
    return text.lstrip("@").strip("/ ")


def address(key: str, cfg: dict) -> str | None:
    """The link for a collection; None while it still needs a profile name."""
    for k, _, _, url, needs in COLLECTIONS:
        if k == key:
            if needs:
                user = cfg.get("app_profile_" + needs, "")
                return url.format(user=user) if user else None
            return url
    return None


def row_words(key: str, cfg: dict) -> str:
    for k, service, what, _, needs in COLLECTIONS:
        if k == key:
            extra = ""
            if needs and not cfg.get("app_profile_" + needs):
                extra = " (asks for your profile name the first time)"
            return "%s: %s%s" % (service, what, extra)
    return key


def explain_signin(log: str, browser: str, service: str = "") -> str | None:
    """A sentence for a sign-in problem, or None if the trouble is something else."""
    low = (log or "").lower()
    name = (browser or "your browser").capitalize()
    if "operation not permitted" in low or "permission denied" in low or "full disk access" in low:
        return ("Media Download isn't allowed to read %s's sign-in. On a Mac, add Media Download under System "
                "Settings, Privacy & Security, Full Disk Access, then try again." % name)
    if "could not find" in low and "cookies database" in low:
        return "%s doesn't seem to be on this computer, or has never been opened. Choose another browser in Settings." % name
    if "login details are needed" in low or "playlist does not exist" in low or "sign in to confirm" in low \
            or "missing required authentication" in low:
        where = service or "that site"
        return ("%s isn't signed in to %s. Open %s in %s, sign in there, then try again; Media Download borrows "
                "that sign-in and never asks for a password." % (name, where, where, name))
    return None
