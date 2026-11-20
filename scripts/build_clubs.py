#!/usr/bin/env python3
"""Build site/clubs/<slug>.html: per-club squad pages + site/clubs.html index.

Club = program family via build_site.club_of (TM, Soldiers, BMG,
Lakeshow, ...). Each page lists every squad with a team page, grouped
ranked-first: board rank, score, window W-L, tier, SOS, cohort, link.
Unranked squads listed with links. Index ranked by (# ranked squads
desc, best rank asc).

Sources (local only): site/<cohort>.html board DATA (ranked stats),
build_site.all_pages_map (every team page incl. unranked).
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_site import CSS, club_of, all_pages_map
from html_utils import esc

OUT = HERE.parent / "site" / "clubs"
COHORT_ORDER = ["11u", "12u", "13u", "14u", "15u"]
COHORT_LABEL = {"11u": "11U", "12u": "12U/6th", "13u": "13U/7th",
                "14u": "14U/8th", "15u": "15U/9th"}



def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "club"


def load_boards():
    """team_id -> {rank, score, wl, tier, sos, cohort} for ranked teams."""
    info = {}
    for cohort in COHORT_ORDER:
        p = HERE.parent / "site" / f"{cohort}.html"
        if not p.exists():
            continue
        m = re.search(r"const DATA = (\[.*?\]);\nlet sortKey", p.read_text(), re.S)
        if not m:
            continue
        for r in json.loads(m.group(1)):
            if r.get("rank"):
                info[r["team"]] = {
                    "rank": r["rank"], "score": r["score"], "wl": r["wl"],
                    "tier": r["tier"], "sos": r["sos"], "cohort": cohort,
                }
    return info


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{club} &mdash; club squads</title>
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
</style>
</head>
<body>
<div class="wrap">
<a class="back" href="../clubs.html">&larr; all clubs</a>
<header class="top">
<h1>{club}</h1>
<p>{summary}</p>
<nav class="tabs">{tabs}</nav>
</header>
<table class="hist">
<thead><tr><th>#</th><th>Squad</th><th>Score</th><th>W-L</th><th>Tier</th><th>Age</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
{unranked_section}
</div>
</body>
</html>
"""


def main():
    pmap = all_pages_map()
    info = load_boards()
    clubs = defaultdict(list)
    for tid in pmap:
        clubs[club_of(tid)].append(tid)
    # pages only for clubs with 2+ squads having pages AND at least
    # one ranked squad (kills 400+ noise buckets of two unranked teams
    # sharing a first token). Unranked squads still listed on kept pages.
    clubs = {c: v for c, v in clubs.items()
             if len(v) > 1 and any(t in info for t in v)}
    OUT.mkdir(parents=True, exist_ok=True)
    tabs = "".join(
        f'<a href="../{c}.html">{t}</a>' for c, (t, _, _) in
        {"11u": ("11U", 0, 0), "12u": ("12U/6th Grade", 0, 0),
         "13u": ("13U/7th Grade", 0, 0), "14u": ("14U/8th Grade", 0, 0),
         "15u": ("15U/9th Grade", 0, 0)}.items())
    tabs += ('<a href="../upcoming.html">Upcoming</a>'
             '<a href="../organizers.html">Organizers</a>')
    slugs = {}
    for club in sorted(clubs):
        tids = clubs[club]
        ranked = sorted(
            ((info[t]["rank"], t) for t in tids if t in info),
            key=lambda x: x[0])
        unranked = sorted(t for t in tids if t not in info)
        slug = slugify(club)
        base, i = slug, 2
        while slug in slugs.values():
            slug = f"{base}-{i}"
            i += 1
        slugs[club] = slug
        rows = []
        for rk, t in ranked:
            d = info[t]
            coh, fn = pmap[t]
            rows.append(
                f"<tr><td>{rk}</td>"
                f"<td><a href=\"../teams/{coh}/{fn}\">{esc(t)}</a></td>"
                f"<td>{d['score']:.3f}</td><td>{esc(d['wl'])}</td>"
                f"<td>{esc(d['tier'])}</td><td>{COHORT_LABEL[coh]}</td></tr>")
        if unranked:
            items = "".join(
                f"<li><a href=\"../teams/{pmap[t][0]}/{pmap[t][1]}\">{esc(t)}</a> "
                f"({COHORT_LABEL[pmap[t][0]]}, unranked)</li>"
                for t in unranked)
            unranked_section = (
                f"<section class=\"note\"><h2>Unranked squads "
                f"({len(unranked)})</h2><ul>{items}</ul></section>")
        else:
            unranked_section = ""
        best = f"best #{ranked[0][0]}" if ranked else "no ranked squads"
        summary = (f"{len(tids)} squads with pages &middot; {len(ranked)} ranked "
                   f"({best}) &middot; cross-age links on every squad page.")
        (OUT / f"{slug}.html").write_text(PAGE.format(
            css=CSS, club=esc(club), summary=summary, tabs=tabs,
            rows="\n".join(rows) if rows else
            "<tr><td colspan=6>No ranked squads.</td></tr>",
            unranked_section=unranked_section))
    # index: # ranked desc, best rank asc
    def sort_key(club):
        tids = clubs[club]
        ranks = [info[t]["rank"] for t in tids if t in info]
        return (-len(ranks), min(ranks) if ranks else 10 ** 9)
    idx_rows = []
    for club in sorted(clubs, key=sort_key):
        tids = clubs[club]
        ranks = sorted(info[t]["rank"] for t in tids if t in info)
        cohs = sorted(set(pmap[t][0] for t in tids),
                      key=lambda c: COHORT_ORDER.index(c))
        idx_rows.append(
            f"<tr><td>{len(ranks)}</td>"
            f"<td><a href=\"clubs/{slugs[club]}.html\">{esc(club)}</a></td>"
            f"<td>{min(ranks) if ranks else '&mdash;'}</td>"
            f"<td>{len(tids)}</td>"
            f"<td>{', '.join(COHORT_LABEL[c] for c in cohs)}</td></tr>")
    idx_tabs = "".join(
        f'<a href="{c}.html">{t}</a>' for c, (t, _, _) in
        {"11u": ("11U", 0, 0), "12u": ("12U/6th Grade", 0, 0),
         "13u": ("13U/7th Grade", 0, 0), "14u": ("14U/8th Grade", 0, 0),
         "15u": ("15U/9th Grade", 0, 0)}.items())
    idx_html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Clubs &mdash; squads by program</title>
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
<h1>Clubs</h1>
<p>{len(clubs)} programs with 2+ squads, ranked by ranked-squad count then best rank.</p>
<nav class="tabs">{idx_tabs}<a href="upcoming.html">Upcoming</a><a href="organizers.html">Organizers</a><a href="clubs.html" class="on">Clubs</a></nav>
</header>
<table class="hist">
<thead><tr><th>Ranked</th><th>Club</th><th>Best</th><th>Squads</th><th>Ages</th></tr></thead>
<tbody>
{"".join(idx_rows)}
</tbody>
</table>
</div>
</body>
</html>"""
    (HERE.parent / "site" / "clubs.html").write_text(idx_html)
    json.dump(slugs, open(HERE.parent / "data" / "club_slugs.json", "w"), indent=1)
    print(f"wrote {len(slugs)} club pages + index")


if __name__ == "__main__":
    main()
