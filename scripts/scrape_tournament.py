#!/usr/bin/env python3
"""
Scrape a single exposureevents tournament: divisions + all games.

Usage:
  python3 scrape_tournament.py <tournament_id> <tournament_slug> [out_dir]

Writes: <out_dir>/<tournament_id>.json
"""
import json, re, sys, time, urllib.parse, urllib.request, http.cookiejar, random
from pathlib import Path

UA = "AAU-Basketball-Aggregator/0.1 (avery@aptoslabs.com)"
BASE = "https://basketball.exposureevents.com"
RATE_LIMIT_SECONDS = 2.0
# Backoff on 429/5xx (added Nov 2026 after ad-hoc probing got the IP
# throttled mid-scrape): sleep, retry same division, slow down after.
BACKOFF_BASE = 30
BACKOFF_MAX_RETRIES = 3


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


def _note(tid, status, **kw):
    try:
        from scrape_state import record_event
        record_event("ee", str(tid), status, **kw)
    except Exception:
        pass


def scrape_tournament(tid, slug, out_dir="data"):
    opener = make_opener()
    sched_url = f"{BASE}/{tid}/{slug}/schedule"
    games_url = f"{BASE}/{tid}/{slug}/eventgames"

    print(f"[{tid}] GET schedule ...")
    try:
        html = get(opener, sched_url)
    except Exception as e:
        code = getattr(getattr(e, "fp", None), "status", None) or getattr(e, "code", None)
        if code == 410 or "410" in str(e):
            print(f"[{tid}] GONE (410) -- marking terminal")
            _note(tid, "gone", detail="HTTP 410 on schedule page")
        else:
            print(f"[{tid}] schedule fetch ERROR: {e}")
            _note(tid, "failed", detail=f"schedule fetch: {e}"[:200])
        raise
    divisions = extract_divisions(html)
    meta = extract_metadata(html)
    print(f"[{tid}] {len(divisions)} divisions — {meta.get('title','')}")
    _note(tid, "downloaded", games=0, name=meta.get("title") or slug,
          detail=f"{len(divisions)} divisions listed")

    all_games = []
    slowed = False
    for d in divisions:
        time.sleep(RATE_LIMIT_SECONDS * (2 if slowed else 1))
        raw = None
        for attempt in range(BACKOFF_MAX_RETRIES + 1):
            try:
                raw = post_xhr(opener, games_url, {"divisionid": d["Id"], "eventid": tid}, sched_url)
                break
            except Exception as e:
                code = getattr(getattr(e, "fp", None), "status", None) or getattr(e, "code", None)
                throttled = code in (429, 500, 502, 503, 504) or "429" in str(e) or "Too Many" in str(e)
                if throttled and attempt < BACKOFF_MAX_RETRIES:
                    wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 5)
                    print(f"  [{d['Id']}] throttled ({e}) -- waiting {wait:.0f}s (try {attempt + 2}/{BACKOFF_MAX_RETRIES + 1})")
                    try:
                        from scrape_state import record_throttle
                        record_throttle("ee", f"tournament:{tid}",
                                        note=f"429/5xx on division {d['Id']}")
                    except Exception:
                        pass
                    time.sleep(wait)
                    slowed = True
                    continue
                print(f"  [{d['Id']}] {d['Name']} — ERROR: {e}")
                break
        if raw is None:
            continue
        try:
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
    if len(all_games) == 0:
        _note(tid, "empty", games=0, name=meta.get("title") or slug,
              detail=f"{len(divisions)} divisions, no games posted")
    else:
        _note(tid, "downloaded", games=len(all_games),
              name=meta.get("title") or slug)
    return payload


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    tid = sys.argv[1]
    slug = sys.argv[2]
    out_dir = sys.argv[3] if len(sys.argv) > 3 else "data"
    try:
        from scrape_state import throttled_since
        remaining = throttled_since("ee")
        if remaining:
            print(f"[throttle] EE throttled us recently -- "
                  f"cooldown ends in {remaining / 60:.0f}m. "
                  f"Waiting it out instead of burning budget...")
            time.sleep(remaining + 5)
    except ImportError:
        pass
    scrape_tournament(tid, slug, out_dir)
