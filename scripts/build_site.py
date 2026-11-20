#!/usr/bin/env python3
"""Static rankings site generator (stdlib only, no install step).

Reads /tmp/rep{11,12,14}.md (output of build_reports.py) and writes a
self-contained static site into site/:

  site/index.html  -- landing with links to the three boards
  site/11u.html, site/12u.html, site/14u.html -- sortable ranking tables

Each board page embeds its data as JSON in the HTML (no fetch needed, so
file:// works) and renders client-side with vanilla JS: sortable columns,
tier filter, and text search. The 5-bullet Why column from the reports
renders as a stacked list per team.

Usage: python3 scripts/build_site.py  (run after build_reports.py)
"""

import json
import re
import subprocess
import sys
from pathlib import Path

from html_utils import esc, external_link, json_for_script

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
OUT = REPO / "site"

COHORTS = {
    "11u": ("11U", "11", "11U boys -- last-15 form, active-only"),
    "12u": ("12U/6th Grade", "12", "12U / 6th grade boys -- last-15 form, active-only"),
    "13u": ("13U/7th Grade", "13", "13U / 7th grade boys -- last-15 form, active-only"),
    "14u": ("14U/8th Grade", "14", "14U / 8th grade boys -- last-15 form, active-only"),
    "15u": ("15U/9th Grade", "15", "15U / 9th grade boys -- last-15 form, active-only"),
}

CSS = """
:root { --bg: #fafafa; --fg: #1a1a1a; --mut: #666; --line: #e2e2e2;
        --acc: #0b5fff; --gold: #8a6d00; }
* { box-sizing: border-box; }
body { font-family: -apple-system, system-ui, "Segoe UI", Helvetica, Arial, sans-serif;
       background: var(--bg); color: var(--fg); margin: 0; padding: 0 16px 64px; }
.wrap { max-width: 1180px; margin: 0 auto; }
header.top { padding: 28px 0 8px; }
header.top h1 { margin: 0 0 4px; font-size: 26px; }
header.top p { margin: 4px 0; color: var(--mut); font-size: 14px; }
nav.tabs { display: flex; gap: 8px; margin: 16px 0 4px; flex-wrap: wrap; }
nav.tabs a { padding: 8px 16px; border: 1px solid var(--line); border-radius: 999px;
             text-decoration: none; color: var(--fg); background: #fff; font-size: 14px; }
nav.tabs a.on { background: var(--fg); color: #fff; border-color: var(--fg); }
.toolbar { display: flex; gap: 12px; align-items: center; margin: 16px 0;
           flex-wrap: wrap; position: sticky; top: 0; background: var(--bg);
           padding: 12px 0; z-index: 5; border-bottom: 1px solid var(--line); }
.toolbar input[type=search] { flex: 1 1 220px; padding: 9px 12px; font-size: 15px;
           border: 1px solid var(--line); border-radius: 8px; }
.toolbar select { padding: 9px 10px; font-size: 14px; border: 1px solid var(--line);
           border-radius: 8px; background: #fff; }
.toolbar .count { color: var(--mut); font-size: 14px; }
table { border-collapse: collapse; width: 100%; font-size: 13.5px; background: #fff; }
thead th { position: sticky; top: 61px; background: #f2f2f2; cursor: pointer;
           text-align: left; padding: 9px 8px; border-bottom: 2px solid #ccc;
           white-space: nowrap; user-select: none; }
thead th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; }
tbody td { padding: 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
tbody tr:hover td { background: #f7faff; }
td.team { font-weight: 600; white-space: nowrap; }
td.team a { color: inherit; }
td.team a:hover { color: var(--acc); }
.tbadge { display: inline-block; font-size: 10.5px; font-weight: 700;
          padding: 1px 8px; border-radius: 999px; margin-right: 8px;
          text-transform: uppercase; letter-spacing: .04em; vertical-align: 1px; }
.t-national { background: #1a1a1a; color: #ffd700; }
.t-up { background: #4b2e83; color: #fff; }
.t-gold { background: #b8860b; color: #fff; }
.t-silver { background: #6c757d; color: #fff; }
.t-bronze { background: #8c5a2b; color: #fff; }
.t-open { background: #e2e2e2; color: #333; }
.badge { display: inline-block; font-size: 11px; padding: 1px 7px; border-radius: 999px;
         background: #eee; margin-left: 6px; vertical-align: 1px; }
.badge.t { background: #fff3bf; color: var(--gold); border: 1px solid #e6cf5c; }
ul.why { margin: 2px 0; padding-left: 18px; }
ul.why li { margin: 1px 0; }
.detail-head { background: #fff; border: 1px solid var(--line); border-radius: 12px;
          padding: 20px 24px; margin: 16px 0; }
.detail-head h2 { margin: 0 0 4px; font-size: 22px; }
.detail-head .sub { color: var(--mut); font-size: 14px; margin: 0; }
table.detail { font-size: 13.5px; }
td.w { font-weight: 700; color: #0a7a2e; }
td.l { font-weight: 700; color: #b3261e; }
.back { display: inline-block; margin-top: 4px; font-size: 14px; }
section.note { margin-top: 28px; }
section.note h2 { font-size: 17px; margin-bottom: 6px; }
section.note p, section.note li { font-size: 14px; }
footer.gen { margin-top: 32px; color: var(--mut); font-size: 12.5px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
         gap: 16px; margin-top: 20px; }
.cards a { display: block; background: #fff; border: 1px solid var(--line);
           border-radius: 12px; padding: 20px; text-decoration: none; color: var(--fg); }
.cards a:hover { border-color: var(--acc); }
.cards h2 { margin: 0 0 6px; font-size: 20px; }
.cards p { margin: 4px 0; color: var(--mut); font-size: 14px; }
.cards .big { font-size: 30px; font-weight: 700; }
/* MOBILE */
@media (max-width: 700px) {
  body { padding: 0 10px 48px; }
  header.top h1 { font-size: 22px; }
  .toolbar { position: static; }
  /* board tables: scroll sideways, keep key columns (#, Team, Score, W-L, Tier, STRK, L10) */
  table:not(.detail) { display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; font-size: 12.5px; }
  table:not(.detail) thead th { top: 0; padding: 7px 6px; }
  table:not(.detail) tbody td { padding: 7px 6px; }
  table:not(.detail) th:nth-child(6), table:not(.detail) td:nth-child(6),
  table:not(.detail) th:nth-child(7), table:not(.detail) td:nth-child(7),
  table:not(.detail) th:nth-child(8), table:not(.detail) td:nth-child(8),
  table:not(.detail) th:nth-child(11), table:not(.detail) td:nth-child(11),
  table:not(.detail) th:nth-child(12), table:not(.detail) td:nth-child(12),
  table:not(.detail) th:nth-child(13), table:not(.detail) td:nth-child(13) { display: none; }
  td.team { white-space: normal; }
  /* team detail tables: scroll sideways */
  table.detail { display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; font-size: 12px; }
  table.detail thead th { top: 0; }
  .detail-head { padding: 16px; }
  .detail-head h2 { font-size: 19px; }
}
/* /MOBILE */
"""

JS = """
const DATA = __DATA__;
let sortKey = "rank", sortDir = 1;
const q = document.getElementById("q");
const tierSel = document.getElementById("tier");
const count = document.getElementById("count");
const tbody = document.getElementById("rows");

function tiers() {
  const s = new Set(DATA.map(r => r.tier.replace(/ STALE.*/, "")));
  return [...s].sort();
}
tiers().forEach(t => {
  const o = document.createElement("option");
  o.value = t; o.textContent = t; tierSel.appendChild(o);
});

function filtered() {
  const needle = (q.value || "").toLowerCase();
  const tier = tierSel.value;
  return DATA.filter(r =>
    (!tier || r.tier.replace(/ STALE.*/, "") === tier) &&
    (!needle || r.team.toLowerCase().includes(needle)));
}

function cmp(a, b) {
  let x = a[sortKey], y = b[sortKey];
  if (typeof x === "string") { x = x.toLowerCase(); y = String(y).toLowerCase(); }
  return (x < y ? -1 : x > y ? 1 : 0) * sortDir;
}

function render() {
  const rows = filtered().sort(cmp);
  const ranked = (sortKey === "rank" && sortDir === 1);
  count.textContent = rows.length + " of " + DATA.length + " teams";
  tbody.innerHTML = "";
  const frag = document.createDocumentFragment();
  rows.forEach((r, i) => {
    const tr = document.createElement("tr");
    const tds = [
      ["num", "#" + (ranked ? r.rank : (i + 1))],
      ["team", ""],
      ["num", r.score.toFixed(3)],
      ["", r.wl],
      ["", r.tier],
      ["num", r.ppg == null ? "-" : r.ppg.toFixed(1)],
      ["num", r.oppg == null ? "-" : r.oppg.toFixed(1)],
      ["num", r.diff == null ? "-" : (r.diff >= 0 ? "+" : "") + r.diff.toFixed(1)],
      ["", r.strk || "-"],
      ["", r.l10 || "-"],
      ["num", r.sos.toFixed(3)],
      ["num", (r.margin >= 0 ? "+" : "") + r.margin.toFixed(1)],
      ["", r.latest],
    ];
    tds.forEach(([cls, txt]) => {
      const td = document.createElement("td");
      if (cls) td.className = cls;
      td.textContent = txt;
      tr.appendChild(td);
    });
    const teamTd = tr.children[1];
    teamTd.className = "team";
    teamTd.innerHTML = "";
    const link = document.createElement("a");
    link.textContent = r.team;
    link.href = r.page;
    teamTd.appendChild(link);
    if (r.titles) {
      const b = document.createElement("span");
      b.className = "badge t"; b.textContent = "🏆" + (r.titles > 1 ? "x" + r.titles : "");
      b.title = r.titles + " title(s)";
      teamTd.appendChild(b);
    }
    frag.appendChild(tr);
  });
  tbody.appendChild(frag);
}

document.querySelectorAll("thead th[data-k]").forEach(th => {
  th.title = th.dataset.k === "rank"
    ? "Back to the official ranking"
    : "Sort by " + th.textContent.replace(/ [▲▼]/, "");
  th.addEventListener("click", () => {
    const k = th.dataset.k;
    if (k === "rank") { sortKey = "rank"; sortDir = 1; }
    else if (sortKey === k) sortDir *= -1;
    else { sortKey = k; sortDir = 1; }
    document.querySelectorAll("thead th").forEach(h =>
      h.textContent = h.textContent.replace(/ [▲▼]/, ""));
    th.textContent += sortDir === 1 ? " ▲" : " ▼";
    render();
  });
});
q.addEventListener("input", render);
tierSel.addEventListener("change", render);
render();
"""

BOARD_TMPL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} NorCal AAU Rankings</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
<header class="top">
<h1>{title} NorCal AAU Rankings</h1>
<p>{sub} &middot; generated {gen}</p>
<p>Score = per-game credit (tier x decay x margin x title x prestige) x opponent strength, iterated 15x.
Tiers nat 1.0 / up .85 / gold .75 / open .5 / silver .5 / bronze .25.
Title x1.5 champ wins; prestige x1.25 every win at Made Hoops/G365/OGP.
Ghosts (&lt;9g) give no opponent strength; only prelim top-10 confer credit; scores shrink by n/(n+8).
[T] = title holder. Click a column header to sort.</p>
<nav class="tabs">{tabs}</nav>
</header>
<div class="toolbar">
<input type="search" id="q" placeholder="Search team..." aria-label="Search team">
<select id="tier" aria-label="Filter by tier"><option value="">All tiers</option></select>
<span class="count" id="count"></span>
</div>
<table>
<thead><tr>
<th class="num" data-k="rank">#</th><th data-k="team">Team</th>
<th class="num" data-k="score">Score</th><th data-k="wl">W-L</th>
<th data-k="tier">Tier</th>
<th class="num" data-k="ppg">PPG</th><th class="num" data-k="oppg">OPP PPG</th>
<th class="num" data-k="diff">DIFF</th><th data-k="strk">STRK</th><th data-k="l10">L10</th>
<th class="num" data-k="sos">SOS</th>
<th class="num" data-k="margin">Margin</th><th data-k="latest">Latest</th>
</tr></thead>
<tbody id="rows"></tbody>
</table>
<section class="note"><h2>Titles (* = prestige Made Hoops/G365/OGP)</h2><ul>{titles}</ul></section>
<section class="note"><h2>TM note</h2><p>{tmnote}</p></section>
<footer class="gen">Generated {gen} from data/aau.db via rank_teams.py + build_reports.py.
Active-only (game in last 60 days), last-15 form. H2H tiebreak: {flips}.
<a href="{cohort}-unranked.html">{ucount} more teams with games (unranked)</a>.</footer>
</div>
<script>{js}</script>
</body>
</html>
"""

TEAM_TMPL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{team} ({cohort}) NorCal AAU</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
<a class="back" href="../../{cohort}.html">&larr; {cohort_title} board</a>
<nav class="tabs">{tabs}</nav>
<div class="detail-head">
<h2>{rank} {team}{titles}</h2>
<p class="sub">{score} &middot; {alltime} all-time &middot; {statline} &middot; tier mix {tier} &middot; window {wl} &middot; SOS {sos} &middot; {gen}</p>
</div>
{why_section}
<section class="note"><h2>Titles ({ntitles})</h2><ul>{titlelist}</ul></section>
{upcoming_section}
<section class="note"><h2>Full record ({ngames} scored games, newest first)</h2>
<table class="detail"><thead><tr><th>Date</th><th>Result</th><th>Opponent</th><th>Rank</th><th>Division</th><th>Event</th></tr></thead>
<tbody>{gamerows}</tbody></table></section>
{club_section}
<footer class="gen">Source: data/aau.db via rank_teams.py. Window = last {lastn} games within 180 days; full record below spans all scored games.</footer>
</div>
</body>
</html>
"""

UNRANKED_TMPL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{cohort_title} unranked teams</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
<a class="back" href="{cohort}.html">&larr; {cohort_title} board</a>
<nav class="tabs">{tabs}</nav>
<header class="top">
<h1>{cohort_title} &mdash; unranked teams ({count})</h1>
<p>Every team with at least one scored game but no board rank (too few
games, inactive, or out-of-region). Generated {gen}.</p>
</header>
<ul>{items}</ul>
</div>
</body>
</html>
"""

INDEX_TMPL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NorCal AAU Rankings</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
<header class="top">
<h1>NorCal AAU Rankings</h1>
<p>Bay Area / NorCal boys youth basketball &middot; generated {gen} &middot; last-15 form, active-only.</p>
</header>
<div class="cards">{cards}</div>
<footer class="gen">Source: exposureevents + bracketteam corpus (data/aau.db).
Scores = per-game credit x opponent strength, iterated 15x. See any board for the full formula.</footer>
</div>
</body>
</html>
"""


def parse_rep(path):
    """Parse /tmp/repNN.md into (board_rows, titles, tmnote, header_meta).

    titles: board-level list (for the board footer) + per-team map
    (for team pages): team_titles[team_id] = [title strings].
    """
    rows, titles, tmnote = [], [], ""
    team_titles = {}
    section = None
    meta = {}
    for line in open(path):
        s = line.rstrip("\n")
        if s.startswith("| # |"):
            section = "board"
            continue
        if s.startswith("|---"):
            continue
        if s.startswith("## Titles"):
            section = "titles"
            continue
        if s.startswith("## TM note"):
            section = "tmnote"
            continue
        if s.startswith("## Board"):
            section = None
            continue
        if section == "board" and s.startswith("| "):
            cells = [c.strip() for c in s.strip().strip("|").split("|")]
            if cells[0].isdigit():
                rows.append(cells)
        elif section == "titles" and s.startswith("- #"):
            titles.append(s[2:])
            m = re.match(r"- #\d+ (.+?): (champ|runner-up) (.*)$", s)
            if m:
                _t = m.group(3).strip()
                _url = ""
                _um = re.search(r"(https?://\S+)$", _t)
                if _um:
                    _url, _t = _um.group(1), _t[:_um.start()].strip()
                _band = ""
                _bm = re.search(r"\[([a-z/]+)\]", _t)
                if _bm:
                    _band = _bm.group(1).split("/")[0]
                team_titles.setdefault(m.group(1).strip(), []).append(
                    (f"{m.group(2)} {_t}", _url, _band))
        elif section == "tmnote" and s.strip():
            tmnote += s.strip() + " "
        elif "ranked." in s and "Active-only" in s:
            m = re.search(r"(\d+) ranked", s)
            if m:
                meta["n"] = m.group(1)
        elif s.startswith("H2H tiebreak"):
            meta["flips"] = s
    return rows, titles, tmnote.strip(), meta, team_titles



def game_logs(level_arg, cohort):
    """Full per-team game logs.

    Reads /tmp/games_<cohort>.jsonl (produced by rank_teams.py --dump-games
    with the same flags), falling back to running the dump inline.
    Cache it because each dump re-runs the full ranking pipeline (~4 min).
    Refresh with:
      python3 scripts/rank_teams.py --level <lv> --last 15 --boys-only \\
        --dump-games 2>/dev/null | grep '^{' > /tmp/games_<cohort>.jsonl
    """
    cache = Path(f"/tmp/games_{cohort}.jsonl")
    raw = ""
    if cache.exists():
        raw = cache.read_text()
    else:
        cmd = [sys.executable, str(HERE / "rank_teams.py"), "--level",
               level_arg, "--last", "15", "--boys-only", "--dump-games"]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True,
                               cwd=str(REPO), timeout=600)
            raw = p.stdout or ""
        except Exception:
            return {}
    logs = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            o = json.loads(line)
            logs[o["team"]] = o["games"]
        except Exception:
            continue
    return logs


def slug_of(team):
    s = re.sub(r"[^a-z0-9]+", "-", team.lower()).strip("-")
    return s or "team"


# Club families: team_id core prefix -> display name. Longest prefix wins.
# Falls back to first-two-tokens title-cased (with junk-drawer fixes).
CLUB_PREFIXES = [
    ("silicon valley soldiers", "Soldiers"),
    ("east bay soldiers", "Soldiers"),
    ("oakland soldiers", "Soldiers"),
    ("sv soldiers", "Soldiers"),
    ("bmg soldiers", "BMG"),
    ("bmg", "BMG"),
    ("tm", "TM"),
    ("peninsula gold", "Peninsula Gold"),
    ("ball game", "Ball Game"),
    ("norcal elite", "NorCal Elite"),
    ("norcal united", "NorCal United"),
    ("east bay elite", "East Bay Elite"),
    ("east bay bulldogs", "East Bay Bulldogs"),
    ("bay city", "Bay City"),
    ("top performance", "Top Performance"),
    ("top flight", "Top Flight"),
    ("team arsenal", "Team Arsenal"),
    ("team locked in", "Team Locked In"),
    ("team unequal", "Team Unequal"),
    ("lakeshow", "Lakeshow"),
    ("stl", "STL"),
    ("javstep", "JavStep"),
    ("esface", "Esface"),
    ("justhoop", "JustHoop"),
    ("flight", "Flight"),
    ("fury", "Fury"),
    ("bulldawgs", "Bulldawgs"),
    ("underdogs", "Underdogs"),
    ("sportstrong", "SportStrong"),
    ("payton's place", "Payton's Place"),
    ("yba", "YBA"),
    ("esface", "Esface"),
]
# First tokens too generic alone -- need two-token keys.
CLUB_SPLIT = {"bay", "team", "top", "sf", "san", "santa", "south", "north",
              "west", "east", "elite", "premier", "select"}


def club_of(team_id):
    core = team_id.split(":")[0].lower().strip()
    for prefix, club in CLUB_PREFIXES:
        if core == prefix or core.startswith(prefix + " ") or core.startswith(prefix + "-"):
            return club
    toks = core.split()
    if not toks:
        return "Other"
    if toks[0] in CLUB_SPLIT and len(toks) > 1:
        return " ".join(toks[:2]).title()
    return toks[0].title()


_all_pages = None


def all_pages_map():
    """team_id -> (cohort, filename) for every cohort, deterministic slugs.

    Replicates build_board's slug loop over game_logs() order so links
    match including -1 dedupe suffixes. Computed once, cached. Missing
    game logs for a cohort -> skipped (club links just omit it).
    """
    global _all_pages
    if _all_pages is not None:
        return _all_pages
    level_arg = {"11u": "11u", "12u": "12u,6th", "13u": "13u,7th",
                 "14u": "14u,8th", "15u": "15u,9th"}
    _all_pages = {}
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
            _all_pages[tid] = (cohort, cand)
    return _all_pages


def upcoming_rosters():
    """Load data/upcoming_rosters.json -> {team_id: [(date, event, url, raw, div)]}.

    Only resolved matches (team_id set) are returned. Missing file or no
    matches -> {}. Never raises -- team pages build without the section.
    """
    try:
        events = json.load(open(REPO / "data" / "upcoming_rosters.json"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    by_team = {}
    for eid, ev in events.items():
        for t in ev.get("teams", []) or []:
            tid = t.get("team_id")
            if not tid:
                continue
            by_team.setdefault(tid, []).append({
                "date": ev.get("start", ""), "event": ev.get("event", "?"),
                "url": ev.get("url", ""), "raw": t.get("raw", ""),
                "div": t.get("div", ""),
            })
    for lst in by_team.values():
        lst.sort(key=lambda x: (x["date"], x["event"]))
    return by_team


def team_page(cohort, cohort_title, r, gen, page_of, rank_of, upcoming=None):
    """Write site/teams/<cohort>/<slug>.html -- full detail page.

    page_of: team_id -> relative page path (for opponent links).
    rank_of: team_id -> current board rank (for the score line).
    """
    log = r.get("log", [])
    w = sum(1 for g in log if g.get("w"))
    bands = {}
    for g in log:
        bands[g.get("band", "?")] = bands.get(g.get("band", "?"), 0) + 1
    mix = "/".join(f"{b}{c}" for b, c in
                   sorted(bands.items(), key=lambda x: -x[1]))
    unranked = not r.get("rank")
    tier_disp = esc(r["tier"]) if r.get("tier") else esc(mix)
    head_rank = f"#{r['rank']}" if r.get("rank") else "Unranked"
    if log:
        lastn = r["wl"].split("(")[-1].rstrip(")") if "(" in r["wl"] else r["wl"]
    else:
        lastn = r["wl"]
    if log:
        gamerows = []
        for g in log:
            ev = external_link(g.get("event_url"), g.get("event", ""))
            cls = "w" if g.get("w") else "l"
            res = f'{"W" if g.get("w") else "L"} {esc(g.get("score", ""))}'
            opp, oid = esc(g.get("opp", "")), g.get("opp_id")
            # raw names may carry a tournament seed ("#2 Cali Gold ...")
            # -- strip it; the board rank we append is the real one.
            opp = re.sub(r"^#\d+\s+", "", opp)
            if oid and oid in page_of:
                pg = page_of[oid].replace("teams/" + cohort + "/", "")
                rk = rank_of.get(oid)
                tag = f"<td>#{rk}</td>" if rk else "<td>-</td>"
                opp = f'<a href="{esc(pg)}">{opp}</a>'
            elif oid and rank_of.get(oid):
                tag = f"<td>#{rank_of[oid]}</td>"
            else:
                tag = "<td>-</td>"
            gamerows.append(
                f"<tr><td>{esc(g.get('d', '')[5:])}</td>"
                f'<td class="{cls}">{res}</td>'
                f"<td>{opp}</td>{tag}"
                f"<td>{esc(g.get('div', ''))}</td><td>{ev}</td></tr>")
        gamerows = "\n".join(gamerows)
    else:
        gamerows = '<tr><td colspan="6">No scored games.</td></tr>'
    why = "".join(f"<li>{esc(x)}</li>" for x in r["why"])
    _titles = r.get("titlelist", [])
    _items = []
    for _t in _titles:
        if isinstance(_t, (list, tuple)):
            _txt = _t[0]
            _url = _t[1] if len(_t) > 1 else ""
            _band = _t[2] if len(_t) > 2 else ""
        else:
            _txt, _url, _band = _t, "", ""
        _badge = (f'<span class="tbadge t-{_band}">{_band}</span> '
                  if _band in ("national", "up", "gold", "silver",
                               "bronze", "open") else "")
        _items.append(f'<li>{_badge}{external_link(_url, _txt)}</li>')
    titlelist = "".join(_items) or "<li>No titles held.</li>"
    marks = " 🏆" * min(r["titles"], 2) if r["titles"] else ""
    tabs = ""
    for c, (t, _, _) in COHORTS.items():
        tabs += f'<a href="../../{c}.html">{t}</a>'
    tabs += ('<a href="../../upcoming.html">Upcoming</a>'
             '<a href="../../organizers.html">Organizers</a>'
             '<a href="../../clubs.html">Clubs</a>')
    why_html = (f"<section class=\"note\"><h2>Why #{r['rank']}</h2>"
                f"<ul>{why}</ul></section>" if r.get("rank") and why else "")
    up_list = (upcoming or {}).get(r["team"], [])
    if up_list:
        up_items = "".join(
            f"<li>{esc(u['date'][5:].replace('-', '/'))} &mdash; "
            f"{external_link(u['url'], u['event'])}"
            f" <span style=\"color:var(--mut)\">({esc(u['div'])}"
            f"{' as ' + esc(u['raw']) if u['raw'].lower() != r['team'].lower() else ''})</span></li>"
            for u in up_list)
        upcoming_section = (f"<section class=\"note\"><h2>Upcoming "
                            f"({len(up_list)})</h2><ul>{up_items}</ul></section>")
    else:
        upcoming_section = ""
    # Club section: same-club squads, same cohort first then other ages.
    # Links via the global pages map (cross-cohort where needed).
    club_section = ""
    try:
        pmap = all_pages_map()
        club = club_of(r["team"])
        same, other = [], []
        for tid, (coh, fn) in pmap.items():
            if tid == r["team"] or club_of(tid) != club:
                continue
            if coh == cohort:
                same.append((tid, f"{fn}"))
            else:
                other.append((tid, f"../../teams/{coh}/{fn}", coh))
        if same or other:
            try:
                cslugs = json.load(open(REPO / "data" / "club_slugs.json"))
                chead = (f"<a href=\"../../clubs/{cslugs[club]}.html\">"
                         f"{esc(club)}</a>" if club in cslugs else esc(club))
            except (FileNotFoundError, json.JSONDecodeError):
                chead = esc(club)
            items = "".join(
                f'<li><a href="{f}">{esc(t)}</a> (same age)</li>'
                for t, f in sorted(same))
            # group other-ages by cohort in board order
            order = ["11u", "12u", "13u", "14u", "15u"]
            for coh in order:
                grp = sorted(t for t, f, c in other if c == coh)
                for t in grp:
                    fn = next(f for x, f, c in other if x == t)
                    items += (f'<li><a href="{fn}">{esc(t)}</a> '
                              f'({coh})</li>')
            club_section = (f"<section class=\"note\"><h2>More {chead} "
                            f"({len(same) + len(other)})</h2><ul>{items}</ul></section>")
    except Exception:
        club_section = ""
    page = TEAM_TMPL.format(
        team=esc(r["team"]) + marks, cohort=esc(cohort),
        cohort_title=esc(cohort_title), tabs=tabs, css=CSS,
        rank=head_rank, titles=" [T]" if r["titles"] else "",
        score=f"{r['score']:.3f}" if r.get("rank") else "unranked",
        alltime=f"{w}-{len(log) - w}",
        statline=(f"{r['ppg']:.1f} PPG / {r['oppg']:.1f} OPP"
                  f" / {r['diff']:+.1f} DIFF / {r['strk']} STRK"
                  f" / {r['l10']} L10"
                  if r["ppg"] is not None else "no scored window games"),
        tier=tier_disp, wl=esc(r["wl"]),
        sos=f"{r['sos']:.3f}" if r.get("rank") else "-",
        gen=esc(gen), why=why, why_section=why_html, ngames=len(log),
        titlelist=titlelist, ntitles=len(_titles),
        upcoming_section=upcoming_section,
        club_section=club_section,
        gamerows=gamerows, lastn=esc(lastn),
    )
    # filename decided by caller (two-pass dedup); return the HTML,
    # caller writes it to teams/<cohort>/<file>.
    return page


def build_board(cohort, title, sub, gen):
    num = {"11u": "11", "12u": "12", "13u": "13", "14u": "14", "15u": "15"}[cohort]
    level_arg = {"11u": "11u", "12u": "12u,6th", "13u": "13u,7th", "14u": "14u,8th", "15u": "15u,9th"}[cohort]
    rows, titles, tmnote, meta, team_titles = parse_rep(f"/tmp/rep{num}.md")
    logs = game_logs(level_arg, cohort)
    data = []
    for tid, log in logs.items():
        # ranked teams carry the board row; unranked teams (rank 0 in
        # the dump) get a page from the log alone, using the same
        # window/stat math with the full log as the window.
        brow = next((r for r in rows
                     if re.sub(r"\s*\[T\]$", "", r[1]).strip() == tid), None)
        if brow is not None:
            # r: [#, team, score, wl, tier, sos, margin, latest, why]
            why_raw = brow[8] if len(brow) > 8 else ""
            m = re.search(r"\(last (\d+)\)", brow[3])
            wn = int(m.group(1)) if m else 15
            wlog = log[:wn]
            data.append({
                "rank": int(brow[0]),
                "team": tid,
                "titles": brow[1].count("[T]"),
                "score": float(brow[2]),
                "wl": brow[3],
                "tier": brow[4],
                "sos": float(brow[5]),
                "margin": float(brow[6]),
                "latest": brow[7],
                "why": [w.strip(" ;") for w in why_raw.split("//")
                        if w.strip(" ;")],
                "log": log,
                "wlog": wlog,
                "titlelist": team_titles.get(tid, []),
            })
        else:
            wlog = log
            data.append({
                "rank": 0,
                "team": tid,
                "titles": 0,
                "score": 0.0,
                "wl": f"{sum(1 for g in log if g.get('w'))}-"
                      f"{sum(1 for g in log if not g.get('w'))}"
                      f" (last {len(log)})",
                "tier": "",
                "sos": 0.0,
                "margin": 0.0,
                "latest": log[0]["d"][:10] if log else "",
                "why": [],
                "log": log,
                "wlog": wlog,
                "titlelist": team_titles.get(tid, []),
            })
    # shared stat math over the chosen window slice (wlog was set per
    # team in the build loop above: ranked = last-N slice, unranked =
    # full log). r["wlog"] carries it; popped after use.
    for r in data:
        wlog = r.pop("wlog", r["log"])
        pf, pa, nw = [], [], 0
        for g in wlog:
            try:
                a, b = g["score"].split("-")
                pf.append(int(a)); pa.append(int(b)); nw += 1
            except (ValueError, AttributeError, KeyError):
                continue
        ppg = sum(pf) / nw if nw else None
        oppg = sum(pa) / nw if nw else None
        # streak: W/L run at the head of the window slice (newest first)
        strk, sc = "", 0
        for g in wlog:
            s = "W" if g.get("w") else "L"
            if not strk:
                strk, sc = s, 1
            elif s == strk:
                sc += 1
            else:
                break
        strk = f"{strk}{sc}" if strk else "-"
        # last 10 of the window slice (or fewer)
        l10g = wlog[:10]
        lw = sum(1 for g in l10g if g.get("w"))
        l10 = f"{lw}-{len(l10g) - lw}" if l10g else "-"
        r["ppg"] = ppg
        r["oppg"] = oppg
        r["diff"] = (ppg - oppg) if ppg is not None else None
        r["strk"] = strk
        r["l10"] = l10
    tabs = ""
    for c, (t, _, _) in COHORTS.items():
        on = ' class="on"' if c == cohort else ""
        tabs += f'<a href="{c}.html"{on}>{t}</a>'
    tabs += '<a href="upcoming.html">Upcoming</a>'
    tabs += '<a href="organizers.html">Organizers</a>'
    tabs += '<a href="clubs.html">Clubs</a>'
    titles_html = "".join(f"<li>{esc(t)}</li>" for t in titles) or "<li>None</li>"
    upcoming = upcoming_rosters()
    # team detail pages: two passes (slugs first so opponent links
    # resolve, then pages). page_of maps team_id -> board-relative path.
    # NOTE: filenames must be deterministic across rebuilds (opponent
    # links point at them) -- claim names from a clean directory, not
    # from what exists on disk. build_board wipes teams/<cohort> first.
    import shutil
    outdir = OUT / "teams" / cohort
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    seen, page_of, rank_of = set(), {}, {}
    unranked = []  # dumped teams not on the board (rank 0 in logs)
    for r in data:
        base = slug_of(r["team"])
        n, cand = 0, ""
        while True:
            cand = (base if n == 0 else f"{base}-{n}") + ".html"
            if cand not in seen:
                break
            n += 1
        seen.add(cand)
        page_of[r["team"]] = f"teams/{cohort}/{cand}"
        if r["rank"]:
            rank_of[r["team"]] = r["rank"]
        else:
            unranked.append(r)
    for r in data:
        rel = page_of[r["team"]]
        (outdir / rel.split("/")[-1]).write_text(
            team_page(cohort, title, r, gen, page_of, rank_of, upcoming))
        r["page"] = rel
    if unranked:
        ulist = "\n".join(
            f'<li><a href="{esc(page_of[r["team"]])}">{esc(r["team"])}</a>'
            f" ({len(r['log'])}g, latest {esc(r['log'][0]['d'][:10])})</li>"
            for r in sorted(unranked, key=lambda x: x["team"]))
        (OUT / f"{cohort}-unranked.html").write_text(
            UNRANKED_TMPL.format(cohort_title=esc(title), cohort=esc(cohort),
                                 css=CSS, tabs=tabs, count=len(unranked),
                                 items=ulist, gen=esc(gen)))
    n_ranked = sum(1 for r in data if r["rank"])
    slim = [{k: v for k, v in r.items() if k != "log"} for r in data if r["rank"]]
    js = JS.replace("__DATA__", json_for_script(slim))
    page = BOARD_TMPL.format(
        title=esc(title), sub=esc(sub), gen=esc(gen), css=CSS, tabs=tabs,
        titles=titles_html, tmnote=esc(tmnote),
        flips=esc(meta.get("flips", "none")),
        cohort=esc(cohort), ucount=len(unranked),
        js=js,
    )
    (OUT / f"{cohort}.html").write_text(page)
    print(f"wrote {cohort}.html ({n_ranked} ranked + {len(unranked)} unranked)")
    return len(data), title


def main():
    from datetime import date
    gen = date.today().isoformat()
    OUT.mkdir(parents=True, exist_ok=True)
    cards = ""
    counts = {}
    for cohort, (title, num, sub) in COHORTS.items():
        n, _ = build_board(cohort, title, sub, gen)
        counts[cohort] = n
    for cohort, (title, num, sub) in COHORTS.items():
        first = ""
        try:
            rep_rows, _, _, _, _ = parse_rep(f"/tmp/rep{num}.md")
            if rep_rows:
                first = esc(re.sub(r"\s*\[T\]$", "", rep_rows[0][1]).strip())
        except Exception:
            pass
        cards += (f'<a href="{cohort}.html"><h2>{esc(title)}</h2>'
                  f'<p class="big">{counts[cohort]}</p>'
                  f'<p>ranked teams &middot; #1 {first}</p></a>')
    (OUT / "index.html").write_text(
        INDEX_TMPL.format(css=CSS, gen=esc(gen), cards=cards))
    print("wrote index.html")


if __name__ == "__main__":
    main()
