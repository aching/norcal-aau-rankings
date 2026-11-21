#!/usr/bin/env python3
"""Publish the normalized 2026 circuit dataset as a searchable static page."""
import csv
import datetime as dt
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_site import CSS
from export_circuits_2026 import FIELDS
from html_utils import esc, safe_url

DATA = HERE.parent / "data"
OUT = HERE.parent / "site" / "circuits"
SLIM_FIELDS = ["circuit", "series", "division", "event", "date", "time",
               "home_team", "away_team", "home_score", "away_score", "status",
               "venue", "court", "url", "game_id", "game_type"]

EXTRA_CSS = """
main{max-width:1500px;margin:auto}.intro{color:var(--mut);line-height:1.6}
.circuit-stats{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0}
.circuit-stats strong{color:var(--txt)}
.circuit-controls{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}
.circuit-controls label{font-size:12px;color:var(--mut);display:flex;flex-direction:column;gap:4px}
.circuit-controls input,.circuit-controls select{width:100%;box-sizing:border-box;padding:8px;background:var(--panel);color:var(--txt);border:1px solid var(--line);border-radius:5px}
.circuit-controls .search{grid-column:span 2}.buttons{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:14px 0}
.buttons button,.buttons a{cursor:pointer;padding:8px 12px;background:var(--panel);color:var(--txt);border:1px solid var(--line);border-radius:5px;text-decoration:none}
#circuits{width:100%;border-collapse:collapse;font-size:13px}#circuits th{text-align:left;color:var(--mut);padding:8px;border-bottom:1px solid var(--line)}
#circuits td{padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:top}#circuits td.muted{color:var(--mut);font-size:12px}
#circuits .score{font-weight:700;white-space:nowrap}.scheduled{color:var(--mut)}
details{margin:18px 0;line-height:1.6}details p,details li{color:var(--mut)}
@media(max-width:900px){.circuit-controls .search{grid-column:span 1}#circuits{min-width:1050px}.table-wrap{overflow:auto}}
"""

APP_JS = r"""(() => {
'use strict';
const C = {circuit:0, series:1, division:2, event:3, date:4, time:5,
  home:6, away:7, homeScore:8, awayScore:9, status:10, venue:11, court:12,
  url:13, id:14, type:15};
const $ = id => document.getElementById(id);
let games = [], filtered = [], shown = 100, newestFirst = true;
const controls = ['circuit', 'series', 'division', 'event', 'statusFilter'];
function options(id, values) {
  [...new Set(values)].sort().forEach(value => {
    const option = document.createElement('option');
    option.value = value; option.textContent = value || '(not specified)';
    $(id).appendChild(option);
  });
}
function compareDate(a, b) {
  return (a[C.date].localeCompare(b[C.date]) || a[C.time].localeCompare(b[C.time]) ||
          String(a[C.id]).localeCompare(String(b[C.id]))) * (newestFirst ? -1 : 1);
}
function sourceLink(game, label) {
  const span = document.createElement('span');
  if (/^https?:\/\//i.test(game[C.url])) {
    const a = document.createElement('a');
    a.href = game[C.url]; a.target = '_blank'; a.rel = 'noopener noreferrer';
    a.textContent = label; span.appendChild(a);
  } else span.textContent = label;
  return span;
}
function gameMatch(game) {
  if ($('circuit').value && game[C.circuit] !== $('circuit').value) return false;
  if ($('series').value && game[C.series] !== $('series').value) return false;
  if ($('division').value && game[C.division] !== $('division').value) return false;
  if ($('event').value && game[C.event] !== $('event').value) return false;
  if ($('statusFilter').value === 'final' && game[C.status].toLowerCase() !== 'final') return false;
  if ($('statusFilter').value === 'scheduled' && game[C.status].toLowerCase() === 'final') return false;
  if ($('from').value && game[C.date] < $('from').value) return false;
  if ($('to').value && game[C.date] > $('to').value) return false;
  const query = $('q').value.trim().toLowerCase();
  return !query || [game[C.home], game[C.away], game[C.event], game[C.venue],
    game[C.division]].join(' ').toLowerCase().includes(query);
}
function render(reset) {
  if (reset) shown = 100;
  filtered = games.filter(gameMatch).sort(compareDate);
  const body = $('gamesBody'); body.replaceChildren();
  filtered.slice(0, shown).forEach(game => {
    const tr = document.createElement('tr');
    const date = document.createElement('td'); date.textContent = game[C.date] + (game[C.time] ? ' ' + game[C.time] : '');
    const teams = document.createElement('td');
    teams.appendChild(sourceLink(game, game[C.home])); teams.appendChild(document.createElement('br'));
    teams.appendChild(document.createTextNode(game[C.away]));
    const score = document.createElement('td'); score.className = 'score';
    score.textContent = game[C.homeScore] !== '' && game[C.awayScore] !== '' ?
      game[C.homeScore] + '–' + game[C.awayScore] : 'Scheduled';
    const details = document.createElement('td');
    details.textContent = game[C.event];
    const meta = document.createElement('div'); meta.className = 'muted';
    meta.textContent = [game[C.series], game[C.division], game[C.type]].filter(Boolean).join(' · ');
    details.appendChild(meta);
    const place = document.createElement('td'); place.className = 'muted';
    place.textContent = [game[C.venue], game[C.court]].filter(Boolean).join(' / ');
    const link = document.createElement('td');
    if (game[C.url]) link.appendChild(sourceLink(game, 'Source ↗'));
    [date, teams, score, details, place, link].forEach(td => tr.appendChild(td));
    body.appendChild(tr);
  });
  const end = Math.min(shown, filtered.length);
  $('status').textContent = filtered.length ?
    `Showing ${1}–${end} of ${filtered.length.toLocaleString()} matching games (${games.length.toLocaleString()} total)` :
    'No matching games';
  $('status').className = filtered.length ? '' : 'scheduled';
  $('more').hidden = end >= filtered.length;
  $('empty').hidden = filtered.length !== 0;
}
function reset() {
  controls.forEach(id => $(id).value = '');
  $('q').value = ''; $('from').value = ''; $('to').value = ''; render(true);
}
$('more').addEventListener('click', () => { shown += 100; render(false); });
$('reset').addEventListener('click', reset);
$('sort').addEventListener('click', () => {
  newestFirst = !newestFirst; $('sort').textContent = newestFirst ? 'Newest first' : 'Oldest first'; render(false);
});
[...controls.map(id => $(id)), $('q'), $('from'), $('to')].forEach(el => el.addEventListener('input', () => render(true)));
fetch('games.json').then(response => {
  if (!response.ok) throw new Error('Game data could not be loaded');
  return response.json();
}).then(data => {
  games = data;
  options('circuit', games.map(g => g[C.circuit]));
  options('series', games.map(g => g[C.series]));
  options('division', games.map(g => g[C.division]));
  options('event', games.map(g => g[C.event]));
  render(true);
}).catch(error => { $('status').textContent = error.message; });
})();
"""


def export_site(games, event_csv, out_dir=OUT):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slim = [[r.get(field, "") for field in SLIM_FIELDS] for r in games]
    for game in slim:
        game[SLIM_FIELDS.index("url")] = safe_url(game[SLIM_FIELDS.index("url")])
    (out_dir / "games.json").write_text(
        json.dumps(slim, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    with (out_dir / "games.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(games)
    shutil.copyfile(event_csv, out_dir / "events.csv")
    (out_dir / "app.js").write_text(APP_JS, encoding="utf-8")

    counts = Counter(r["circuit"] for r in games)
    finals = sum(r["status"].lower() == "final" for r in games)
    stats = "".join(f"<span><strong>{esc(circuit)}</strong> {counts[circuit]:,} games</span>"
                    for circuit in sorted(counts))
    nav = "".join(f'<a href="../{slug}.html">{label}</a>' for slug, label in
                  [("11u", "11U"), ("12u", "12U"), ("13u", "13U"), ("14u", "14U"),
                   ("15u", "15U"), ("organizers", "Organizers"), ("clubs", "Clubs")])
    nav += '<a href="../index.html">Upcoming</a><a href="./" class="on">Circuits</a>'
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="2026 UAA, EYBL, and 3SSB schedules and results">
<title>2026 Circuit Schedules &amp; Results</title><style>{CSS}{EXTRA_CSS}</style></head>
<body><div class="wrap"><nav class="tabs">{nav}</nav><main>
<h1>2026 Circuit Schedules &amp; Results</h1>
<p class="intro">UAA / Rise, Nike EYBL / EYCL / PIT, Junior EYBL, and West 3SSB.
<strong>{len(games):,} games</strong>; {finals:,} finals and {len(games)-finals:,} scheduled or unscored rows.
Generated {dt.date.today().isoformat()}.</p>
<div class="circuit-stats">{stats}</div>
<div class="circuit-controls">
<label class="search">Team or event search<input id="q" type="search" placeholder="e.g. Oakland Soldiers"></label>
<label>Circuit<select id="circuit"><option value="">All circuits</option></select></label>
<label>Series<select id="series"><option value="">All series</option></select></label>
<label>Division<select id="division"><option value="">All divisions</option></select></label>
<label>Event<select id="event"><option value="">All events</option></select></label>
<label>Result<select id="statusFilter"><option value="">All</option><option value="final">Final</option><option value="scheduled">Scheduled/unscored</option></select></label>
<label>From<input type="date" id="from"></label><label>To<input type="date" id="to"></label>
</div><div class="buttons"><button id="reset">Reset filters</button><button id="sort">Newest first</button>
<a href="games.csv" download>Download games CSV</a><a href="events.csv" download>Download events CSV</a><a href="games.json" download>Download JSON</a></div>
<p id="status" role="status">Loading game data…</p><p id="empty" hidden>No matching games.</p>
<div class="table-wrap"><table id="circuits"><thead><tr><th>Date / time</th><th>Teams</th><th>Score</th><th>Event / division</th><th>Venue / court</th><th>Source</th></tr></thead><tbody id="gamesBody"></tbody></table></div>
<div class="buttons"><button id="more" hidden>Show 100 more</button></div>
<details><summary>Coverage notes</summary><ul>
<li>Nike's official public Event Hub provides 1,570 main-session games and 258 Peach Jam/PIT games. EYBL, EYCL, and PIT are separate series.</li>
<li>UAA's official pages provide 3,720 deduplicated records. The combined page substitutes the fuller 846-game girls UAA aggregate schedule for 689 overlapping webpage rows.</li>
<li>3SSB is the verified West circuit only (2,131 games), not a complete nationwide archive.</li>
<li>Unavailable times and courts remain blank. Source scores and statuses are preserved without silently correcting anomalies.</li>
</ul></details>
</main></div><noscript><p>Enable JavaScript to filter games, or use the CSV/JSON downloads above.</p></noscript>
<script src="app.js" defer></script></body></html>"""
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    print(f"circuits: {len(games):,} games, {len(slim)} data rows, -> {out_dir}")


def main():
    with (DATA / "circuits_2026_all.csv").open() as f:
        games = list(csv.DictReader(f))
    export_site(games, DATA / "circuits_2026_events.csv")


if __name__ == "__main__":
    main()
