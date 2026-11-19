#!/usr/bin/env python3
"""
Scrape a single exposureevents tournament: divisions + all games.

Usage:
  python3 scrape_tournament.py <tournament_id> <tournament_slug> [out_dir]

Writes: <out_dir>/<tournament_id>.json
"""
import json, re, sys, time, urllib.parse, urllib.request, http.cookiejar
from pathlib import Path

UA = "AAU-Basketball-Aggregator/0.1 (avery@aptoslabs.com)"
BASE = "https://basketball.exposureevents.com"
RATE_LIMIT_SECONDS = 2.0


def make_opener():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", UA)]
    return opener


def get(opener, url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with opener.open(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def post_xhr(opener, url, body, referer):
    data = urllib.parse.urlencode(body).encode()
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": referer,
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with opener.open(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def extract_divisions(html):
    m = re.search(r"divisions:\s*(\[\{.*?\}\]),", html, re.S)
    if not m:
        return []
    return json.loads(m.group(1))


def extract_metadata(html):
    meta = {}
    t = re.search(r"<title>([^<]+)</title>", html)
    if t:
        meta["title"] = t.group(1).strip()
    return meta


def scrape_tournament(tid, slug, out_dir="data"):
    opener = make_opener()
    sched_url = f"{BASE}/{tid}/{slug}/schedule"
    games_url = f"{BASE}/{tid}/{slug}/eventgames"

    print(f"[{tid}] GET schedule …")
    html = get(opener, sched_url)
    divisions = extract_divisions(html)
    meta = extract_metadata(html)
    print(f"[{tid}] {len(divisions)} divisions — {meta.get('title','')}")

    all_games = []
    for d in divisions:
        time.sleep(RATE_LIMIT_SECONDS)
        try:
            raw = post_xhr(opener, games_url, {"divisionid": d["Id"], "eventid": tid}, sched_url)
            day_groups = json.loads(raw)
        except Exception as e:
            print(f"  [{d['Id']}] {d['Name']} — ERROR: {e}")
            continue
        n = sum(len(g["Games"]) for g in day_groups)
        print(f"  [{d['Id']:>9}] {d['Name']:50} {n} games")
        for grp in day_groups:
            for g in grp["Games"]:
                g["_division_id"] = d["Id"]
                g["_division_name"] = d["Name"]
                g["_day_group"] = grp["Name"]
                all_games.append(g)

    payload = {
        "tournament_id": int(tid),
        "tournament_slug": slug,
        "metadata": meta,
        "divisions": divisions,
        "games": all_games,
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    out = Path(out_dir) / f"{tid}.json"
    out.write_text(json.dumps(payload, indent=2))
    print(f"[{tid}] -> {out} ({len(all_games)} total games)")
    return payload


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    tid = sys.argv[1]
    slug = sys.argv[2]
    out_dir = sys.argv[3] if len(sys.argv) > 3 else "data"
    scrape_tournament(tid, slug, out_dir)
