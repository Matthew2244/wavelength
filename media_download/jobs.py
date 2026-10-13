"""One download: what was asked for, and everything known about it so far."""
from __future__ import annotations

import itertools
import os
import time
from dataclasses import asdict, dataclass, field, fields

from . import words

_ids = itertools.count(1)

ACTIVE = ("looking", "downloading", "converting")
# "waiting_choice": a playlist link, waiting for the person to say which items
FINISHED = ("done", "failed", "stopped", "skipped")


@dataclass
class Job:
    url: str
    dest: str
    kind: str = "best"
    max_height: int = 0
    format_id: str = ""
    format_audio_only: bool = False
    start: str = ""
    end: str = ""
    chapters: bool = False
    subtitles: bool = False
    cookies: str = ""
    subfolder: str = ""
    index: int = 0
    name: str = ""
    item_title: str = ""
    extra: str = ""
    cover_art: bool = True

    id: int = 0
    title: str = ""
    site: str = ""
    uploader: str = ""
    length: float = 0.0
    state: str = "waiting"
    stage: str = ""
    percent: float | None = None
    eta: float | None = None
    speed: float | None = None
    bytes_done: int = 0
    bytes_total: int = 0
    part: int = 1
    part_count: int = 1
    files: list = field(default_factory=list)
    formats: list = field(default_factory=list)
    reason: str = ""
    log_tail: list = field(default_factory=list)
    info_file: str = ""
    info_time: float = 0.0
    probed: bool = False
    engine_retry: bool = False
    added: float = 0.0
    finished: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = next(_ids)
        if not self.added:
            self.added = time.time()
        if not self.site:
            self.site = words.site_name(self.url)

    def folder(self) -> str:
        return os.path.join(self.dest, self.subfolder) if self.subfolder else self.dest

    def format_words(self) -> str:
        bits = [words.FORMAT_SHORT.get(self.kind, self.kind)]
        if self.format_id:
            bits = ["the exact stream %s" % self.format_id]
        if self.kind == "video" and self.max_height:
            bits.append("highest available" if self.max_height < 0 else "up to %dp" % self.max_height)
        if self.start or self.end:
            bits.append("from %s to %s" % (self.start or "the start", self.end or "the end"))
        if self.chapters:
            bits.append("split by chapter")
        if self.subtitles:
            bits.append("with subtitles")
        if self.cookies:
            bits.append("using %s sign-in" % self.cookies.capitalize())
        return ", ".join(bits)

    def reset_progress(self):
        self.percent = self.eta = self.speed = None
        self.bytes_done = self.bytes_total = 0
        self.part = self.part_count = 1
        self.stage = ""
        self.reason = ""
        self.log_tail = []
        self.files = []

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        known = {f.name for f in fields(cls)}
        job = cls(**{k: v for k, v in d.items() if k in known})
        job.id = next(_ids)  # ids are per run; a restored job gets a fresh one
        return job

    def spec(self) -> dict:
        """What a worker needs to run this download."""
        keys = ("url", "dest", "kind", "max_height", "format_id", "format_audio_only", "start", "end",
                "chapters", "subtitles", "cookies", "subfolder", "index", "name", "item_title", "extra", "cover_art",
                "info_file", "info_time")
        return {k: getattr(self, k) for k in keys}
