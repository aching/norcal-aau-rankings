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
Content watermarks are computed by the refresh pipeline from the JSON files.
Every writer uses `edit_state()` so each read-modify-write is serialized across
threads/processes; atomic replacement keeps lock-free readers consistent.
"""
import json, sys, time
from contextlib import contextmanager
from pathlib import Path

from storage import atomic_write_json, file_lock

STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "scrape_state.json"
LOCK_PATH = STATE_PATH.with_suffix(".lock")


@contextmanager
def edit_state():
    """Serialize one read-modify-write transaction across threads/processes."""
    with file_lock(LOCK_PATH):
        state = load()
        yield state
        atomic_write_json(STATE_PATH, state)


def load():
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text())
        state.setdefault("runs", {})
        state.setdefault("content", {})
        return state
    return {"runs": {}, "content": {}}


def record(source, job, stats=None, status="ok", started_at=None, note=None):
    with edit_state() as state:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        entry = state["runs"].get(f"{source}:{job}", {})
        entry.update({
            "source": source, "job": job,
            "started_at": started_at or entry.get("started_at") or now,
            "finished_at": now, "status": status,
            "stats": stats or {}, "note": note,
        })
        state["runs"][f"{source}:{job}"] = entry
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
    with edit_state() as state:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        entry = state.setdefault("throttle", {}).get(source, {})
        entry.update({"source": source, "job": job, "throttled_at": now,
                      "note": note or ""})
        state["throttle"][source] = entry
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
    with edit_state() as state:
        entry = state["content"].get(source, {})
        entry.update({k: v for k, v in watermark.items() if v is not None})
        entry["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        state["content"][source] = entry
        return entry


# ---- Per-event tracking (added Nov 2026) ----
# Every discovered event gets a record keyed "<source>:<id>" (ee:123,
# bt:456, fb:789) with a lifecycle status:
#   pending    -- in discovery, never attempted
#   downloaded -- JSON on disk (games count recorded, may be 0)
#   processed  -- loaded into aau.db by build_db (set on rebuild sweep)
#   empty      -- scraped, 0 games; recheck_after date (schedules fill in)
#   failed     -- error (throttle/HTTP/parse); retry_after date
#   gone       -- HTTP 410, terminal; recheck_after ~90d
# Fields: name, city, start, org, status, games, attempts, last_attempt,
# next_retry (ISO date or ""), detail. Writers: scrapers set
# downloaded/empty/failed/gone; build_db marks processed; backfill seeds
# pending from discovery snapshots. Readers: refresh.py status backlog.
EVENT_RETRY_DAYS = {"failed": 3, "empty": 14, "gone": 90, "downloaded": 7}


def _today():
    return time.strftime("%Y-%m-%d")


def _retry_after(status, days=None):
    from datetime import date, timedelta
    d = days if days is not None else EVENT_RETRY_DAYS.get(status, 7)
    return (date.today() + timedelta(days=d)).isoformat()


def _record_event(state, source, eid, status, games=None, name=None, city=None,
                  start=None, org=None, detail=None, retry_days=None,
                  count_attempt=True):
    """Apply an event update to state already owned by edit_state()."""
    events = state.setdefault("events", {})
    key = f"{source}:{eid}"
    e = events.get(key, {})
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    if status != "processed" and count_attempt:
        e["attempts"] = (e.get("attempts") or 0) + 1
        e["last_attempt"] = now
    elif status != "processed":
        e.setdefault("attempts", 0)
    e.update({"source": source, "eid": str(eid), "status": status})
    for k, v in (("name", name), ("city", city), ("start", start),
                 ("org", org), ("detail", detail)):
        if v is not None:
            e[k] = v
    if games is not None:
        e["games"] = games
    if status == "downloaded":
        # downloaded but not yet in DB; processed set by build_db sweep
        e["next_retry"] = ""
    elif status == "processed":
        e["next_retry"] = ""
        e["processed_at"] = now
    elif status == "pending":
        # never attempted: due immediately
        e["next_retry"] = ""
    else:
        e["next_retry"] = _retry_after(status, retry_days)
    events[key] = e
    return e


def record_event(source, eid, status, games=None, name=None, city=None,
                 start=None, org=None, detail=None, retry_days=None):
    """Upsert one event record, counting attempts except for processed rows."""
    with edit_state() as state:
        return _record_event(state, source, eid, status, games=games, name=name,
                             city=city, start=start, org=org, detail=detail,
                             retry_days=retry_days)


def seed_pending_event(source, eid, **metadata):
    """Seed a missing pending event atomically; never displace real progress."""
    with edit_state() as state:
        if f"{source}:{eid}" in state.setdefault("events", {}):
            return None
        return _record_event(state, source, eid, "pending", count_attempt=False,
                             **metadata)


def mark_processed(source, eid, games):
    """Idempotent processed-marking (no attempt increment)."""
    return record_event(source, eid, "processed", games=games)


def mark_processed_many(rows):
    """Mark (source, event_id, games) rows with one locked ledger rewrite."""
    if not rows:
        return []
    with edit_state() as state:
        return [_record_event(state, source, eid, "processed", games=games)
                for source, eid, games in rows]


def event_backlog(source=None, only_due=False):
    """Events needing work: pending/failed past retry, empty/gone past
    recheck. Returns list sorted by (start, key)."""
    from datetime import date
    today = date.today().isoformat()
    out = []
    for key, e in load().get("events", {}).items():
        if source and e.get("source") != source:
            continue
        st = e.get("status")
        if st in ("downloaded", "processed"):
            continue
        if only_due and (e.get("next_retry") or "") > today:
            continue
        out.append(e)
    out.sort(key=lambda e: (e.get("start") or "", e.get("source") or "",
                            e.get("eid") or ""))
    return out


def event_stats(source=None):
    """Counter of statuses, optionally per source."""
    from collections import Counter
    c = Counter()
    for e in load().get("events", {}).values():
        if source and e.get("source") != source:
            continue
        c[e.get("status", "?")] += 1
    return dict(c)


class Progress:
    """Minimal stdlib-only progress meter for batch scrape loops.

    TTY (interactive terminal): rewrites one status line in place --
    `[done/total pct%|bar| rate/s ETA m:ss] current item`. Safe under
    `2>&1` (stderr merge keeps stdout a TTY); under a pipe (`| tail`)
    it degrades to milestone lines every ~10% since \\r can't work there.
    Per-item detail still goes to the caller's own log lines + file.
    """

    def __init__(self, total, label="", width=24, min_interval=0.15,
                 interactive=True):
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
            self.tty = interactive and sys.stdout.isatty()
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
