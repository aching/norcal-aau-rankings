#!/usr/bin/env python3
"""Shared scrape-run ledger: data/scrape_state.json.

Tracks the last scrape per (source, job) so any agent/script can answer
"when did we last hit site X" without parsing log files. Survives DB rebuilds
(build_db.py mirrors it into a scrape_runs table); JSON is the source of truth.

Shape:
  {"runs": {"<source>:<job>": {"source": ..., "job": ..., "started_at": ...,
                               "finished_at": ..., "status": "ok|failed",
                               "stats": {...}, "note": ...}},
   "content": {"<source>": {"last_event_end": ..., "last_event_id": ...,
                             "last_game_date": ..., "updated_at": ...}}}
The "runs" section answers "when did the job last run"; the "content" section
answers "how fresh is the data" (newest event/game actually on disk).
Content watermarks are computed by `refresh.py status` from the JSON files;
jobs never write them directly.
"""
import json, sys, time
from pathlib import Path

STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "scrape_state.json"


def load():
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text())
        state.setdefault("runs", {})
        state.setdefault("content", {})
        return state
    return {"runs": {}, "content": {}}


def record(source, job, stats=None, status="ok", started_at=None, note=None):
    state = load()
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    entry = state["runs"].get(f"{source}:{job}", {})
    entry.update({
        "source": source, "job": job,
        "started_at": started_at or entry.get("started_at") or now,
        "finished_at": now, "status": status,
        "stats": stats or {}, "note": note,
    })
    state["runs"][f"{source}:{job}"] = entry
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))
    return entry


def last_run(source, job=None):
    state = load()
    runs = [r for r in state["runs"].values() if r["source"] == source
            and (job is None or r["job"] == job)]
    runs.sort(key=lambda r: r.get("finished_at", ""), reverse=True)
    return runs[0] if runs else None


THROTTLE_COOLDOWN_SECONDS = 30 * 60  # don't start new scrapes within 30m of a 429/5xx


def record_throttle(source, job, note=None):
    """Log that `source` throttled us (429/5xx). Scrapers call this on
    backoff; scrape entry points should check throttled_since() first."""
    state = load()
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    entry = state.setdefault("throttle", {}).get(source, {})
    entry.update({"source": source, "job": job, "throttled_at": now,
                  "note": note or ""})
    state["throttle"][source] = entry
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))
    return entry


def throttled_since(source, cooldown=THROTTLE_COOLDOWN_SECONDS):
    """Seconds since `source` last throttled us, or None if beyond cooldown
    (or never). Callers: if not None, wait it out or abort instead of
    burning more budget against a hot throttle."""
    state = load()
    entry = state.get("throttle", {}).get(source)
    if not entry or not entry.get("throttled_at"):
        return None
    try:
        ts = time.mktime(time.strptime(entry["throttled_at"], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return None
    age = time.time() - ts
    return None if age >= cooldown else cooldown - age


def update_content(source, watermark):
    """Merge a content watermark for a source. Keys: last_event_end,
    last_event_id, last_game_date (all optional)."""
    state = load()
    entry = state["content"].get(source, {})
    entry.update({k: v for k, v in watermark.items() if v is not None})
    entry["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    state["content"][source] = entry
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))
    return entry


class Progress:
    """Minimal stdlib-only progress meter for batch scrape loops.

    TTY (interactive terminal): rewrites one status line in place --
    `[done/total pct%|bar| rate/s ETA m:ss] current item`. Safe under
    `2>&1` (stderr merge keeps stdout a TTY); under a pipe (`| tail`)
    it degrades to milestone lines every ~10% since \\r can't work there.
    Per-item detail still goes to the caller's own log lines + file.
    """

    def __init__(self, total, label="", width=24, min_interval=0.15):
        self.total = max(int(total or 0), 0)
        self.label = (label + " ") if label else ""
        self.width = width
        self.min_interval = min_interval
        self.start = time.time()
        self.done = 0
        self.failed = 0
        self._last = 0.0
        self._last_pct = 0
        try:
            import shutil
            self.cols = shutil.get_terminal_size().columns
        except Exception:
            self.cols = 100
        try:
            self.tty = sys.stdout.isatty()
        except Exception:
            self.tty = False

    def tick(self, n=1, failed=0, msg=""):
        self.done += n
        self.failed += failed
        now = time.time()
        if self.done < self.total and now - self._last < self.min_interval:
            return
        self._last = now
        self.render(msg)

    def _line(self, msg):
        el = time.time() - self.start
        rate = self.done / el if el > 0 else 0.0
        pct = 100.0 * self.done / self.total if self.total else 100.0
        if rate > 0 and self.total and self.done < self.total:
            s = int((self.total - self.done) / rate)
            eta = f"{s // 60}:{s % 60:02d}"
        else:
            eta = "0:00" if self.done >= self.total else "--:--"
        fill = int(self.width * self.done / self.total) if self.total else self.width
        bar = "#" * fill + "-" * (self.width - fill)
        fail = f" failed={self.failed}" if self.failed else ""
        line = (f"{self.label}[{self.done}/{self.total} {pct:3.0f}%|{bar}| "
                f"{rate:.1f}/s ETA {eta}{fail}] {msg}")
        return line[: max(self.cols - 1, 20)]

    def render(self, msg=""):
        line = self._line(msg)
        if self.tty:
            sys.stdout.write("\r" + line + "\x1b[K")
            sys.stdout.flush()
        else:
            pct = int(100.0 * self.done / self.total) if self.total else 100
            if pct // 10 > self._last_pct // 10 or self.done >= self.total:
                self._last_pct = pct
                sys.stdout.write(line + "\n")
                sys.stdout.flush()

    def finish(self, msg="done"):
        if self.tty:
            sys.stdout.write("\r" + self._line(msg) + "\n")
        else:
            sys.stdout.write(f"{self.label}DONE - {msg}\n")
        sys.stdout.flush()
