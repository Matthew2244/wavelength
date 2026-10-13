"""The download list: what runs when, on how many cores, and what happened.

No window code here, so all of it can be tested without one. The window
subscribes with a listener and is told about every change; it decides what to
redraw and what to say.

Limits, both in Settings:
- downloads at once (automatic: half the cores, two to eight), and
- downloads from one site at once (3), because a site that sees too many
  requests from one address answers "429 too many requests" or a bot check.
Lookups run beside downloads with their own limit, so a long download never
stops the next link from being looked up.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time

from . import engine, words
from .jobs import ACTIVE, FINISHED, Job

PROBE_AT_ONCE = 4


def worker_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker"]
    return [sys.executable, "-m", "media_download", "--worker"]


def _popen(task: dict) -> subprocess.Popen:
    kw = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
              text=True, encoding="utf-8", bufsize=1)
    if sys.platform == "win32":
        kw["creationflags"] = 0x00000200 | 0x08000000  # new process group, no console window
    else:
        kw["start_new_session"] = True  # its own group, so Stop ends ffmpeg too
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(worker_command(), env=env, **kw)
    proc.stdin.write(json.dumps(task) + "\n")
    proc.stdin.close()
    return proc


def _kill(proc: subprocess.Popen) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                           creationflags=0x08000000)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass


def run_task(task: dict, on_event=None, timeout: float = 300) -> list[dict]:
    """Run one short task (search, recognise) to the end. Returns its events."""
    proc = _popen(task)
    events = []
    timer = threading.Timer(timeout, _kill, (proc,))
    timer.start()
    try:
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            events.append(ev)
            if on_event:
                on_event(ev)
    finally:
        timer.cancel()
        proc.wait()
    return events


class Manager:
    def __init__(self, settings: dict, listener=None):
        self.settings = settings
        self.listener = listener or (lambda job, what, data=None: None)
        self.jobs: list[Job] = []
        self.lock = threading.RLock()
        # job id -> (run number, process or None while starting). A job's run number goes up
        # each time it starts, so a stopped run finishing late can never touch the next run.
        self.procs: dict[int, tuple] = {}
        self.probing = 0
        self.dirty = False
        self.updating_engine = False
        self.batch_started = None
        self.batch_counts = {"done": 0, "failed": 0}
        self.batch_total = 0
        self.site_pause: dict[str, float] = {}
        self.wake_timer = None
        self.wake_when = None
        self.notices: list = []

    # ------------------------------------------------------------ limits

    def parallel(self) -> int:
        return int(self.settings.get("app_parallel") or 0) or engine.auto_parallel()

    def per_site(self) -> int:
        return max(1, int(self.settings.get("app_per_site") or 3))

    # ------------------------------------------------------------ list

    def find(self, job_id: int) -> Job | None:
        with self.lock:
            for j in self.jobs:
                if j.id == job_id:
                    return j
        return None

    def add(self, job: Job, at: int | None = None) -> Job:
        with self.lock:
            job.state = "waiting" if job.probed else "looking"
            if at is None:
                self.jobs.append(job)
            else:
                self.jobs.insert(at, job)
            if self.batch_started is None:
                self.batch_started = time.time()
                self.batch_counts = {"done": 0, "failed": 0}
                self.batch_total = 0
            self.batch_total += 1
            self.dirty = True
        self.listener(job, "added")
        self.pump()
        return job

    def _drop_temp(self, job: Job) -> None:
        """Delete this download's partial files. Kept after a stop or failure so Retry resumes."""
        import shutil
        from .options import temp_dir
        d = temp_dir(job.spec())
        if os.path.basename(d) != "shared":
            shutil.rmtree(d, ignore_errors=True)

    def remove(self, job: Job) -> None:
        self.stop(job, quiet=True)
        self._drop_temp(job)
        with self.lock:
            if job in self.jobs:
                self.jobs.remove(job)
            self.dirty = True
        self.listener(job, "removed")

    def clear_finished(self) -> int:
        with self.lock:
            gone = [j for j in self.jobs if j.state in ("done", "skipped")]
            self.jobs = [j for j in self.jobs if j not in gone]
            self.dirty = True
        for j in gone:
            self.listener(j, "removed")
        return len(gone)

    def counts(self) -> dict:
        out = {}
        with self.lock:
            for j in self.jobs:
                out[j.state] = out.get(j.state, 0) + 1
        return out

    def busy(self) -> bool:
        with self.lock:
            return any(j.state in ACTIVE or j.state in ("waiting", "waiting_choice") for j in self.jobs)

    # ------------------------------------------------------------ control

    def stop(self, job: Job, quiet: bool = False) -> None:
        with self.lock:
            entry = self.procs.pop(job.id, None)
            proc = entry[1] if entry else None
            if job.state in ACTIVE or job.state == "waiting":
                job.state = "stopped"
                job.stage = ""
                job.reason = "Stopped by you."
                self.dirty = True
        if proc:
            _kill(proc)
        if not quiet:
            self.listener(job, "changed")
        self.pump()

    def stop_all(self) -> int:
        with self.lock:
            targets = [j for j in self.jobs if j.state in ACTIVE or j.state == "waiting"]
        for j in targets:
            self.stop(j, quiet=True)
            self.listener(j, "changed")
        return len(targets)

    def retry(self, job: Job) -> None:
        with self.lock:
            if job.state in ACTIVE:
                return
            job.reset_progress()
            job.net_retries = 0
            self.site_pause.pop(job.site, None)  # asked for by hand: don't keep making them wait
            job.state = "waiting" if job.probed else "looking"
            job.finished = 0.0
            if self.batch_started is None:
                self.batch_started = time.time()
                self.batch_counts = {"done": 0, "failed": 0}
                self.batch_total = 0
            self.batch_total += 1
            self.dirty = True
        self.listener(job, "changed")
        self.pump()

    def move(self, job: Job, delta: int) -> None:
        with self.lock:
            i = self.jobs.index(job)
            k = max(0, min(len(self.jobs) - 1, i + delta))
            self.jobs.insert(k, self.jobs.pop(i))
            self.dirty = True
        self.listener(job, "moved")

    def expand(self, job: Job, entries: list[dict], folder: str, numbered: bool = True) -> list[Job]:
        """Replace a playlist's row with one row per chosen item."""
        with self.lock:
            at = self.jobs.index(job) if job in self.jobs else len(self.jobs)
            if job in self.jobs:
                self.jobs.remove(job)
                self.batch_total = max(0, self.batch_total - 1)
        self.listener(job, "removed")
        made = []
        for k, e in enumerate(entries):
            spec = {f: getattr(job, f) for f in ("dest", "kind", "max_height", "start", "end", "chapters",
                                                  "subtitles", "transcript", "cookies", "extra", "cover_art")}
            item = Job(url=e["url"], subfolder=folder, index=(e.get("number") or k + 1) if numbered else 0,
                       **spec)
            item.title = e.get("title") or ""
            if item.title and item.title != e["url"]:
                item.item_title = item.title
            item.length = e.get("duration") or 0
            item.uploader = e.get("uploader") or ""
            item.probed = True  # the playlist listing already said what it is
            if e.get("info_file"):
                item.info_file, item.info_time = e["info_file"], time.time()
            made.append(self.add(item, at + k))
        return made

    # ------------------------------------------------------------ running

    def pump(self) -> None:
        """Start whatever the limits allow."""
        with self.lock:
            notices, self.notices = self.notices, []
        for kind, site, until in notices:
            self.listener(None, kind, {"site": site, "until": until})
        start_probe, start_dl = [], []
        with self.lock:
            running = [j for j in self.jobs if j.state in ("downloading", "converting")]
            per_site = {}
            for j in running:
                # Converting doesn't touch the site, so only downloads count against its limit:
                # an album from one site still converts on every core.
                if j.state == "downloading":
                    per_site[j.site] = per_site.get(j.site, 0) + 1
            free = self.parallel() - len(running)
            now = time.time()
            wake = []
            for j in self.jobs:
                hold = max(j.not_before, self.site_pause.get(j.site, 0)) if j.state in ("looking", "waiting") else 0
                if hold > now:
                    wake.append(hold)
                    continue
                if j.state == "looking" and j.id not in self.procs and self.probing < PROBE_AT_ONCE:
                    self.probing += 1
                    j.run += 1
                    self.procs[j.id] = (j.run, None)  # reserved
                    start_probe.append((j, j.run))
                elif j.state == "waiting" and free > 0 and per_site.get(j.site, 0) < self.per_site():
                    free -= 1
                    per_site[j.site] = per_site.get(j.site, 0) + 1
                    j.state = "downloading"
                    j.percent = None
                    j.run += 1
                    self.procs[j.id] = (j.run, None)
                    start_dl.append((j, j.run))
            if wake:
                self._wake_at(min(wake))
        for j, run in start_probe:
            threading.Thread(target=self._run_probe, args=(j, run), daemon=True).start()
        for j, run in start_dl:
            self.listener(j, "changed")
            threading.Thread(target=self._run_download, args=(j, run), daemon=True).start()
        self._check_all_done()

    def _wake_at(self, when: float) -> None:
        """Pump again when the earliest wait is over (lock held)."""
        if self.wake_timer and self.wake_when and self.wake_when <= when:
            return
        if self.wake_timer:
            self.wake_timer.cancel()
        self.wake_when = when
        self.wake_timer = threading.Timer(max(0.1, when - time.time() + 0.2), self._woken)
        self.wake_timer.daemon = True
        self.wake_timer.start()

    def _woken(self):
        with self.lock:
            self.wake_timer = self.wake_when = None
        self.pump()
        with self.lock:
            due = [j for j in self.jobs if j.state in ("waiting", "looking")]
        for j in due:
            self.listener(j, "changed")

    def _no_room(self, job: Job) -> bool:
        """Too big for the disk it's going to? Say so before starting, not at 90 percent (lock held)."""
        import shutil
        need = job.bytes_total or 0
        if job.kind != "video" and job.kind in ("wav", "flac"):
            need *= 6  # converting compressed audio to WAV or FLAC makes it several times bigger
        if not need:
            return False
        try:
            free = shutil.disk_usage(job.dest if os.path.isdir(job.dest) else os.path.dirname(job.dest)).free
        except OSError:
            return False
        if free > need * 1.1 + 200_000_000:
            return False
        job.reason = ("There isn't room: it needs about %s and that disk has %s free. Free some space, or "
                      "choose another folder, then Retry." % (words.size(need), words.size(free)))
        return True

    def _try_later(self, job: Job, text: str) -> bool:
        """Network trouble or a "slow down": wait and try again by itself. True if it will (lock held).

        A connection that drops or a server error waits 15 seconds, then a minute. A site that
        says too many requests (429) pauses every download from that site for 5, then 10, then
        15 minutes: hammering it again is how a short pause becomes a long block.
        """
        now = time.time()
        if words.is_rate_limited(text) and job.net_retries < 3:
            job.net_retries += 1
            until = now + 300 * job.net_retries
            first = self.site_pause.get(job.site, 0) < now
            self.site_pause[job.site] = max(self.site_pause.get(job.site, 0), until)
            job.not_before = self.site_pause[job.site]
            job.wait_reason = ("%s asked for fewer downloads, so everything from it is paused. Trying again at %s."
                               % (job.site or "The site", words.clock_time(job.not_before)))
            if first:
                self.notices.append(("site_paused", job.site, job.not_before))
            return True
        if words.is_transient(text) and job.net_retries < 2:
            delay = (15, 60)[job.net_retries]
            job.net_retries += 1
            job.not_before = now + delay
            job.wait_reason = "Lost the connection, or the site had a problem. Trying again by itself."
            return True
        return False

    def _check_all_done(self):
        with self.lock:
            if self.batch_started is None or self.busy() or self.updating_engine:
                return
            took = time.time() - self.batch_started
            counts = dict(self.batch_counts)
            self.batch_started = None
        self.listener(None, "all_done", {"took": took, **counts})

    def _spawn(self, job: Job, task: dict, run: int):
        with self.lock:
            if self.procs.get(job.id) != (run, None) or job.run != run or job.state not in ACTIVE:
                self._release(job, run)
                return None  # stopped, removed or restarted before it started
            proc = _popen(task)
            self.procs[job.id] = (run, proc)
            return proc

    def _release(self, job: Job, run: int) -> None:
        """Forget this run's process, but only if it is still this run's (lock held)."""
        entry = self.procs.get(job.id)
        if entry and entry[0] == run:
            del self.procs[job.id]

    def _events(self, job: Job, proc):
        for line in proc.stdout:
            try:
                yield json.loads(line)
            except ValueError:
                continue
        proc.wait()

    def _run_probe(self, job: Job, run: int) -> None:
        playlist, ok, log = None, False, []
        try:
            proc = self._spawn(job, {"task": "probe", "spec": job.spec()}, run)
            if proc is None:
                return
            for ev in self._events(job, proc):
                e = ev.get("ev")
                if e == "info" and job.run == run:
                    with self.lock:
                        job.title = ev.get("title") or job.title
                        job.length = ev.get("duration") or 0
                        job.uploader = ev.get("uploader") or ""
                        job.info_file = ev.get("info_file") or ""
                        job.info_time = time.time()
                        job.bytes_total = ev.get("size") or 0
                        job.formats = ev.get("formats") or []
                elif e == "playlist":
                    playlist = ev
                elif e == "log":
                    log.append(ev.get("text", ""))
                elif e == "end":
                    ok = ev.get("ok", False)
        finally:
            with self.lock:
                self.probing -= 1
                stopped = job.state != "looking" or job.run != run
                self._release(job, run)
                if not stopped:
                    if playlist is not None:
                        job.state = "waiting_choice"
                    elif ok and self._no_room(job):
                        job.state = "failed"
                        job.finished = time.time()
                        self.batch_counts["failed"] += 1
                    elif ok:
                        job.state = "waiting"
                        job.probed = True
                    elif self._try_later(job, "\n".join(log)):
                        job.state = "looking"  # look it up again once the wait is over
                    else:
                        job.state = "failed"
                        job.log_tail = log[-12:]
                        job.reason = words.explain_failure("\n".join(log), bool(job.cookies), job.site)
                        job.finished = time.time()
                        self.batch_counts["failed"] += 1
                self.dirty = True
        if playlist is not None and not stopped:
            self.listener(job, "playlist", playlist)
        else:
            self.listener(job, "changed" if stopped or ok else "finished")
        self.pump()

    def _run_download(self, job: Job, run: int) -> None:
        log, files, ok, already = [], [], False, False
        spec = job.spec()
        spec["rate_limit"] = self.settings.get("app_rate_limit") or ""
        task = {"task": job.task or "download", "spec": spec,
                "fragments": int(self.settings.get("app_fragments") or 4)}
        try:
            proc = self._spawn(job, task, run)
            if proc is None:
                return
            for ev in self._events(job, proc):
                e = ev.get("ev")
                with self.lock:
                    if job.run != run:
                        break  # stopped and started again: this run's news is stale
                    if e == "progress":
                        job.state = "downloading"
                        job.bytes_done = ev.get("done") or 0
                        job.bytes_total = ev.get("total") or job.bytes_total
                        job.percent = (100.0 * job.bytes_done / job.bytes_total) if job.bytes_total else None
                        job.speed, job.eta = ev.get("speed"), ev.get("eta")
                        job.part, job.part_count = ev.get("part") or 1, ev.get("parts") or 1
                        if ev.get("title") and not job.title:
                            job.title = ev["title"]
                    elif e == "stage":
                        freed = job.state == "downloading"
                        job.state = "converting"
                        job.stage = ev.get("text") or "Converting"
                    elif e == "file":
                        files.append(ev["path"])
                    elif e == "described":
                        srt = next((f for f in files if f.endswith(".srt")), None)
                        if srt:
                            from . import describe
                            describe.remember(ev.get("url") or job.url, srt)
                    elif e == "already":
                        already = True
                    elif e == "log":
                        log.append(ev.get("text", ""))
                    elif e == "end":
                        ok = ev.get("ok", False)
                    if job.state not in ACTIVE:
                        break  # stopped meanwhile
                if e == "stage" and freed:
                    self.pump()  # its site slot is free for the next download
                self.listener(job, "progress")
        finally:
            retry_engine = False
            with self.lock:
                self._release(job, run)
                mine = job.run == run
                if job.state in ACTIVE and mine:
                    job.finished = time.time()
                    # Only what's really there: a cover image is downloaded, embedded, then deleted.
                    job.files = [f for f in dict.fromkeys(files) if os.path.exists(f)]
                    job.log_tail = log[-12:]
                    if job.info_file:
                        try:
                            os.remove(job.info_file)
                        except OSError:
                            pass
                        job.info_file = ""
                    if ok:
                        if any("NOTRANSCRIPT" in ln for ln in log):
                            job.note = "It has no captions, so there's no transcript."
                        self._drop_temp(job)
                        job.state = "skipped" if already and not files else "done"
                        job.stage = ""
                        job.percent = 100.0
                        if files:
                            try:
                                job.bytes_done = sum(os.path.getsize(f) for f in files if os.path.exists(f))
                            except OSError:
                                pass
                        self.batch_counts["done"] += 1
                    elif self._try_later(job, "\n".join(log)):
                        job.state = "waiting"
                        job.stage = ""
                        job.files = []
                    else:
                        text = "\n".join(log)
                        if (self.settings.get("auto_update", True) and not job.engine_retry
                                and words.worth_updating_for(text)):
                            job.engine_retry = True
                            job.state = "waiting"
                            job.stage = ""
                            job.reason = ""
                            job.files = []
                            retry_engine = True
                        else:
                            job.state = "failed"
                            job.reason = words.explain_failure(text, bool(job.cookies), job.site)
                            self.batch_counts["failed"] += 1
                    self.dirty = True
        if retry_engine:
            self._update_engine_then_retry(job)
            return
        if mine:
            self.listener(job, "finished")
        self.pump()

    def _update_engine_then_retry(self, job: Job) -> None:
        """A failure is the moment a newer yt-dlp is worth having. Update once, retry once."""
        with self.lock:
            job.state = "converting"
            job.stage = "Checking for a newer download engine"
            first = not self.updating_engine
            self.updating_engine = True
        self.listener(job, "changed")
        if first:
            outcome, sentence = engine.update_engine()
            with self.lock:
                self.updating_engine = False
            self.listener(None, "engine", {"outcome": outcome, "text": sentence})
        else:
            while self.updating_engine:
                time.sleep(0.5)
            outcome = "updated"
        with self.lock:
            if job.state != "converting":
                return  # stopped meanwhile
            # Retry once either way: with a new engine, or the same one, since
            # many failures are passing network trouble. engine_retry is set, so
            # a second failure is reported rather than retried again.
            job.state = "waiting"
            job.stage = ""
        self.listener(job, "changed")
        self.pump()

    # ------------------------------------------------------------ keeping

    def save(self) -> None:
        with self.lock:
            data = [j.to_dict() for j in self.jobs if j.state != "waiting_choice"][-500:]
            self.dirty = False
        try:
            os.makedirs(os.path.dirname(engine.QUEUE_FILE), exist_ok=True)
            tmp = engine.QUEUE_FILE + ".tmp"
            with open(tmp, "w") as fh:
                json.dump({"version": 1, "jobs": data}, fh)
            os.replace(tmp, engine.QUEUE_FILE)
        except OSError:
            pass

    def restore(self) -> int:
        """Bring back the list from last time. Unfinished ones come back stopped,
        never running on their own. Returns how many didn't finish."""
        try:
            with open(engine.QUEUE_FILE) as fh:
                data = json.load(fh).get("jobs") or []
        except (OSError, ValueError, AttributeError):
            return 0
        unfinished = 0
        with self.lock:
            for d in data:
                try:
                    j = Job.from_dict(d)
                except TypeError:
                    continue
                if j.state not in FINISHED:
                    j.state = "stopped"
                    j.stage = ""
                    j.reason = "The app closed before this finished."
                    unfinished += 1
                self.jobs.append(j)
        return unfinished

    def resume_unfinished(self) -> int:
        with self.lock:
            todo = [j for j in self.jobs if j.state == "stopped"]
        for j in todo:
            self.retry(j)
        return len(todo)

    def shutdown(self) -> None:
        with self.lock:
            procs = [e[1] for e in self.procs.values() if e and e[1]]
            for j in self.jobs:
                if j.state in ACTIVE or j.state == "waiting":
                    j.state = "stopped"
                    j.reason = "The app closed before this finished."
        for p in procs:
            _kill(p)
        self.save()
