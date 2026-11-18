#!/usr/bin/env python3
"""
Batch scrape: iterate over events_ca_past12mo.json, filter to NorCal,
scrape each tournament that we haven't already scraped, and save to data/.

Writes progress to data/_batch_progress.log
"""
import json, os, sys, time
from pathlib import Path

# Reuse the single-tournament scraper
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrape_tournament import scrape_tournament
from scrape_state import Progress, record

NORCAL_SUBSTR = [
    "oakland","san jose","san francisco","fremont","hayward","san leandro","san mateo",
    "palo alto","sunnyvale","santa clara","milpitas","san ramon","dublin","pleasanton",
    "concord","walnut creek","berkeley","richmond","daly city","redwood","mountain view",
    "livermore","union city","newark","san bruno","castro valley","alameda","emeryville",
    "sacramento","elk grove","roseville","rancho cordova","folsom","stockton","modesto",
    "tracy","manteca","antioch","vallejo","fairfield","napa","santa rosa","san rafael",
    "novato","petaluma","marin","monterey","salinas","santa cruz","watsonville","gilroy",
    "morgan hill","los gatos","los altos","menlo park","burlingame","belmont","foster city",
    "danville","san carlos","cupertino","saratoga","campbell","east palo alto","tri-valley",
    "bay area",
]


def is_norcal(city):
    return bool(city) and any(s in city.lower() for s in NORCAL_SUBSTR)


# Circuit events carry the prestige multiplier (AGENTS.md): Jr. EYBL,
# 3SSB/3Stripes, UA. Most are SoCal-based but NorCal teams travel, so
# they bypass the NorCal city gate. User-confirmed Nov 2026. Camps and
# tryouts have no bracket games -- never match (skip those).
CIRCUIT_SUBSTR = [
    "jr. eybl", "jr eybl", "eybl",
    "3ssb", "3stripes", "3stripes gold",
    "earn your stripes", "super regional",
    "peach jam", "uaa finals", "ua next",
]
SKIP_SUBSTR = ["camp", "tryout", "clinic", "combine", "showcase"]


def is_circuit(name):
    low = (name or "").lower()
    if any(s in low for s in SKIP_SUBSTR):
        return False
    return any(s in low for s in CIRCUIT_SUBSTR)


def main(events_file="data/events_ca_past12mo.json", out_dir="data"):
    events = json.load(open(events_file))
    # Filter NorCal past
    norcal = [e for e in events if is_norcal(e.get("City")) and e.get("EndDate") and e["EndDate"] < "2026-05-30"]
    norcal.sort(key=lambda e: e["EndDate"], reverse=True)  # most-recent first

    progress = Path(out_dir) / "_batch_progress.log"
    progress.parent.mkdir(parents=True, exist_ok=True)

    def log(msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
        with open(progress, "a") as f: f.write(line)
        print(line, end="", flush=True)

    log(f"START — {len(norcal)} NorCal past tournaments queued")
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    prog = Progress(len(norcal), label="EE backfill")
    done = 0; skipped = 0; failed = 0
    for i, e in enumerate(norcal, 1):
        tid = e["Id"]; slug = e.get("Slug") or e["Name"].lower().replace(" ", "-")
        out_path = Path(out_dir) / f"{tid}.json"
        if out_path.exists():
            log(f"[{i}/{len(norcal)}] SKIP {tid} (already have)")
            skipped += 1
            prog.tick(msg=f"SKIP {tid}")
            continue
        try:
            log(f"[{i}/{len(norcal)}] SCRAPE {tid} {slug[:40]:40} ({e.get('City','?')[:18]:18}) ending {e.get('EndDate','?')}")
            prog.render(f"SCRAPE {tid} {slug[:40]}")
            scrape_tournament(tid, slug, out_dir)
            done += 1
            prog.tick(msg=f"SCRAPE {tid}")
        except Exception as ex:
            log(f"[{i}/{len(norcal)}] FAIL  {tid} {ex}")
            failed += 1
            prog.tick(failed=1, msg=f"FAIL {tid}")
    prog.finish(f"scraped {done}, skipped {skipped}, failed {failed}")
    log(f"DONE — scraped {done}, skipped {skipped}, failed {failed}")
    record("exposureevents", "backfill",
           {"queued": len(norcal), "scraped": done, "skipped": skipped, "failed": failed},
           status="ok" if not failed else "failed", started_at=started)


if __name__ == "__main__":
    main()
