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
from team_identity import resolve
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


def corpus_participants():
    """tournament_id -> {division: [team names]} from scraped corpus games.

    EE: HomeTeamName/AwayTeamName grouped by _division_name. BT: home_team/
    away_team grouped by division (or _division_name). Names are raw
    registration strings, deduped, sorted.
    """
    parts = {}
    for f in glob.glob(str(HERE.parent / "data" / "[0-9]*.json")):
        is_bt = Path(f).name.startswith("bt_")
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if is_bt:
            tid = d.get("event_id")
        else:
            tid = d.get("tournament_id") or int(Path(f).stem.lstrip("bt_") or 0)
        divs = {}
        for g in d.get("games", []) or []:
            if is_bt:
                div = g.get("division") or g.get("_division_name") or "?"
                names = [g.get("home_team"), g.get("away_team")]
            else:
                div = g.get("_division_name") or g.get("DivisionName") or "?"
                names = [g.get("HomeTeamName"), g.get("AwayTeamName")]
            bucket = divs.setdefault(div, set())
            for n in names:
                if n and str(n).strip():
                    bucket.add(str(n).strip())
        if divs:
            parts[tid] = {k: sorted(v) for k, v in divs.items()}
    return parts


_page_map = None


def team_page_map():
    """team_id -> organizer-relative team page path (../teams/<cohort>/<f>).

    Replicates build_site.build_board's deterministic slug loop over
    game_logs() order, so links match including -1 dedupe suffixes.
    Computed once, cached.
    """
    global _page_map
    if _page_map is not None:
        return _page_map
    from build_site import game_logs, slug_of
    level_arg = {"11u": "11u", "12u": "12u,6th", "13u": "13u,7th", "14u": "14u,8th", "15u": "15u,9th"}
    _page_map = {}
    for cohort, lv in level_arg.items():
        try:
            logs = game_logs(lv, cohort)
        except Exception:
            continue
        seen = set()
        for tid in logs.keys():
            base = slug_of(tid)
            n, cand = 0, ""
            while True:
                cand = (base if n == 0 else f"{base}-{n}") + ".html"
                if cand not in seen:
                    break
                n += 1
            seen.add(cand)
            _page_map[tid] = f"../teams/{cohort}/{cand}"
    return _page_map


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
details {{ margin-top: 4px; }}
summary {{ cursor: pointer; color: var(--mut); font-size: 13px; }}
details div {{ margin: 3px 0 3px 12px; font-size: 13px; }}
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
    participants = corpus_participants()
    try:
        strength = json.load(open(HERE.parent / "data" / "org_strength.json"))
    except (FileNotFoundError, json.JSONDecodeError):
        strength = {}
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
         "13u": ("13U/7th Grade", 0, 0), "14u": ("14U/8th Grade", 0, 0), "15u": ("15U/9th Grade", 0, 0)}.items())
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
                f"[<a href=\"{esc(u['url'])}/schedule\">schedule</a>] "
                f"[<a href=\"{esc(u['url'])}/teams\">teams</a>] "
                f"<span class=\"count\">{esc(u['status'])}</span></li>" for u in up
                if u["src"] == "EE") + "".join(
                f"<li>{esc(u['date'][5:].replace('-', '/'))} &mdash; "
                f"<a href=\"{esc(u['url'])}\">{esc(u['name'])}</a> "
                f"[<a href=\"{esc(u['url'])}\">schedule/teams</a>] "
                f"<span class=\"count\">{esc(u['status'])}</span></li>" for u in up
                if u["src"] != "EE")
            upcoming_section = (f"<section class=\"note\"><h2>Upcoming ({len(up)})</h2>"
                                f"<ul>{items}</ul></section>")
        else:
            upcoming_section = ""
        if org in strength:
            s = strength[org]
            divrows = "".join(
                f"<tr><td>{esc(d['div'])}</td>"
                f"<td>{d['avg']:.3f}</td><td>{d['n']}</td></tr>"
                for d in s["divisions"][:12])
            div_section = (
                f"<section class=\"note\"><h2>Strongest divisions "
                f"(avg ranked-team score, last 365d)</h2></section>"
                f"<table class=\"hist\"><thead><tr><th>Division</th>"
                f"<th>Avg strength</th><th>Teams</th></tr></thead>"
                f"<tbody>{divrows}</tbody></table>")
            summary += (f" Competition strength {s['avg']:.3f} "
                        f"({s['n']} ranked appearances, {s['events']} events).")
        else:
            div_section = ""
        rows = []
        pmap = team_page_map()
        for h in past:
            gc = counts.get(h["id"], 0)
            url = f"{EE_BASE}/{h['id']}/{h['slug']}"
            city = h["city"] or h["loc"]
            who = ""
            divs = participants.get(h["id"])
            if divs:
                n_teams = sum(len(v) for v in divs.values())
                groups = []
                for div in sorted(divs):
                    chips = []
                    for raw in divs[div]:
                        tid, _ = resolve(raw, div)
                        if tid and tid in pmap:
                            chips.append(f"<a href=\"{pmap[tid]}\">{esc(raw)}</a>")
                        else:
                            chips.append(esc(raw))
                    groups.append(f"<div><b>{esc(div)}</b> ({len(divs[div])}): " +
                                  ", ".join(chips) + "</div>")
                who = (f"<details><summary>who played ({n_teams} teams, "
                       f"{len(divs)} divisions)</summary>" +
                       "".join(groups) + "</details>")
            else:
                who = (f"[<a href=\"{esc(url)}/schedule\">schedule</a>] "
                       f"[<a href=\"{esc(url)}/teams\">teams</a>]")
            rows.append(
                f"<tr><td style=\"white-space:nowrap\">{esc((h['start'] or '')[5:].replace('-', '/'))}</td>"
                f"<td><a href=\"{esc(url)}\">{esc(h['name'])}</a> {who}<br>"
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
            upcoming_section=upcoming_section + div_section, past_n=len(past),
            rows="\n".join(rows)))
    # write slug map for upcoming page linking
    json.dump(slugs, open(HERE.parent / "data" / "org_slugs.json", "w"), indent=1)
    print(f"wrote {len(slugs)} organizer pages -> {OUT}")

    # ---- organizers index: ranked by avg strength of field ----
    try:
        strength = json.load(open(HERE.parent / "data" / "org_strength.json"))
    except (FileNotFoundError, json.JSONDecodeError):
        strength = {}
    orows = []
    for i, (org, s) in enumerate(
            sorted(strength.items(), key=lambda kv: -kv[1]["avg"]), 1):
        top = s["divisions"][0] if s["divisions"] else None
        top_txt = f"{top['div']} ({top['avg']:.3f})" if top else "-"
        orows.append(
            f"<tr><td>{i}</td>"
            f"<td><a href=\"organizers/{slugs.get(org, '')}.html\">{esc(org)}</a></td>"
            f"<td>{s['avg']:.3f}</td><td>{s['n']}</td><td>{s['events']}</td>"
            f"<td>{esc(top_txt)}</td></tr>")
    unranked = sorted(o for o in slugs if o not in strength)
    urows = "".join(
        f"<tr><td></td><td><a href=\"organizers/{slugs[o]}.html\">{esc(o)}</a></td>"
        f"<td colspan=4 style=\"color:var(--mut)\">insufficient scraped games "
        f"(need 20+ ranked appearances)</td></tr>" for o in unranked)
    tabs_idx = "".join(
        f'<a href="{c}.html">{t}</a>' for c, (t, _, _) in
        {"11u": ("11U", 0, 0), "12u": ("12U/6th Grade", 0, 0),
         "13u": ("13U/7th Grade", 0, 0), "14u": ("14U/8th Grade", 0, 0), "15u": ("15U/9th Grade", 0, 0)}.items())
    idx_html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Organizers &mdash; ranked by strength of field</title>
<style>
{CSS}
table.hist {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
table.hist th {{ text-align: left; padding: 8px; border-bottom: 2px solid var(--line); }}
table.hist td {{ padding: 9px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }}
@media (max-width: 700px) {{
  table.hist {{ display: block; overflow-x: auto; font-size: 12.5px; }}
  table.hist td {{ padding: 7px 6px; }}
}}
</style>
</head>
<body>
<div class="wrap">
<a class="back" href="index.html">&larr; rankings hub</a>
<header class="top">
<h1>Organizers</h1>
<p>Ranked by avg strength of field: mean ranked-team score over resolved
ranked appearances in scraped events (last 365d, min 20 appearances).
{len(strength)} ranked, {len(unranked)} with insufficient data.</p>
<nav class="tabs">{tabs_idx}<a href="upcoming.html">Upcoming</a><a href="organizers.html" class="on">Organizers</a></nav>
</header>
<table class="hist">
<thead><tr><th>#</th><th>Organizer</th><th>Strength</th><th>Appearances</th><th>Events</th><th>Top division</th></tr></thead>
<tbody>
{"".join(orows) + urows}
</tbody>
</table>
</div>
</body>
</html>"""
    (HERE.parent / "site" / "organizers.html").write_text(idx_html)
    print(f"wrote organizers index ({len(strength)} ranked + {len(unranked)} unranked)")


if __name__ == "__main__":
    main()
