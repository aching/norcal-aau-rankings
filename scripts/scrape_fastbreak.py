#!/usr/bin/env python3
"""Scrape a FastBreak Compete event (server-rendered HTML, no API needed).

Usage:
    python3 scripts/scrape_fastbreak.py <event_id> <slug> [out_dir]

Bootstraps the division list from the `var divisions = [...]` JSON blob
(the page REQUIRES a valid ?division=<id> param -- the bare URL renders
a stub with no select and no games), fetches every division page,
parses game cards (teams, scores, winner class, venue, date,
pool/bracket), and writes data/fb_<event_id>.json.

Etiquette: 1 concurrent request, >=1.5s delay, honest UA -- same as
the BracketTeam scraper (AGENTS.md).
"""

import html as ihtml
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

BASE = "https://events.fastbreakcompete.ai"
UA = "AAU-Basketball-Aggregator/0.1 (avery@aptoslabs.com)"
DELAY = 1.5


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def json_blob(html, var):
    """Extract `var <name> = [...];` balancing brackets (no regex)."""
    i = html.find(f"var {var} = ")
    if i < 0:
        return None
    i += len(f"var {var} = ")
    while i < len(html) and html[i] in " \t":
        i += 1
    if i >= len(html) or html[i] not in "[{":
        return None
    open_c, close_c = html[i], "]" if html[i] == "[" else "}"
    depth, instr, esc, j = 0, False, False, i
    while j < len(html):
        c = html[j]
        if instr:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
        elif c == '"':
            instr = True
        elif c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return json.loads(html[i:j + 1])
        j += 1
    return None


def parse_divisions(html):
    m = re.search(r'id="division-select"[^>]*>(.*?)</select>', html, re.S)
    if not m:
        return []
    return [(oid, ihtml.unescape(n.strip())) for oid, _sel, n in
            re.findall(r'<option value="(\d+)"( selected)?>([^<]+)</option>',
                       m.group(1))]


def parse_games(html, division_name):
    games = []
    parts = re.split(
        r'<div[^>]*class="card divisions-and-teams-card card-game"[^>]*'
        r'data-game-id="(\d+)"[^>]*>', html)
    # parts[0] = prelude; then alternating (game_id, card) pairs
    for k in range(1, len(parts), 2):
        gid, card = parts[k], parts[k + 1] if k + 1 < len(parts) else ""
        hdr = re.search(
            r'<div class="card-header">(.*?)</div>\s*<div class="card-body',
            card, re.S)
        when = venue = court = ""
        if hdr:
            bits = re.findall(r'title="([^"]+)"', hdr.group(1))
            when = bits[0] if len(bits) > 0 else ""
            venue = bits[1] if len(bits) > 1 else ""
            court = bits[2].strip("()") if len(bits) > 2 else ""
        teams = re.findall(
            r'<div class="card-team-container([^"]*)">.*?'
            r'data-team-name="([^"]+)".*?'
            r'<div class="card-team-score">\s*(\d*)\s*</div>',
            card, re.S)
        if len(teams) != 2:
            continue
        (cls_h, home, hs), (cls_a, away, aws) = teams
        status = "FINAL" if "card-info-final" in card else "Scheduled"
        dm = re.search(
            r'card-info-final">FINAL</div>\s*<div>([^<]+)</div>\s*<div>([^<]+)</div>',
            card)
        weekday, datestr = (dm.group(1), dm.group(2)) if dm else ("", "")
        pm = re.search(r'card-footer-info">.*?<div[^>]*title="([^"]+)"',
                       card, re.S)
        pool = pm.group(1) if pm else ""
        games.append({
            "game_id": gid,
            "division_name": division_name,
            "pool": pool,
            "date": datestr.strip(),
            "weekday": weekday.strip(),
            "time": when.strip(),
            "venue": venue.strip(),
            "court": court.strip(),
            "home_team": ihtml.unescape(home.strip()),
            "home_score": int(hs) if hs else None,
            "home_winner": "winner" in cls_h,
            "away_team": ihtml.unescape(away.strip()),
            "away_score": int(aws) if aws else None,
            "away_winner": "winner" in cls_a,
            "status": status,
        })
    return games


def main():
    event_id, slug = sys.argv[1], sys.argv[2]
    out_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("data")
    url0 = f"{BASE}/event/{event_id}-{slug}"
    stub = fetch(url0)
    divs = json_blob(stub, "divisions") or []
    if not divs:
        print("no divisions blob found", file=sys.stderr)
        sys.exit(1)
    info = json_blob(stub, "eventInfo") or {}
    meta = {"title": info.get("name") or slug,
            "start_date": info.get("startDate"),
            "end_date": info.get("endDate"),
            "city": info.get("city"),
            "tenant": info.get("tenant"),
            "published": info.get("published")}
    print(f"{meta['title']}: {len(divs)} divisions")
    all_games, div_list = [], []
    for d in divs:
        did, dname = str(d["id"]), d["name"]
        html = fetch(f"{url0}?division={did}")
        gs = parse_games(html, dname)
        print(f"  [{did}] {dname}: {len(gs)} games")
        all_games.extend(gs)
        scored = sum(1 for g in gs if g["home_score"] is not None)
        div_list.append({"Id": int(did), "Name": dname,
                         "games": len(gs), "scored": scored})
        time.sleep(DELAY)
    out = {"metadata": {"event_id": event_id, "slug": slug,
                        "source": "fastbreak", **meta},
           "divisions": div_list, "games": all_games}
    path = out_dir / f"fb_{event_id}.json"
    path.write_text(json.dumps(out, indent=1))
    scored = sum(1 for g in all_games if g["home_score"] is not None)
    print(f"wrote {path}: {len(all_games)} games ({scored} scored)")


if __name__ == "__main__":
    main()
