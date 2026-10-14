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
    transcript: bool = False
    cookies: str = ""
    subfolder: str = ""
    index: int = 0
    name: str = ""
    item_title: str = ""
    extra: str = ""
    cover_art: bool = True
    task: str = "download"       # or "describe": make audio description
    source_path: str = ""        # describe: a downloaded video to read, instead of fetching one

    id: int = 0
    title: str = ""
    site: str = ""
    uploader: str = ""
    upload_date: str = ""        # YYYYMMDD, exact
    upload_ts: float = 0.0       # or a time, approximate when upload_approx (YouTube lists)
    upload_approx: bool = False
    views: int = 0
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
    net_retries: int = 0
    not_before: float = 0.0      # waiting to try again: not before this time
    wait_reason: str = ""
    note: str = ""               # something worth knowing about a finished download
    tmp: str = ""
    run: int = 0
    added: float = 0.0
    finished: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = next(_ids)
        if not self.added:
            self.added = time.time()
        if not self.site:
            self.site = words.site_name(self.url)
        if not self.tmp:
            # Its own temporary folder, kept across Stop and Retry so a retry resumes.
            self.tmp = "job-%d-%d" % (int(self.added * 1000), self.id)

    def folder(self) -> str:
        if not self.subfolder:
            return self.dest
        from .options import safe_folder  # the name it's really saved under, not the raw title
        return os.path.join(self.dest, safe_folder(self.subfolder))

    def format_words(self) -> str:
        if self.task == "describe":
            return "audio description, made by reading the picture"
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
        if self.transcript:
            bits.append("with a text transcript")
        if self.cookies:
            from .accounts import spec_words
            bits.append("using %s's sign-in" % spec_words(self.cookies))
        return ", ".join(bits)

    def reset_progress(self):
        self.not_before, self.wait_reason, self.note = 0.0, "", ""
        self.percent = self.eta = self.speed = None
        self.bytes_done = self.bytes_total = 0
        self.part = self.part_count = 1
        self.stage = ""
        self.reason = ""
        self.log_tail = []
        self.files = []

    def take_when(self, d: dict) -> None:
        """Upload date and views from a listing or lookup (worker.when); an exact date wins."""
        if d.get("uploaded"):
            self.upload_date, self.upload_ts, self.upload_approx = str(d["uploaded"]), 0.0, False
        elif d.get("uploaded_ts") and not self.upload_date:
            self.upload_ts, self.upload_approx = float(d["uploaded_ts"]), bool(d.get("approx"))
        if d.get("views"):
            self.views = int(d["views"])

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
                "chapters", "subtitles", "transcript", "cookies", "subfolder", "index", "name", "item_title", "extra", "cover_art", "tmp", "task", "source_path", "title",
                "info_file", "info_time")
        return {k: getattr(self, k) for k in keys}
