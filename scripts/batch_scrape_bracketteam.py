#!/usr/bin/env python3
"""
Batch scrape: discover NorCal basketball events on bracketteam.com and scrape
each one we haven't already scraped.

Usage:
  python3 batch_scrape_bracketteam.py [out_dir]

Writes data/bt_<event_id>.json per event + progress to data/_batch_bt_progress.log

Note: bracketteam's search index only surfaces recent/upcoming events (as of
Oct 2026 the oldest basketball events are ~Aug 2026), so this is the
going-forward pipeline, not a backfill. History lives in exposureevents data.
"""
import json, sys, time, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrape_bracketteam import api_get, unwrap, scrape_event, is_norcal
from scrape_state import Progress, record
from storage import atomic_write_json

SPORT_BASKETBALL = 2


def discover_events():
    events, page = [], 1
    while True:
        resp = unwrap(api_get("/advanced-events-search", {
            "page": page, "items_per_page": 100, "sport_id": SPORT_BASKETBALL,
            "show_all_tournaments": "true",
        }))
        results = resp.get("result", []) if isinstance(resp, dict) else []
        if not results:
            break
        events.extend(results)
        pages = resp.get("pages", [1])
        if page >= max(pages):
            break
        page += 1
        time.sleep(1.5)
    return events


def main(out_dir="data", interactive=True):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    progress = out_dir / "_batch_bt_progress.log"

    def log(msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
        with open(progress, "a") as f: f.write(line)
        print(line, end="", flush=True)

    events = discover_events()
    norcal = [e for e in events if is_norcal(e)]
    log(f"START — {len(events)} basketball events found, {len(norcal)} NorCal")
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    prog = Progress(len(norcal), label="BT backfill", interactive=interactive)
    done = skipped = failed = 0
    for i, e in enumerate(norcal, 1):
        eid = e["id"]
        out_path = out_dir / f"bt_{eid}.json"
        if out_path.exists():
            log(f"[{i}/{len(norcal)}] SKIP {eid} (already have)")
            skipped += 1
            prog.tick(msg=f"SKIP {eid}")
            continue
        try:
            log(f"[{i}/{len(norcal)}] SCRAPE {eid} {e.get('event_name','?')[:45]:45} ({e.get('start_date','?')})")
            prog.render(f"SCRAPE {eid} {e.get('event_name','?')[:45]}")
            time.sleep(1.5)
            payload = scrape_event(eid)
            atomic_write_json(out_path, payload)
            log(f"[{i}/{len(norcal)}]   -> {len(payload['games'])} games, {len(payload['divisions'])} divisions")
            done += 1
            prog.tick(msg=f"SCRAPE {eid}")
        except Exception as ex:
            log(f"[{i}/{len(norcal)}] FAIL  {eid} {ex}")
            failed += 1
            prog.tick(failed=1, msg=f"FAIL {eid}")
    prog.finish(f"scraped {done}, skipped {skipped}, failed {failed}")
    log(f"DONE — scraped {done}, skipped {skipped}, failed {failed}")
    record("bracketteam", "backfill",
           {"found": len(events), "norcal": len(norcal),
            "scraped": done, "skipped": skipped, "failed": failed},
           status="ok" if not failed else "failed", started_at=started)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data")
