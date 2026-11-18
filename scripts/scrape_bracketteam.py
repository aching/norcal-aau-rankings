#!/usr/bin/env python3
"""
Scrape a single bracketteam.com tournament: event meta + divisions + all games.

Usage:
  python3 scrape_bracketteam.py <event_id> [out_dir]

Writes: data/bt_<event_id>.json

Source: bracketteam.com public API (site is an Angular SPA; HTML shell is empty).
Auth: the app embeds its public API key in main.*.js (apiKey); requests carry
it as X-Authorization. robots.txt is fully open (Allow: /).
Rate limit: >=1.5s between requests (we only read public schedule endpoints).
"""
import json, sys, time, urllib.parse, urllib.request
from pathlib import Path

UA = "AAU-Basketball-Aggregator/0.1 (avery@aptoslabs.com)"
# Public app API key embedded in bracketteam.com's JS bundle (apiKey in environment config).
API_KEY = "fB0SC4jghlUrszbzgFmHyAPeWvzwc5kWV3yhdP9xhs8ysLRkDDGpomh5gmqoZdAc"
BASE = "https://bracketteam.com/api"
RATE_LIMIT_SECONDS = 1.5

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
    "bay area","chico","martinez","manteca","clayton","livermore","pittsburg","rocklin",
    "oro ville","oroville","pinole","concord","antioch","danville","california",
]


def is_norcal(event):
    blob = json.dumps(event).lower()
    if "wisconsin" in blob or "virginia" in blob or "new jersey" in blob or "arizona" in blob:
        return False
    return any(s in blob for s in NORCAL_SUBSTR)


def api_get(path, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "X-Authorization": API_KEY, "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, headers={
        "User-Agent": UA, "X-Authorization": API_KEY,
        "Content-Type": "application/json", "Accept": "application/json",
    }, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def unwrap(resp):
    if isinstance(resp, dict) and resp.get("success") and "content" in resp:
        return resp["content"]
    return resp


def scrape_event(event_id):
    event = unwrap(api_get("/get-public-tournament", {"tournament_id": event_id}))
    t = event.get("tournament", event)
    time.sleep(RATE_LIMIT_SECONDS)
    divs = unwrap(api_post("/get-tournament-divisions", {"tournament_id": int(event_id)}))
    divisions = divs.get("divisions", []) if isinstance(divs, dict) else []
    print(f"[{event_id}] {t.get('event_name')} — {len(divisions)} divisions")

    all_games, teams = [], {}
    for d in divisions:
        did = d["id"]
        time.sleep(RATE_LIMIT_SECONDS)
        try:
            sched = unwrap(api_get("/get-division-schedule", {
                "tournament_id": event_id, "division_id": did,
                "page": 1, "matches_per_page": 1000,
            }))
        except Exception as e:
            print(f"  [{did}] {d.get('division_name')} — ERROR: {e}")
            continue
        matches = sched.get("matches", []) if isinstance(sched, dict) else []
        n = 0
        for m in matches:
            m["_division_id"] = did
            m["_division_name"] = d.get("division_name")
            m["_event_id"] = int(event_id)
            all_games.append(m); n += 1
        for tm in (sched.get("division_teams", []) or []):
            teams[tm["id"]] = {"id": tm["id"], "name": tm.get("name"),
                               "alias": tm.get("alias"),
                               "main_team": (tm.get("main_team") or {}).get("name")}
        print(f"  [{did:>7}] {str(d.get('division_name')):45} {n} games")

    payload = {
        "source": "bracketteam",
        "event_id": int(event_id),
        "event_name": t.get("event_name"),
        "start_date": t.get("start_date"), "end_date": t.get("end_date"),
        "venues": t.get("venues", []),
        "sport_id": t.get("sport_id"),
        "divisions": divisions,
        "teams": sorted(teams.values(), key=lambda x: x["id"]),
        "games": all_games,
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    event_id = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "data"
    payload = scrape_event(event_id)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    out = Path(out_dir) / f"bt_{event_id}.json"
    out.write_text(json.dumps(payload, indent=2))
    print(f"[{event_id}] -> {out} ({len(payload['games'])} total games)")


if __name__ == "__main__":
    main()
