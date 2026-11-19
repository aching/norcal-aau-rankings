#!/usr/bin/env python3
"""Build site/upcoming.html: filterable 3-month lookahead of NorCal tournaments.

Inputs:
  /tmp/ee_status.json  (EE discovery + division probes; probe may be absent)
  /tmp/bt_upcoming.json (BT discovery payloads)

Region mapping: Bay Area sub-areas per user request (Oakland, South Bay,
Peninsula, Hayward area, SF, Walnut Creek / Tri-Valley, Alameda / East Bay)
plus North Bay, Central Valley / Sac, Santa Cruz / Monterey spillover.

Status semantics:
  EE: divisions published count (schedule page lists N divisions). Teams and
      schedule detail requires per-division XHR (rate-limited) -- shows
      "check event page" until the refresh pipeline records it.
  BT: teams listed = paid_teams_count>0; schedule posted = has_matches/games.
"""
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_site import CSS

EE_BASE = "https://basketball.exposureevents.com"

REGION_ORDER = [
    "Oakland", "SF", "Alameda / East Bay", "Hayward area",
    "Walnut Creek / Tri-Valley", "Peninsula", "South Bay",
    "North Bay", "Santa Cruz / Monterey", "Central Valley / Sac",
    "Other NorCal",
]

CITY_TO_REGION = {
    "oakland": "Oakland",
    "san francisco": "SF",
    "alameda": "Alameda / East Bay", "berkeley": "Alameda / East Bay",
    "emeryville": "Alameda / East Bay", "albany": "Alameda / East Bay",
    "hayward": "Hayward area", "san leandro": "Hayward area",
    "union city": "Hayward area", "newark": "Hayward area",
    "castro valley": "Hayward area",
    "walnut creek": "Walnut Creek / Tri-Valley", "concord": "Walnut Creek / Tri-Valley",
    "pleasant hill": "Walnut Creek / Tri-Valley", "martinez": "Walnut Creek / Tri-Valley",
    "clayton": "Walnut Creek / Tri-Valley", "danville": "Walnut Creek / Tri-Valley",
    "san ramon": "Walnut Creek / Tri-Valley", "dublin": "Walnut Creek / Tri-Valley",
    "livermore": "Walnut Creek / Tri-Valley", "pleasanton": "Walnut Creek / Tri-Valley",
    "san mateo": "Peninsula", "redwood": "Peninsula", "burlingame": "Peninsula",
    "san carlos": "Peninsula", "belmont": "Peninsula", "daly city": "Peninsula",
    "san bruno": "Peninsula", "foster city": "Peninsula", "menlo park": "Peninsula",
    "palo alto": "Peninsula", "east palo alto": "Peninsula",
    "san jose": "South Bay", "santa clara": "South Bay", "milpitas": "South Bay",
    "campbell": "South Bay", "los gatos": "South Bay", "saratoga": "South Bay",
    "cupertino": "South Bay", "sunnyvale": "South Bay", "mountain view": "South Bay",
    "los altos": "South Bay", "gilroy": "South Bay", "morgan hill": "South Bay",
    "hollister": "South Bay",
    "santa cruz": "Santa Cruz / Monterey", "watsonville": "Santa Cruz / Monterey",
    "salinas": "Santa Cruz / Monterey", "monterey": "Santa Cruz / Monterey",
    "san rafael": "North Bay", "novato": "North Bay", "santa rosa": "North Bay",
    "napa": "North Bay", "petaluma": "North Bay", "vallejo": "North Bay",
    "fairfield": "North Bay", "vacaville": "North Bay", "marin": "North Bay",
    "suisun city": "North Bay",
    "sacramento": "Central Valley / Sac", "elk grove": "Central Valley / Sac",
    "roseville": "Central Valley / Sac", "stockton": "Central Valley / Sac",
    "modesto": "Central Valley / Sac", "tracy": "Central Valley / Sac",
    "manteca": "Central Valley / Sac", "lodi": "Central Valley / Sac",
    "davis": "Central Valley / Sac", "rocklin": "Central Valley / Sac",
    "folsom": "Central Valley / Sac", "chico": "Central Valley / Sac",
    "oroville": "Central Valley / Sac", "pittsburg": "Central Valley / Sac",
    "antioch": "Central Valley / Sac", "brentwood": "Central Valley / Sac",
    "bay area": "Walnut Creek / Tri-Valley",
}


def region_of(cities):
    for c in cities:
        cl = (c or "").lower().strip()
        for key, reg in CITY_TO_REGION.items():
            if key in cl:
                return reg
    return "Other NorCal"


def load_events():
    events = []
    try:
        ee = json.load(open("/tmp/ee_status.json"))
    except FileNotFoundError:
        ee = []
    for e in ee:
        tid = e["Id"]
        slug = (e.get("Slug") or "").strip("/") or "tournament"
        probe = e.get("probe") or {}
        divs = e.get("ee_divs", 0)
        if isinstance(probe, dict) and probe.get("divs_with_games"):
            status = f"schedule posted ({probe['games_total']} games, {probe['divs_with_games']} divs)"
            teams = f"{probe.get('teams_total', 0)} teams listed" if probe.get("teams_total") else "teams TBA"
        elif isinstance(probe, dict) and probe.get("divs_with_teams"):
            status = "teams posted, schedule TBA"
            teams = f"{probe.get('teams_total', 0)} teams listed"
        elif divs:
            status = f"{divs} divisions published, teams/schedule TBA"
            teams = "check event page"
        else:
            status = "announced, divisions TBA"
            teams = "check event page"
        events.append({
            "date": (e.get("StartDate") or "")[:10],
            "end": (e.get("EndDate") or "")[:10],
            "name": e.get("Name", "?"),
            "org": canon_org(e.get("OrganizationName") or ""),
            "org_url": f"{EE_BASE}/organizations/{e['OrganizationId']}" if e.get("OrganizationId") else "",
            "city": e.get("City") or e.get("Location") or "",
            "region": region_of([e.get("City") or "", e.get("Location") or ""]),
            "src": "EE",
            "url": f"{EE_BASE}/{tid}/{slug}",
            "status": status,
            "teams": teams,
        })
    try:
        bt = json.load(open("/tmp/bt_upcoming.json"))
    except FileNotFoundError:
        bt = []
    for e in bt:
        venues = e.get("venues") or []
        cities = [v.get("city", "") for v in venues if isinstance(v, dict) and v.get("city")]
        city = "; ".join(dict.fromkeys(cities)) or "NorCal"
        paid = e.get("paid_teams_count") or 0
        games = e.get("games_count") or 0
        has_m = e.get("has_matches")
        if has_m and games:
            status = f"schedule posted ({games} games)"
        elif paid:
            status = "teams posted, schedule TBA"
        else:
            status = "announced, teams/schedule TBA"
        teams = f"{paid} paid teams" if paid else "no teams listed yet"
        pub = (e.get("public_url") or {}).get("absolute") or f"https://bracketteam.com/event/{e.get('id')}"
        admins = e.get("administrators") or []
        orgs = sorted({canon_org(a.get("organization_name")) for a in admins
                       if isinstance(a, dict) and (a.get("organization_name") or "").strip()})
        events.append({
            "date": str(e.get("start_date") or "")[:10],
            "end": str(e.get("end_date") or "")[:10],
            "name": e.get("event_name", "?"),
            "org": "; ".join(orgs),
            "org_url": "",
            "city": city,
            "region": region_of(cities),
            "src": "BT",
            "url": pub,
            "status": status,
            "teams": teams,
        })
    events = [e for e in events if e["date"]]
    events.sort(key=lambda x: (x["date"], x["name"]))
    return events


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Upcoming NorCal Tournaments &mdash; next 3 months</title>
<style>
{css}
.filters {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 14px 0; }}
.filters button {{ padding: 7px 14px; border: 1px solid var(--line); border-radius: 999px;
  background: #fff; font-size: 13.5px; cursor: pointer; }}
.filters button.on {{ background: var(--fg); color: #fff; border-color: var(--fg); }}
table.upcoming {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
table.upcoming th {{ text-align: left; padding: 8px; border-bottom: 2px solid var(--line);
  position: sticky; top: 0; background: var(--bg); }}
table.upcoming td {{ padding: 9px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }}
.src {{ font-size: 11px; color: var(--mut); border: 1px solid var(--line); border-radius: 4px;
  padding: 1px 5px; white-space: nowrap; }}
.st-posted {{ color: #1a7f37; font-weight: 600; }}
.st-tba {{ color: #9a6700; }}
@media (max-width: 700px) {{
  table.upcoming {{ display: block; overflow-x: auto; font-size: 12.5px; }}
  table.upcoming td {{ padding: 7px 6px; }}
}}
</style>
</head>
<body>
<div class="wrap">
<a class="back" href="index.html">&larr; rankings hub</a>
<header class="top">
<h1>Upcoming NorCal Tournaments</h1>
<p>{window} &middot; {count} events &middot; generated {gen}. Status re-checked on rebuild;
EE teams/schedule detail needs the event page until the refresh pipeline records it.</p>
<nav class="tabs">{tabs}</nav>
<div class="filters" id="reg">
<button data-r="all" class="on">All regions</button>
{region_buttons}
</div>
</header>
<table class="upcoming">
<thead><tr><th>Date</th><th>Event</th><th>Organizer</th><th>Area</th><th>Status</th><th>Teams</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>
<script>
const btns = document.querySelectorAll('#reg button');
const rows = document.querySelectorAll('tbody tr');
btns.forEach(b => b.addEventListener('click', () => {{
  btns.forEach(x => x.classList.remove('on'));
  b.classList.add('on');
  const r = b.dataset.r;
  rows.forEach(tr => {{ tr.style.display = (r === 'all' || tr.dataset.region === r) ? '' : 'none'; }});
}}));
</script>
</body>
</html>
"""


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;")


ORG_CANONICAL = {
    "bay area roaddawgs": "Bay Area Roaddawgs",
    "blacktop 24/7": "BlackTop 24/7",
    "iconic hoop events": "Iconic Hoop Events",
}


def canon_org(name):
    return ORG_CANONICAL.get((name or "").strip().lower(), (name or "").strip())


def org_slugs():
    try:
        return json.load(open(HERE.parent / "data" / "org_slugs.json"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main():
    events = load_events()
    gen = date.today().isoformat()
    tabs = "".join(
        f'<a href="{c}.html">{t}</a>' for c, (t, _, _) in
        {"11u": ("11U", 0, 0), "12u": ("12U/6th Grade", 0, 0),
         "13u": ("13U/7th Grade", 0, 0), "14u": ("14U/8th Grade", 0, 0), "15u": ("15U/9th Grade", 0, 0)}.items())
    tabs += '<a href="upcoming.html" class="on">Upcoming</a><a href="organizers.html">Organizers</a><a href="clubs.html">Clubs</a>'
    present = [r for r in REGION_ORDER if any(e["region"] == r for e in events)]
    region_buttons = "".join(f'<button data-r="{r}">{r}</button>' for r in present)
    slugs = org_slugs()
    rows = []
    for e in events:
        st_cls = "st-posted" if "schedule posted" in e["status"] else ("st-tba" if "TBA" in e["status"] else "")
        d = e["date"][5:].replace("-", "/")
        parts = []
        for o in [x.strip() for x in (e.get("org") or "").split(";")]:
            if not o:
                continue
            if o in slugs:
                parts.append(f'<a href="organizers/{slugs[o]}.html">{esc(o)}</a>')
            elif e.get("org_url"):
                parts.append(f'<a href="{esc(e["org_url"])}">{esc(o)}</a>')
            else:
                parts.append(esc(o))
        org = "; ".join(parts)
        rows.append(
            f'<tr data-region="{esc(e["region"])}">'
            f'<td style="white-space:nowrap">{d}</td>'
            f'<td><a href="{esc(e["url"])}">{esc(e["name"])}</a> <span class="src">{e["src"]}</span><br>'
            f'<span style="color:var(--mut);font-size:12.5px">{esc(e["city"])}</span></td>'
            f'<td>{org}</td>'
            f'<td>{esc(e["region"])}</td>'
            f'<td class="{st_cls}">{esc(e["status"])}</td>'
            f'<td>{esc(e["teams"])}</td></tr>')
    window = f"{events[0]['date']} -- {events[-1]['date']}" if events else "no events"
    out = HERE.parent / "site" / "upcoming.html"
    out.write_text(PAGE.format(css=CSS, tabs=tabs, window=esc(window),
                               count=len(events), gen=gen,
                               region_buttons=region_buttons, rows="\n".join(rows)))
    print(f"wrote {out} ({len(events)} events)")


if __name__ == "__main__":
    main()
