#!/usr/bin/env python3
"""
Re-scrape exposureevents tournaments that currently have no games
(empty divisions or divisions-but-no-games). Schedules often publish late.

Usage:
  python3 rescrape_empty.py [--limit N] [--include-upcoming] [out_dir]

Default skips the upcoming tournament 257525 (actively being scouted; excluded
from historical analysis by scout.py). Pass --include-upcoming to re-scrape it too.
Writes data/<tid>.json in place, progress to data/_rescrape_progress.log.
"""
import json, glob, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrape_tournament import scrape_tournament
from scrape_state import Progress, record

UPCOMING_TID = "257525"


def needs_rescrape(path):
    d = json.load(open(path))
    tid = str(d.get("tournament_id"))
    if tid == UPCOMING_TID and "--include-upcoming" not in sys.argv:
        return False
    return len(d.get("games", [])) == 0


def main():
    out_dir = sys.argv[-1] if len(sys.argv) > 1 and not sys.argv[-1].startswith("--") and sys.argv[-1] != "scripts/rescrape_empty.py" else "data"
    limit = None
    for a in sys.argv:
        if a.startswith("--limit"):
            limit = int(a.split("=")[1])
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    progress = out_dir / "_rescrape_progress.log"

    def log(msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
        with open(progress, "a") as f: f.write(line)
        print(line, end="", flush=True)

    files = sorted(glob.glob(str(out_dir / "[0-9]*.json")))
    todo = [f for f in files if needs_rescrape(f)]
    if limit:
        todo = todo[:limit]
    log(f"START — {len(todo)} empty tournaments to re-scrape (of {len(files)} total)")
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    prog = Progress(len(todo), label="EE rescrape-empty")

    fixed = still_empty = failed = 0
    for i, f in enumerate(todo, 1):
        tid = Path(f).stem
        slug = json.load(open(f)).get("tournament_slug", "")
        log(f"[{i}/{len(todo)}] RESCRAPE {tid} {slug[:40]}")
        prog.render(f"RESCRAPE {tid} {slug[:40]}")
        try:
            payload = scrape_tournament(tid, slug, str(out_dir))
            if payload["games"]:
                fixed += 1
                log(f"[{i}/{len(todo)}]   FIXED {tid}: {len(payload['games'])} games")
            else:
                still_empty += 1
                log(f"[{i}/{len(todo)}]   still empty {tid}")
            prog.tick(msg=f"RESCRAPE {tid}")
        except Exception as ex:
            log(f"[{i}/{len(todo)}] FAIL {tid} {ex}")
            failed += 1
            prog.tick(failed=1, msg=f"FAIL {tid}")
    prog.finish(f"newly filled {fixed}, still empty {still_empty}, failed {failed}")
    log(f"DONE — newly filled {fixed}, still empty {still_empty}, failed {failed}")
    record("exposureevents", "rescrape-empty",
           {"queued": len(todo), "filled": fixed, "still_empty": still_empty, "failed": failed},
           status="ok" if not failed else "failed", started_at=started)


if __name__ == "__main__":
    main()
