(() => {
'use strict';
const C = {circuit:0, series:1, division:2, event:3, date:4, time:5,
  home:6, away:7, homeScore:8, awayScore:9, status:10, venue:11, court:12,
  url:13, id:14, type:15, homeCanonical:16, homeAge:17, homeResolution:18,
  homeMatch:19, homeProfile:20, awayCanonical:21, awayAge:22, awayResolution:23,
  awayMatch:24, awayProfile:25};
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
function teamLabel(game, side) {
  const isHome = side === 'home';
  const label = game[isHome ? C.home : C.away];
  const profile = game[isHome ? C.homeProfile : C.awayProfile];
  if (!profile || !profile.startsWith('../teams/')) return document.createTextNode(label);
  const a = document.createElement('a');
  a.href = profile;
  const team = game[isHome ? C.homeCanonical : C.awayCanonical];
  const age = game[isHome ? C.homeAge : C.awayAge];
  const resolution = game[isHome ? C.homeResolution : C.awayResolution];
  a.title = `AAU profile · ${team} · age cohort ${age} · ${resolution} match`;
  a.textContent = label + ' ↗';
  return a;
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
    teams.appendChild(teamLabel(game, 'home')); teams.appendChild(document.createElement('br'));
    teams.appendChild(teamLabel(game, 'away'));
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
