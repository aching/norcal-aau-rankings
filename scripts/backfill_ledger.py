#!/usr/bin/env python3
"""Backfill the per-event ledger (data/scrape_state.json `events` section).

Reconciles three sources of truth:
  1. discovery snapshots (data/events_ca*.json + events_upcoming.json) -> pending
  2. corpus JSON on disk (data/[0-9]*.json, bt_*, fb_*) -> downloaded/empty
  3. aau.db tables (ee_tournaments/bt_events/fb_events) -> processed

Idempotent: reruns only fill gaps, never overwrite a fresher status
(downloaded > pending; processed is terminal until file mtime changes).

Usage: python3 scripts/backfill_ledger.py [--source ee|bt|fb]
"""
import json
import glob
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from scrape_state import load, record_event

DATA = HERE.parent / "data"


def discovery_events():
    """id -> {name, city, start, org} from all EE snapshots."""
    seen = {}
    for f in sorted(glob.glob(str(DATA / "events_ca*.json"))) + [str(DATA / "events_upcoming.json")]:
        try:
            evs = json.load(open(f))
        except Exception:
            continue
        if isinstance(evs, dict):
            evs = evs.get("events", evs.get("data", []))
        for e in evs:
            if e.get("Id") and e["Id"] not in seen:
                seen[str(e["Id"])] = {
                    "name": e.get("Name", "?"),
                    "city": e.get("City") or e.get("Location") or "",
                    "start": (e.get("StartDate") or "")[:10],
                    "org": (e.get("OrganizationName") or "").strip(),
                }
    return seen


def main():
    only = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--source" else None
    state = load()
    events = state.setdefault("events", {})
    made = {"pending": 0, "downloaded": 0, "empty": 0, "processed": 0, "skipped": 0}

    # 1. discovery -> pending (only if no record yet)
    if only in (None, "ee"):
        for eid, meta in discovery_events().items():
            key = f"ee:{eid}"
            if key not in events:
                r = record_event("ee", eid, "pending", games=None, **meta,
                                 detail="seeded from discovery snapshot")
                # seeding is not an attempt: reset the counter/expiry
                from scrape_state import load as _load, STATE_PATH as _SP
                _s = _load()
                _s["events"][key]["attempts"] = 0
                _s["events"][key].pop("last_attempt", None)
                _s["events"][key]["next_retry"] = ""
                _SP.write_text(json.dumps(_s, indent=2))
                made["pending"] += 1
            else:
                made["skipped"] += 1

    # 2. corpus files -> downloaded/empty (skip if already processed)
    def note_file(source, eid, ngames):
        key = f"{source}:{eid}"
        cur = events.get(key, {})
        if cur.get("status") == "processed":
            made["skipped"] += 1
            return
        st = load()["events"].get(key, {}).get("status")
        if ngames > 0:
            if st != "downloaded":
                record_event(source, eid, "downloaded", games=ngames)
                made["downloaded"] += 1
            else:
                made["skipped"] += 1
        else:
            if st not in ("empty", "gone"):
                record_event(source, eid, "empty", games=0,
                             detail="0 games on disk")
                made["empty"] += 1
            else:
                made["skipped"] += 1

    if only in (None, "ee"):
        for fp in glob.glob(str(DATA / "[0-9]*.json")):
            try:
                d = json.load(open(fp))
            except Exception:
                continue
            note_file("ee", str(d.get("tournament_id") or Path(fp).stem),
                      len(d.get("games", [])))
    if only in (None, "bt"):
        for fp in glob.glob(str(DATA / "bt_*.json")):
            m = re.match(r"bt_(.+)\.json$", Path(fp).name)
            if not m:
                continue
            try:
                d = json.load(open(fp))
            except Exception:
                continue
            note_file("bt", m.group(1),
                      len(d.get("games", [])) + len(d.get("teams", [])))
    if only in (None, "fb"):
        for fp in glob.glob(str(DATA / "fb_*.json")):
            m = re.match(r"fb_(.+)\.json$", Path(fp).name)
            if not m:
                continue
            try:
                d = json.load(open(fp))
            except Exception:
                continue
            note_file("fb", m.group(1), len(d.get("games", [])))

    # 3. DB tables -> processed (authoritative: game rows exist in aau.db)
    db_path = DATA / "aau.db"
    if db_path.exists():
        con = sqlite3.connect(db_path)
        for source, table, col in (("ee", "ee_games", "tournament_id"),
                                   ("bt", "bt_games", "event_id"),
                                   ("fb", "fb_games", "event_id")):
            if only and source != only:
                continue
            try:
                rows = con.execute(
                    f"SELECT {col}, COUNT(*) FROM {table} GROUP BY {col}").fetchall()
            except Exception:
                continue
            for eid, n in rows:
                key = f"{source}:{eid}"
                cur = load()["events"].get(key, {})
                if cur.get("status") != "processed":
                    # games count recorded without bumping attempts
                    from scrape_state import mark_processed
                    mark_processed(source, str(eid), n)
                    made["processed"] += 1
                else:
                    made["skipped"] += 1
        con.close()
    print(f"backfill: {made}")


if __name__ == "__main__":
    main()
