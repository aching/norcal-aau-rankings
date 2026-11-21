# AGENTS.md — aau-basketball

## 1. Project overview

NorCal AAU basketball opponent-research project (spec owner: Avery). Goal per `PRD.md` (Draft v0.2): a web app where you type a Bay Area/NorCal team name and get tournament history, game results, season record, and program affiliation. The repo contains the ingestion pipeline and a generated static rankings site, backed by `data/aau.db` (SQLite). Next work is the full V1 web app.

## 2. Commands

No manifest, Makefile, or linters. CI is GitHub Pages deployment only. Tests use stdlib `unittest`; otherwise stdlib-only Python 3 — **no install step**. Run everything from the repo root (scripts use relative `data/` paths).

```bash
# Full refresh: discovery -> scrape -> database (all stages by default)
python3 scripts/refresh.py status                                    # report only: last run vs last data per source
python3 scripts/refresh.py progress                                  # live progress of running jobs (window + current item)
python3 scripts/refresh.py [--no-ee] [--no-bt] [--no-db] [--since=YYYY-MM-DD]
```
# Single-tournament scrapes (write data/<id>.json / data/bt_<id>.json)
python3 scripts/scrape_tournament.py <tournament_id> <slug> [out_dir]   # exposureevents
python3 scripts/scrape_bracketteam.py <event_id> [out_dir]              # bracketteam

# Rebuild the database from all JSON (default: data/aau.db)
python3 scripts/build_db.py [db_path]

# Regression tests (no network or corpus writes)
python3 -m unittest discover -s tests -v

# Rebuild the one-off 2026 circuit archive and website from cached data
python3 scripts/scrape_uaa.py --offline
python3 scripts/export_circuits_2026.py
python3 scripts/build_site.py  # refresh linked profile circuit supplements
python3 scripts/build_circuits_site.py

# One-off scouting report -> data/scout_257525.md
python3 scripts/scout.py
```

`refresh.py status` is the freshness dashboard: per source it shows **last run** (when each job ran) vs **last data** (newest tournament/game on disk). `batch_scrape.py` (EE backfill over a fixed events file) and `rescrape_empty.py` are legacy one-shots — prefer `refresh.py`.

Freshness ledger: `data/scrape_state.json` is the source of truth (mirrored into the DB's `scrape_runs` + `scrape_content` tables by `build_db.py`). Every batch/discovery script records its run via `scripts/scrape_state.py:record()`.

Verify scraper changes by re-running a single-tournament scrape and inspecting the JSON.

Scraping etiquette (PRD §6): 1 concurrent request, ≥2s EE / ≥1.5s BT delay, honest UA `AAU-Basketball-Aggregator/0.1 (avery@aptoslabs.com)`, exponential backoff on 429/5xx (30s x 2^attempt, max 3 retries per division, then slow to 2x delay -- see `scrape_tournament.py`), throttle cooldown (30m recorded in `scrape_state.json` `throttle` section; entry points wait it out via `throttled_since()`), stop on IP block/takedown. Never store games with `HideScores: true` (filtered at load). BT auth: public app key in `scrape_bracketteam.py:API_KEY` (embedded in their JS bundle), sent as `X-Authorization`; robots.txt is fully open. Circuit events (Jr. EYBL, 3SSB/3Stripes, UA) carry the prestige multiplier when scraped — most are SoCal-based but NorCal teams travel; camps/tryouts have no bracket games, skip those.

## 3. Architecture & code layout

Pipeline: **discovery → scrape → JSON corpus → SQLite → generated static site**. No server app layer.

- `PRD.md` — the spec: scope (NorCal, 7U–17U/grade/HS, boys+girls), data model, scraping ground rules, Appendices B–D with reverse-engineered exposureevents API findings. Read before touching scrapers.
- `scripts/refresh.py` — orchestrator: EE discovery (`list_events.py` over `[since, today]`) → scrape new NorCal tournaments → BT batch → `build_db.py`. Computes content watermarks (`last_event_end/id`, `last_game_date`) from JSON on disk.
- `scripts/list_events.py` — pages the CA events listing (`/youth-basketball-events/california`), extracts `X-Exposure-Token` from page HTML, POSTs paged JSON → `events_ca*.json`.
- `scripts/scrape_tournament.py` — EE core: GETs `{BASE}/{tid}/{slug}/schedule`, regex-extracts embedded `divisions: [...]` JS, POSTs per-division to `/eventgames` XHR, stamps games with `_division_id/_division_name/_day_group` → `<tid>.json`.
- `scripts/scrape_bracketteam.py` + `batch_scrape_bracketteam.py` — BT side: paged `advanced-events-search` (sport_id=2) filtered by `is_norcal()`, then per-division `get-division-schedule` → `bt_<eid>.json`. BT index only surfaces recent/upcoming events (oldest ~Aug 2026 as of Oct 2026) — it's the going-forward source; history lives in EE.
- `scripts/build_db.py` — loads `data/[0-9]*.json` → `ee_*` tables, `data/bt_*.json` → `bt_*` tables, ledger → `scrape_runs`/`scrape_content`, and resolves every (raw name, division) pair → `team_names`/`teams` via `team_identity.py`. BT winners derived from scores (`H`/`A`/NULL); forfeits/sets stored as-is.
- Team identity (`scripts/team_identity.py`): `normalize()` (deterministic: strip `#N` ranks, unify separators, extract age/grade/gender) + `OVERRIDES` (curated: TM Falcons/Griffins aliases, Cali Gold ranks, Tarheels colors) + `SUCCESSORS` (grade-up links: `tm:falcons`→`tm:falcons-14u`, `tm:griffins`→`tm:griffins-12u`) + level-split (bare names resolve per-division age: 14U Gold Fury ≠ 10U Fury). Query pattern: join `ee_games`/`bt_games` → `team_names` on `(raw_name, division_hint)`, filter by `team_id`. `bare`-confidence rows are ambiguous program labels — never merge across divisions.
- `data/` — the corpus: one JSON per tournament/event, `events_ca*.json` snapshots, `scrape_state.json`, logs, `aau.db`. Empty `divisions: []`/`games: []` means unpublished schedule — valid empty state, not an error.
- `scripts/scout.py` — single-use report for the May 30–31 2026 invitational. **Not generic tooling**: tournament id, rosters, opponent regexes, division filters all hardcoded. Its `data/[0-9]*.json` glob intentionally skips `events_*.json`.
- `scripts/rank_teams.py` — generic form ranking: per-game credit scaled by opponent strength (win: tier x decay x margin x (0.25+0.75xopp); loss: tier x decay x margin x 0.25xopp), iterated 15 rounds; tier weights nat 1.0 / up .85 / gold .75 / open .5 / silver .5 / bronze .25, decay full <90d to 0 at 1yr; margin is a log curve capped at 25 (squeaker ~0.85x, median ~1.0x, 20pts ~1.15x; close losses keep consolation, `--no-margin` disables); opponents with <9 games contribute no opp strength (ghosts); ranked-win gate: only prelim top-10 confer transitive credit (`--ranked-win-top 0` disables); NorCal membership gate: circuit-only (SoCal) + house-league teams don't rank (`--no-norcal-gate` disables); published scores shrink by n/(n+8) sample-size prior (`--shrink-k 0` disables). Prints sos + vs-ranked/unranked H2H columns. `--no-sos` recovers pure form. Optional tournament-city radius (`--region/--miles`). Backs the `rank-teams` skill (`.claude/skills/rank-teams/SKILL.md`). Region filters by *tournament city*, never team hometown (corpus has no hometowns).

Key invariants: `divisionteamid` is the durable per-team-per-tournament key (PRD App. C) — use it, not the team slug (tier inconsistently encoded). Never derive division/tier from slugs; parse the division string. Team names are noisy (`Program – Coach – AgeU`); regex matching needs an age-division filter or cohorts collide (see `DIV_*` in `scout.py`).

**ID-type convention (hardened Nov 2026 after a silent-drop bug):** EE `tournament_id` may be int or str on disk depending on scraper vintage (`scrape_tournament.py` now writes int; older files vary). BT `event_id` is int; FB ids are `fb`-prefixed strings (separate namespace, no collision with EE/BT numerics). Rule: **normalize at the boundary, never compare raw JSON ids.** `rank_teams.games_for_team` guarantees `g[4]` is str (ID INVARIANT); `build_db` coerces (`str()` EE/FB, `int()` BT); site builders (`build_organizers`, `compute_org_strength`) coerce to int at load. New loaders/comparisons must do the same -- an un-normalized int-vs-str dict lookup fails silently and drops data with no error.

## 4. Tech stack & key dependencies

Python 3 stdlib only (`urllib` + `http.cookiejar`; the `/eventgames` XHR spike made the PRD's suggested Playwright unnecessary). Sources: `basketball.exposureevents.com` (HTML + JSON XHR) and `bracketteam.com` (public JSON API, Angular SPA with empty HTML shell). Store: flat JSON (immutable cache per PRD) + SQLite (`data/aau.db`, rebuilt from scratch by `build_db.py`). No framework yet.

## 5. Conventions & gotchas

- Division names vary **per tournament** — normalize all three: `11u - Boys (Pink)` vs `Boys - 13U/7th Grade - 2031` (trailing number = grad year, strip it) vs `13U/7th Grade Gold` (PRD App. B). Case-insensitive; `(Color)`, trailing `Color`, `/Color` suffixes are equivalent tiers.
- `list_events.py` / `scrape_tournament.py` regex-scrape `tokenValue` / `divisions: [...]` out of HTML — both break silently on site re-renders; check raw responses first when they return nothing.
- `scout.py` derives W/L from `*IsWinner` + `Status == "Final"`; forfeit scores like `F-W` are strings (try/except) — keep that pattern.
- `research/` is an empty placeholder. Scraped JSON is the corpus — don't hand-edit; re-scrape.
- EE re-scrapes are cheap but pointless for schedule-less tournaments: the Oct 29 `rescrape-empty` run filled 0/199 (3 HTTP 410s). Check `scrape_state.json` before re-running bulk jobs.
