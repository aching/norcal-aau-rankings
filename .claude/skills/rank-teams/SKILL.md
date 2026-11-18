---
name: rank-teams
description: Rank 14U/8th-grade (or any level) AAU teams by last-N-games form, optionally limited to tournaments near a Bay Area city. Use when the user asks for team rankings, power rankings, hottest teams, W-L over recent games, or a matchup prediction grounded in recent form.
---

# Rank teams by recent form

Backed by `scripts/rank_teams.py`, which queries `data/aau.db`
(built by `scripts/build_db.py`).

## Run it

```bash
# 14U/8th-grade boys, last 12 (180-day floor), tournaments within 50mi of Palo Alto
python3 scripts/rank_teams.py --level 14u,8th --last 12 --region 'Palo Alto' --miles 50 --boys-only

# Other cohorts / scopes
python3 scripts/rank_teams.py --level 14u,8th --last 10 --region 'San Ramon' --miles 25
python3 scripts/rank_teams.py --level 13u --last 10 --girls-only
python3 scripts/rank_teams.py --level 14u --last 12 --min-games 8 --include-bare --no-decay
```

Flags: `--level` (required; comma-separated — use `14u,8th` for the
full 14U/8th-grade cohort since the two labels are disjoint),
`--last N` (default 12), `--window-days` (default 180: hard recency floor -- older games are out, not just decayed; 0 disables), `--min-games` (default 4, below that =
unranked), `--active-days` (default 60: teams whose latest game is
older are listed separately as inactive, never ranked; 0 disables),
`--region` + `--miles` (default 50), `--boys-only` / `--girls-only`,
`--include-bare` (opt in to ambiguous `prog:*` labels),
`--no-decay` (disable recency decay), `--no-sos` (pure form),
`--title-bonus MULT` (default 1.5: championship-bracket wins in won
2-day events earn MULT x credit; `--no-title` disables both title
and prestige bonuses), `--prestige-mult MULT` (default 1.25: EVERY
win at a Made Hoops / Grassroots365 / OGP event earns MULT x, pool
included; stacks with title bonus),
`--min-title-teams N` (default 8: min teams for title detection),
`--h2h-band GAP` (default 0.01: a lower team that directly beat a
higher team jumps them when scores are within GAP; 0 disables),
`--db` path.
## What it answers

Sort key is a **head-to-head-weighted transitive score**. Each game
is worth credit scaled by the OPPONENT's strength (iterated 15x to
convergence, so A > B > C propagates): a win earns
`tier x decay x margin x (0.25 + 0.75 x opp)`, a loss earns a consolation
`tier x decay x margin x 0.25 x opp` (good losses count, bad losses cost).
Opponents with <9 games (ghosts) contribute no opp strength -- their
blurry seeds must not launder credit. **Only prelim top-10 teams confer
transitive credit** (two-pass gate: pass 1 ranks everyone, pass 2 zeroes
opp scores outside the top 10 -- beating #13 pays the floor but no boost,
losing to #13+ earns no consolation; `--ranked-win-top 0` disables).
Tier weights: national 1.0 / playing-up 0.85 / gold 0.75 /
open 0.5 / silver 0.5 / bronze 0.25, blended bands averaged.
**Cross-tier ceiling (default on, `--no-tier-ceiling` disables):**
bronze sits below silver, silver below gold, gold below national --
unless the team beats someone from that tier or higher (opponent
modal band, not the ranked-win gate -- beating an unranked-but-gold
team still promotes). Each cross-tier win buys 10% headroom above the
next tier's best clean team, so a bronze team with two silver wins
can pass mediocre silvers but never golds. open/silver are peers
(D2 flights mix freely); playing-up counts as national; mixed bands
take the best component. "International"-named local divisions are
open, not national (only EYBL/EYCL/E15/E16/PIT + national-named
divisions count). Curated Nov 2026 after Delta Heat's bronze 11-4
sat at #39 with zero silver wins. Decay:
full <90d, fading to zero at 1yr. **Margin (log curve, capped at 25):**
squeaker ~0.85x, median game (~12 pts) 1.0x, 20-pt statement ~1.15x;
close losses keep full consolation, blowout losses keep ~0.2x.
**Sample-size shrinkage:** published scores scale by n/(n+8) -- a 4-game
streak keeps 33%, a full 15-game window keeps 65% (disable:
`--shrink-k 0`). Short streaks must be sustained to hold rank.
**NorCal membership:** teams appearing ONLY in SoCal circuit events
(Jr. EYBL / 3SSB / 3Stripes qualifiers+finals) or the surname house
league don't rank -- membership needs >=1 NorCal-pipeline game
(`--no-norcal-gate` disables). Circuit games still score for everyone,
prestige-weighted. **Identity level-split:** bare program names
("Fury", "TM Basketball") resolve per-division -- 14U Gold Fury and
10U Fury are different teams (`team_identity.py`). Beating a strong team moves the
needle; beating a weak team barely registers; losing to a weak team
hurts. Every win at a prestige-operator event (Made Hoops /
Grassroots365 / OGP **plus the national shoe circuits: Nike Jr. EYBL,
adidas 3SSB / 3Stripes Gold, Under Armour Next/Rise/Future**) earns a
prestige multiplier (default x1.25, pool play included --
`--prestige-mult`, stacks with the title bonus).
Championship-bracket wins in a won 2-day event earn a title multiplier
(default x1.5 -- [T] marks title holders, * prestige in the title list;
runner-up's final loss counts at half).
bonus). The `sos` column shows mean opponent strength and `vs`
shows direct results (ranked opps with rank #, plus unranked with
game counts — wins first). Plain W-L and margin print alongside;
`STALE` flags mark teams idle >120d. Use the table for "who's hot"
and as the form baseline for matchup predictions — combined with
head-to-head history. `--no-sos` recovers pure form; `--sos-iters`
changes propagation rounds (default 15, converged).

## Rules you must follow when reporting

1. **Region = tournament location, not team hometown.** The corpus has
   no per-team hometowns; the filter keeps games at tournaments whose
   snapshot `City` falls in radius. Say "teams playing near X", never
   "teams from X". Cities outside `CITY_COORDS` in the script never
   match — a team whose games were all in Rocklin/Sacramento drops out
   of a Palo Alto-50 ranking silently. If a known team is missing,
   check whether its tournaments geocode before concluding anything.
2. **Head-to-head is a tiebreak, not a recount.** A direct win swaps
   two close ranks (default: scores within 0.01, at most 2 spots apart)
   — same-level games only (a 10U result never moves a 14U rank), fresh
   evidence only (inside the active window). Nobody else moves. The
   flip list prints in the header (`h2h tiebreak ±0.01 (N flips: ...)`). Gaps beyond the
   band don't flip: losing badly to everyone else still sinks you.
   `--h2h-band 0` disables.
3. **Exclude `bare` rows by default, and gate on team activity.**
   `prog:*` team_ids are ambiguous program labels merged across
   divisions — never rank them unless the user explicitly asks
   (`--include-bare`). Exception: the opponent graph resolves through
   ALL names (including bare) when scoring opponents — a ranked team's
   strength can flow through a bare-label intermediary. That's correct
   (the game happened), but say so if a rank hinges on it.
   `--active-days` (default 60) implements "at least one game in the
   last 2 months": activity is checked against the team's UNFILTERED
   game list, not the regional slice — a team active in Rocklin but
   idle near Palo Alto is active, just unsampled. Three bins result:
   ranked (≥min-games in-region), active-elsewhere (recent games, too
   few/none in-region — listed, unranked), inactive (nothing anywhere
   in the window — listed, unranked). `0` disables the gate.
3. **Color/coach squads rank separately.** Black vs Orange, Lo vs
   Harvey vs Eddie are different team_ids. Never blend them, and say
   which squad a rank refers to.
4. **Tier is in the score, not beside it.** Every row shows its modal
   tier band; the score already weights by it. Still sanity-check:
   an `open`-tier team above a `national` one earned it only via
   volume + recency — say so.
5. **Small samples lie; stale teams don't rank at all.** 5-0 vs weak
   fields can outscore 11-4 vs strong ones — call this out. Teams idle
   longer than `--active-days` (default 60d) are gated out of the
   board into an inactive list; use `--active-days 0` to see them.
   `STALE` flags (idle >120d) should therefore never appear on a
   default-gated board — if one does, the gate is broken.
6. **No UAA inference.** There is no UAA division/team label in the
   corpus; never call a squad "UAA" unless the name says so.
7. **Curated ids blend eras — check the game log, not just the rank.**
   Override team_ids (e.g. `tm:falcons-14u`, linked via SUCCESSORS to
   the 13U `tm:falcons` base label) sweep multiple seasons and labels
   into one row. A bad blended rank can hide decent recent-tier form:
   always pull the team's last-N game list before writing it off in a
   matchup call.
8. **Titles need eligibility — read the fine print.** A title counts
   when a (tournament, division) has games on 2+ distinct dates and
   ≥8 distinct teams (`--min-title-teams`), with a real
   championship-bracket final (pool-only or consolation-only events
   never qualify). BT events can't yield titles (no bracket labels).
   One-off/small events and runner-up finals get reduced or no credit —
   say so when a rank leans on one.

## W/L semantics (do not re-derive)

- EE: `Status == 'Final'` = played; `*IsWinner` flags = winner.
  Forfeit strings (`F-W`) carry winner flags and count as W/L.
- BT: `has_result = 1` and `winner IN ('H','A')` = played/decided.
  `NULL`/unscheduled/exhibition rows are skipped.
- `HideScores: true` games never reach the DB (filtered at load).
- EE dates are `M/D/YYYY`, BT dates `YYYY-MM-DD`; the script normalizes.

## Extending

- New city centroid: add a fragment → `(lat, lon)` row to
  `CITY_COORDS`. Fragments match as substrings, so keep them specific.
- New level: nothing to change — `--level` filters `teams.level`
  directly (`14u`, `13u`, `8th`, `7th`, ...). Pass `--level 14u,8th`
  for the combined 14U/8th-grade cohort (the two labels are disjoint
  in the DB, so neither alone covers the cohort).
