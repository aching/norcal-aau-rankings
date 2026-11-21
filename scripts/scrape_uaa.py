#!/usr/bin/env python3
"""Collect 2026 UAA/UAA Rise results from the official public pages.

The public WordPress pages embed box-score tables in rendered HTML. Responses
are cached verbatim under data/; re-parsing does not require network access.
"""
import argparse
import csv
import datetime as dt
import hashlib
import html as html_lib
import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

UA = "AAU-Basketball-Aggregator/0.1 (avery@aptoslabs.com)"
API = "https://underarmournext.com/wp-json/wp/v2/pages"
PAGES = ("boys-uaa", "boys-rise", "girls-uaa", "girls-rise")
RAW_DIR = Path("data/uaa_pages")
OUT = Path("data/circuits_2026_uaa.csv")
FIELDS = ["source", "circuit", "series", "gender", "division", "event_id",
          "event", "session", "date", "time", "game_type", "home_team",
          "away_team", "home_score", "away_score", "home_won", "away_won",
          "status", "venue", "court", "game_id", "home_team_id",
          "away_team_id", "url", "source_pages"]


def text(value):
    return html_lib.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def attr(attrs, name):
    match = re.search(rf"\b{name}=([\"'])(.*?)\1|\b{name}=([^\s>]+)", attrs, re.S)
    if not match:
        return ""
    value = match.group(2) if match.group(1) else match.group(3)
    return html_lib.unescape(value)


def team_key(value):
    return re.sub(r"\s+", "", html_lib.unescape(value)).lower()


def parse_page(page, slug):
    source_html = page["content"]["rendered"]
    wrapper_re = re.compile(r"<div class='synGamesWrapper(?: ([^']+))?'>")
    wrappers = list(wrapper_re.finditer(source_html))
    records = []
    for i, wrapper in enumerate(wrappers):
        end = wrappers[i + 1].start() if i + 1 < len(wrappers) else len(source_html)
        section = source_html[wrapper.end():end]
        prefix = source_html[max(0, wrapper.start() - 2500):wrapper.start()]
        headings = re.findall(r'ToggleSubheaderH2CustomHighlight">(.*?)</div>', prefix, re.S)
        heading = text(headings[-1]) if headings else slug
        division_match = re.search(r"(1[4-8]U)", heading, re.I)
        division = division_match.group(1).upper() if division_match else heading
        sessions = list(re.finditer(
            r"<div class='ozaccbtn small'[^>]*>\s*(.*?)\s*</div>", section, re.S))
        for j, session_match in enumerate(sessions):
            session_end = sessions[j + 1].start() if j + 1 < len(sessions) else len(section)
            session_html = section[session_match.end():session_end]
            session_label = text(session_match.group(1))
            date_match = (re.search(r"(\d{2})\.(\d{2})\.(\d{4})", session_label)
                          or re.search(r"(\d{2})\s+(\d{2}),\s+(\d{4})", session_label))
            if not date_match:
                continue
            date = dt.date(int(date_match.group(3)), int(date_match.group(1)),
                           int(date_match.group(2))).isoformat()
            session = re.sub(
                r"\s*[–-]?\s*(?:\d{2}\.\d{2}\.\d{4}|\d{2}\s+\d{2},\s+\d{4})\s*$",
                "", session_label).strip()
            game_re = re.compile(
                r"<div class='synGame'\s+([^>]+)>(.*?)(?=<div class='synGame'|\Z)", re.S)
            for game in game_re.finditer(session_html):
                attrs, body = game.groups()
                home_id, away_id = attr(attrs, "data-home"), attr(attrs, "data-away")
                link_match = re.search(r"class='gameLink' href='([^']+)'", body)
                box_url = html_lib.unescape(link_match.group(1)) if link_match else ""
                box_url = (urllib.parse.urljoin("https://underarmournext.com", box_url)
                           if box_url else f"https://underarmournext.com/basketball/{slug}/")
                sgid = urllib.parse.parse_qs(urllib.parse.urlsplit(box_url).query).get("sgid", [""])[0]
                team_re = re.compile(
                    r"<div class='synTeamResults([^']*)'>\s*"
                    r"<div class='synTeam team-([^']*)'[^>]*>(.*?)</div>\s*"
                    r"<div class='synScore'>(.*?)</div>", re.S)
                team_rows = []
                for team in team_re.finditer(body):
                    result_class, team_id, name, score = team.groups()
                    team_rows.append({"key": team_key(team_id), "name": text(name),
                                      "score": text(score),
                                      "won": 1 if "bold" in result_class.split() else 0})
                teams = {row["key"]: row for row in team_rows}
                home = teams.get(team_key(home_id))
                away = teams.get(team_key(away_id))
                # Some 14U rows use display names as IDs and normalize spaces
                # differently in the class attribute. Source order is home, away.
                if home is None and away is None and len(team_rows) == 2:
                    home, away = team_rows
                home = home or {"name": "", "score": "", "won": None}
                away = away or {"name": "", "score": "", "won": None}
                series = "Rise" if slug.endswith("-rise") else "UAA"
                gender = "boys" if slug.startswith("boys-") else "girls"
                event_id = f"{gender}-{division.lower()}"
                records.append({
                    "source": "underarmournext", "circuit": "UAA", "series": series,
                    "gender": gender, "division": division, "event_id": event_id,
                    "event": f"{gender.title()} {division} {series}",
                    "session": session, "date": date, "time": "", "game_type": session,
                    "home_team": home["name"], "away_team": away["name"],
                    "home_score": home["score"], "away_score": away["score"],
                    "home_won": home["won"], "away_won": away["won"],
                    "status": "Final" if home["score"] and away["score"] else "Scheduled",
                    "venue": "", "court": "", "game_id": sgid,
                    "home_team_id": home_id, "away_team_id": away_id,
                    "url": box_url, "source_pages": slug,
                    "_source_index": len(records),
                })
    expected = source_html.count("<div class='synGame'")
    if expected != len(records):
        raise ValueError(f"{slug}: found {expected} game containers but parsed {len(records)}")
    return records


def fetch_or_load(slug, offline=False):
    path = RAW_DIR / f"{slug}.json"
    if path.exists():
        return json.loads(path.read_text())["page"]
    if offline:
        raise FileNotFoundError(f"missing offline cache: {path}")
    params = urllib.parse.urlencode({"slug": slug, "_fields": "id,modified,content"})
    url = API + "?" + params
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=60) as response:
        page = json.load(response)[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"source_url": url,
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "page": page}, indent=2) + "\n")
    return page


def main(offline=False):
    games = {}
    seen = Counter()
    for i, slug in enumerate(PAGES):
        if i and not (RAW_DIR / slug).exists():
            time.sleep(10)  # Official robots.txt Crawl-delay: 10.
        page = fetch_or_load(slug, offline)
        records = parse_page(page, slug)
        seen[slug] = len(records)
        for record in records:
            key = record["game_id"] or (
                record["gender"], record["division"], record["session"], record["date"],
                record["home_team_id"], record["away_team_id"], record["_source_index"])
            if key in games:
                prior = games[key]
                fields = ("date", "division", "home_team_id", "away_team_id", "home_score", "away_score")
                if any(prior[f] != record[f] for f in fields):
                    raise ValueError(f"conflicting duplicate UAA game: {key}")
                prior["series"] = "+".join(sorted(set(prior["series"].split("+") + [record["series"]])))
                prior["source_pages"] = "+".join(sorted(set(prior["source_pages"].split("+") + [slug])))
                prior["event"] = f"{prior['gender'].title()} {prior['division']} {prior['series']}"
            else:
                if not record["game_id"]:
                    digest = hashlib.sha1(repr(key).encode("utf-8")).hexdigest()[:20]
                    record["game_id"] = "uaa-fallback-" + digest
                games[key] = record
    rows = [
        {field: record.get(field, "") for field in FIELDS}
        for record in sorted(games.values(), key=lambda r: (
            r["date"], r["gender"], r["division"], r["series"], r["session"], r["game_id"]))
    ]
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    Path("data/uaa_2026_games.json").write_text(json.dumps(rows, indent=2) + "\n")
    print("fetched/parsed:", dict(seen))
    print(f"wrote {OUT} and data/uaa_2026_games.json: {len(rows)} deduplicated games")
    for group in sorted(set((r["gender"], r["division"], r["series"]) for r in rows)):
        print(group, sum(1 for r in rows if (r["gender"], r["division"], r["series"]) == group))
    incomplete = sum(1 for r in rows if not r["home_team"] or not r["away_team"]
                     or not r["home_score"] or not r["away_score"])
    print("incomplete source rows:", incomplete)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="only use cached responses")
    args = parser.parse_args()
    main(offline=args.offline)
