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

import argparse
import datetime as dt
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
    """Parse both legacy and current FastBreak server-rendered game cards."""
    games = []
    cards = list(re.finditer(
        r'<div\b[^>]*class="card divisions-and-teams-card card-game"[^>]*'
        r'data-game-id="(\d+)"[^>]*>', html, re.S))
    for index, match in enumerate(cards):
        gid = match.group(1)
        end = cards[index + 1].start() if index + 1 < len(cards) else len(html)
        card = html[match.end():end]
        hdr = re.search(r'<div class="card-header">(.*?)</div>\s*'
                        r'<div class="card-body', card, re.S)
        bits = re.findall(r'title="([^"]+)"', hdr.group(1)) if hdr else []
        when = ihtml.unescape(bits[0]).strip() if bits else ""
        venue = ihtml.unescape(bits[1]).strip() if len(bits) > 1 else ""
        court = ihtml.unescape(bits[2]).strip("()") if len(bits) > 2 else ""
        teams = re.findall(
            r'<div class="card-team-container([^"]*)">.*?'
            r'data-team-id="([^"]*)"\s+data-team-name="([^"]+)"', card, re.S)
        if len(teams) != 2:
            # Older cards may not carry a provider team id.
            teams = re.findall(
                r'<div class="card-team-container([^"]*)">.*?'
                r'data-team-name="([^"]+)"', card, re.S)
            if len(teams) == 2:
                teams = [(cls, "", name) for cls, name in teams]
        if len(teams) != 2:
            continue
        status = "FINAL" if "card-info-final" in card else "Scheduled"
        scores = re.findall(r'card-team-score[^>]*>\s*(\d*)\s*</div>', card, re.S)
        if len(scores) < 2:
            scores = re.findall(
                r'card-team-info[^>]*>\s*([0-9]+)\s*-\s*([0-9]+)\s*</div>',
                card, re.S)
            scores = list(scores[0]) if scores else []
        home_score = int(scores[0]) if len(scores) > 0 and scores[0] else None
        away_score = int(scores[1]) if len(scores) > 1 and scores[1] else None
        if status != "FINAL" and home_score == away_score == 0:
            home_score = away_score = None
        preceding = list(re.finditer(r'<h2>Games on ([^<]+)</h2>', html[:match.start()]))
        datestr = preceding[-1].group(1).strip() if preceding else ""
        if not datestr:
            dm = re.search(
                r'card-info-final">FINAL</div>\s*<div>([^<]+)</div>\s*<div>([^<]+)</div>',
                card)
            datestr = dm.group(2).strip() if dm else ""
        info = re.search(
            r'card-info-container[^>]*>\s*<div>([^<]+)</div>\s*<div>([^<]+)</div>',
            card, re.S)
        weekday = info.group(1).strip() if info else ""
        if not weekday:
            dm = re.search(
                r'card-info-final">FINAL</div>\s*<div>([^<]+)</div>\s*<div>([^<]+)</div>',
                card)
            weekday = dm.group(1).strip() if dm else ""
        pool = ""
        for title in re.findall(r'title="([^"]+)"', card):
            if title.startswith("Pool "):
                pool = ihtml.unescape(title)
                break
        (cls_h, home_id, home), (cls_a, away_id, away) = teams
        games.append({
            "game_id": gid, "division_name": division_name, "pool": pool,
            "date": datestr, "weekday": weekday, "time": when,
            "venue": venue, "court": court,
            "home_team": ihtml.unescape(home.strip()), "home_team_id": home_id,
            "home_score": home_score, "home_winner": status == "FINAL" and "winner" in cls_h,
            "away_team": ihtml.unescape(away.strip()), "away_team_id": away_id,
            "away_score": away_score, "away_winner": status == "FINAL" and "winner" in cls_a,
            "status": status,
        })
    return games


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event_id")
    parser.add_argument("slug")
    parser.add_argument("out_dir", nargs="?", default="data")
    parser.add_argument("--base-url", default=BASE,
                        help="event host, including a tenant-specific FastBreak host")
    args = parser.parse_args(argv)
    event_id, slug = args.event_id, args.slug
    out_dir = Path(args.out_dir)
    url0 = f"{args.base_url.rstrip('/')}/event/{event_id}-{slug}"
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
            "published": info.get("published"),
            "url": url0}
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
           "scraped_at": dt.datetime.now(dt.timezone.utc).isoformat(),
           "divisions": div_list, "games": all_games}
    path = out_dir / f"fb_{event_id}.json"
    path.write_text(json.dumps(out, indent=1))
    scored = sum(1 for g in all_games if g["home_score"] is not None)
    print(f"wrote {path}: {len(all_games)} games ({scored} scored)")


if __name__ == "__main__":
    main()
