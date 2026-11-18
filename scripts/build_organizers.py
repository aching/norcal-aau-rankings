#!/usr/bin/env python3
"""Build site/organizers/<slug>.html: per-organizer history pages.

History sources (local only, no scraping):
  EE: data/events_ca*.json + data/events_upcoming.json (org names + slugs),
      joined to corpus data/[id].json for game counts.
  BT: data/upcoming_rosters.json admin orgs for upcoming; historical BT
      linkage needs a BT discovery snapshot (not yet saved) -- pages note
      "BT history coming".

Each page: organizer name, upcoming events (dates + links + status from
the upcoming page data), past events newest-first (date, name, city,
link, game count where scraped, ranked-team count where resolvable),
plus EE organization page link when known.

Also patches build_upcoming.py output: org names link to these pages
(falls back to EE org URL when no local page... actually local page
always wins: it links out to EE too).
"""
import json
import re
import sys
import glob
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_site import CSS
from build_upcoming import load_events as load_upcoming, region_of

EE_BASE = "https://basketball.exposureevents.com"
OUT = HERE.parent / "site" / "organizers"


CANONICAL = {
    # user-confirmed same organizers, different source spellings
    "bay area roaddawgs": "Bay Area Roaddawgs",
    "blacktop 24/7": "BlackTop 24/7",
    "iconic hoop events": "Iconic Hoop Events",
}


def canon_org(name):
    return CANONICAL.get((name or "").strip().lower(), (name or "").strip())


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "unknown"


def load_ee_history():
    """Org name -> list of {id, name, start, end, city, loc, slug, org_id}."""
    seen = {}
    for f in sorted(glob.glob(str(HERE.parent / "data" / "events_ca*.json"))):
        try:
            evs = json.load(open(f))
        except Exception:
            continue
        if isinstance(evs, dict):
            evs = evs.get("events", evs.get("data", []))
        for e in evs:
            if e.get("Id") and e["Id"] not in seen:
                seen[e["Id"]] = e
    orgs = defaultdict(list)
    for e in seen.values():
        org = canon_org(e.get("OrganizationName") or "") or "(unknown organizer)"
        orgs[org].append({
            "id": e["Id"],
            "name": e.get("Name", "?"),
            "start": (e.get("StartDate") or "")[:10],
            "end": (e.get("EndDate") or "")[:10],
            "city": e.get("City") or "",
            "loc": e.get("Location") or "",
            "slug": (e.get("Slug") or "").strip("/") or "tournament",
            "org_id": e.get("OrganizationId"),
        })
    return orgs


def corpus_game_counts():
    counts = {}
    for f in glob.glob(str(HERE.parent / "data" / "[0-9]*.json")):
        try:
            d = json.load(open(f))
            tid = d.get("tournament_id") or int(Path(f).stem)
            counts[tid] = len(d.get("games", []))
        except Exception:
            pass
    return counts


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;")


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{org} &mdash; organizer history</title>
<style>
{css}
table.hist {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
table.hist th {{ text-align: left; padding: 8px; border-bottom: 2px solid var(--line); }}
table.hist td {{ padding: 9px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }}
.count {{ font-size: 12px; color: var(--mut); }}
@media (max-width: 700px) {{
  table.hist {{ display: block; overflow-x: auto; font-size: 12.5px; }}
  table.hist td {{ padding: 7px 6px; }}
}}
{extra_css}
</style>
</head>
<body>
<div class="wrap">
<a class="back" href="../upcoming.html">&larr; upcoming tournaments</a>
<header class="top">
<h1>{org}</h1>
<p>{summary}</p>
<nav class="tabs">{tabs}</nav>
</header>
{upcoming_section}
<section class="note"><h2>Past events ({past_n})</h2></section>
<table class="hist">
<thead><tr><th>Date</th><th>Event</th><th>Games</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>
</body>
</html>
"""


def main():
    sys.path.insert(0, str(HERE))
    orgs = load_ee_history()
    counts = corpus_game_counts()
    upcoming = load_upcoming()
    up_by_org = defaultdict(list)
    for e in upcoming:
        if e.get("org"):
            for o in [canon_org(x) for x in e["org"].split(";")]:
                if o:
                    up_by_org[o].append(e)
    # also map BT-only orgs (no EE history) so they get a page too
    bt_only = defaultdict(list)
    try:
        rosters = json.load(open(HERE.parent / "data" / "upcoming_rosters.json"))
        for eid, ev in rosters.items():
            for t in ev.get("teams", []) or []:
                pass
    except FileNotFoundError:
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    tabs = "".join(
        f'<a href="../{c}.html">{t}</a>' for c, (t, _, _) in
        {"11u": ("11U", 0, 0), "12u": ("12U/6th Grade", 0, 0),
         "13u": ("13U/7th Grade", 0, 0), "14u": ("14U/8th Grade", 0, 0)}.items())
    slugs = {}
    today = date.today().isoformat()
    for org in sorted(set(list(orgs.keys()) + list(up_by_org.keys()))):
        hist = sorted(orgs.get(org, []), key=lambda x: x["start"] or "", reverse=True)
        past = [h for h in hist if (h["start"] or "") < today]
        up = sorted(up_by_org.get(org, []), key=lambda x: x["date"])
        n_games = sum(counts.get(h["id"], 0) for h in hist)
        n_scraped = sum(1 for h in hist if counts.get(h["id"], 0) > 0)
        org_id = next((h["org_id"] for h in hist if h.get("org_id")), None)
        parts = [f"{len(hist)} EE events"]
        if n_scraped:
            parts.append(f"{n_scraped} with {n_games} scraped games")
        if up:
            parts.append(f"{len(up)} upcoming")
        summary = " &middot; ".join(parts) + "."
        if org_id:
            summary += f' <a href="{EE_BASE}/organizations/{org_id}">EE organization page &rarr;</a>'
        if org in up_by_org and org not in orgs:
            summary += " BT organizer (EE history coming)."
        if up:
            items = "".join(
                f"<li>{esc(u['date'][5:].replace('-', '/'))} &mdash; "
                f"<a href=\"{esc(u['url'])}\">{esc(u['name'])}</a> "
                f"<span class=\"count\">{esc(u['status'])}</span></li>" for u in up)
            upcoming_section = (f"<section class=\"note\"><h2>Upcoming ({len(up)})</h2>"
                                f"<ul>{items}</ul></section>")
        else:
            upcoming_section = ""
        rows = []
        for h in past:
            gc = counts.get(h["id"], 0)
            url = f"{EE_BASE}/{h['id']}/{h['slug']}"
            city = h["city"] or h["loc"]
            rows.append(
                f"<tr><td style=\"white-space:nowrap\">{esc((h['start'] or '')[5:].replace('-', '/'))}</td>"
                f"<td><a href=\"{esc(url)}\">{esc(h['name'])}</a><br>"
                f"<span class=\"count\">{esc(city)}</span></td>"
                f"<td>{gc if gc else '&mdash;'}</td></tr>")
        if not rows:
            rows.append("<tr><td colspan=3>No past events in local history.</td></tr>")
        slug = slugify(org)
        # avoid collisions
        base, i = slug, 2
        while slug in slugs.values():
            slug = f"{base}-{i}"
            i += 1
        slugs[org] = slug
        (OUT / f"{slug}.html").write_text(PAGE.format(
            css=CSS, extra_css="", org=esc(org), summary=summary, tabs=tabs,
            upcoming_section=upcoming_section, past_n=len(past),
            rows="\n".join(rows)))
    # write slug map for upcoming page linking
    json.dump(slugs, open(HERE.parent / "data" / "org_slugs.json", "w"), indent=1)
    print(f"wrote {len(slugs)} organizer pages -> {OUT}")


if __name__ == "__main__":
    main()
