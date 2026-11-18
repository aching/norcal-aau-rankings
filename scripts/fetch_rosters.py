#!/usr/bin/env python3
"""Fetch upcoming-event rosters and resolve them to ranked team_ids.

Sources:
  BT: get-tournament-divisions + get-division-schedule per event
      (division_teams[].name). Cheap, unthrottled.
  EE: per-division eventgames XHR (rate-limited >=2s; often 429 after bulk
      discovery). Skipped here -- run with --ee after the throttle clears.

Writes data/upcoming_rosters.json:
  {event_id: {event, start, end, url, src, teams:
    [{raw, div, team_id|None, cohort|None, conf}]}}

Matching policy (user-confirmed): resolve via team_identity; attach only
when the resolved id is a ranked team on a board. Unmatched names stay on
the record (shown on upcoming.html) but create no team pages.
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from team_identity import resolve

EE_BASE = "https://basketball.exposureevents.com"
DATA = HERE.parent / "data"


def ranked_ids():
    import re
    ranked = {}
    for cohort in ("11u", "12u", "13u", "14u", "15u"):
        p = HERE.parent / "site" / f"{cohort}.html"
        if not p.exists():
            continue
        m = re.search(r"const DATA = (\[.*?\]);\nlet sortKey", p.read_text(), re.S)
        if not m:
            continue
        for r in json.loads(m.group(1)):
            ranked[r["team"]] = cohort
    return ranked


def fetch_bt():
    from scrape_bracketteam import api_get, api_post, unwrap
    bt = json.load(open("/tmp/bt_upcoming.json"))
    targets = [e for e in bt if (e.get("paid_teams_count") or 0) > 0 or e.get("has_matches")]
    print(f"BT roster fetch: {len(targets)} events", flush=True)
    out = {}
    for i, e in enumerate(targets):
        eid = e["id"]
        try:
            divs = unwrap(api_post("/get-tournament-divisions", {"tournament_id": eid}))
            time.sleep(1.7)
            divs = divs.get("divisions", []) if isinstance(divs, dict) else []
        except Exception as ex:
            print(f"  [{i+1}] {eid} divs ERR {str(ex)[:60]}")
            continue
        teams = []
        for d in divs:
            try:
                sched = unwrap(api_get("/get-division-schedule", {
                    "tournament_id": eid, "division_id": d["id"],
                    "page": 1, "matches_per_page": 1000}))
                time.sleep(1.7)
                for t in (sched.get("division_teams") or []):
                    nm = (t.get("name") or "").strip()
                    if nm and not t.get("is_no_team"):
                        teams.append({"raw": nm, "div": d.get("division_name") or ""})
            except Exception as ex:
                print(f"  div {d.get('id')} ERR {str(ex)[:60]}")
        seen, uniq = set(), []
        for t in teams:
            k = (t["raw"].lower(), t["div"].lower())
            if k not in seen:
                seen.add(k)
                uniq.append(t)
        pub = (e.get("public_url") or {}).get("absolute") or f"https://bracketteam.com/event/{eid}"
        out[str(eid)] = {
            "event": e.get("event_name", "?"), "start": str(e.get("start_date") or "")[:10],
            "end": str(e.get("end_date") or "")[:10], "url": pub, "src": "BT",
            "teams": uniq,
        }
        print(f"  [{i+1}/{len(targets)}] {eid} {e.get('event_name','')[:44]:44} {len(uniq)} teams",
              flush=True)
    return out


def resolve_all(events):
    ranked = ranked_ids()
    print(f"ranked teams: {len(ranked)}")
    n_match = 0
    for eid, ev in events.items():
        for t in ev["teams"]:
            tid, conf = resolve(t["raw"], t.get("div") or "")
            t["conf"] = conf
            if tid in ranked:
                t["team_id"] = tid
                t["cohort"] = ranked[tid]
                n_match += 1
            else:
                t["team_id"] = None
                t["cohort"] = None
    print(f"matched: {n_match}")
    return events


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--ee", action="store_true", help="also probe EE divisions (rate-limited)")
    args = ap.parse_args()

    try:
        events = json.load(open(DATA / "upcoming_rosters.json"))
        print(f"loaded {len(events)} existing events")
    except FileNotFoundError:
        events = {}
    events.update(fetch_bt())
    if args.ee:
        print("EE probing not yet implemented -- run after throttle clears")
    events = resolve_all(events)
    out = DATA / "upcoming_rosters.json"
    out.write_text(json.dumps(events, indent=1))
    print(f"wrote {out} ({len(events)} events)")


if __name__ == "__main__":
    main()
