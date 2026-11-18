# PRD — Bay Area / NorCal AAU Team History

**Status:** Draft v0.2
**Owner:** Avery
**Last updated:** 2026-05-29

## 1. Problem

Parents and players researching an upcoming AAU opponent have to dig across multiple tournament sites (exposureevents.com, bracketteam.com, individual program sites) to answer basic questions:

- Who is this team? What tournaments do they play?
- How are they doing this season?
- Are they a tier above or below us?

Information is fragmented per-tournament and per-source. There is no consolidated, multi-season profile per Bay Area team. Worse, the *same team* shows up under different names across sources because tournaments often list teams as "Program – Coach Lastname – AgeU" rather than a canonical program name.

## 2. Goal

A web app where you type a Bay Area / NorCal AAU team name and get a single page showing:

- Tournament history (which tournaments, when, finish/bracket result)
- Recent game results with scores and opponents
- Season win/loss record
- Other regional teams they regularly play
- Age group, gender, and program affiliation

## 3. Non-goals (V1)

- Individual player stats, rosters, or recruiting info
- Live in-game score updates
- Power rankings / predictions
- Coverage outside Northern California
- Mobile app (responsive web is enough)

## 4. Primary users

Parents and players researching an upcoming opponent. Secondary: coaches doing the same.

### User stories

1. *"We play LakeShow 14U next weekend — how have they done this spring?"*
2. *"What tournaments does SV Soldiers usually enter? Are they a tier above us?"*
3. *"Show me every NorCal team in 12U boys, sorted by recent results."*
4. *"Our opponent just popped up on the bracket — pull their info now."*
5. *"This team is listed as 'Soldiers — Coach Smith 13U'. Who are they really?"*

## 5. Scope

### Geographic

All of Northern California — SF, East Bay, South Bay, Peninsula, Tri-Valley, North Bay, Sacramento, Central Valley, Monterey. Use a region whitelist (counties or city list) to gate which teams get pulled into the directory by default; auto-discovered teams from outside the region get flagged but still stored.

### Age groups (first-class)

- **Age-based:** 7U, 8U, 9U, 10U, 11U, 12U, 13U, 14U, 15U, 16U, 17U
- **Grade-based:** 2nd–12th grade (many programs roster this way)
- **HS-level:** Varsity, JV, Frosh-Soph

A team belongs to *one* (program, age_group, gender) tuple per season. Normalize grade↔age where possible (e.g., 5th grade ≈ 11U, 6th grade ≈ 12U) but show both labels when the source uses grade.

### Gender

Boys, girls. Track separately even when programs run both.

### Verified seed teams (from Avery)

| Short | Verified name | Source | Notes |
|---|---|---|---|
| SV Soldiers | Silicon Valley Soldiers | siliconvalleysoldiers.org | Affiliated with Oakland Soldiers |
| Oakland Soldiers | Oakland Soldiers | — | Nike EYBL program |
| LakeShow | LakeShow Hoops | lakeshowhoops.com | |
| LAVA | Bay Area Lava | bayarealava.com | Dublin / Tri-Valley, founded 2019 |
| WHPH | WHPH (aka SF Soldiers Basketball) | whphbasketball.com | Domain WHPH, page brands as "SF Soldiers" — needs clarification |
| Spartans | San Jose Spartans | sanjosespartans.com | Santa Clara Valley non-profit |
| TM Falcons | TM Falcons | exposureevents (e.g. `tm-falcons-black`, division "13u - Boys (White)") | Tracked explicitly. "Black"/etc. are tiers; multiple cohorts likely. |
| TM Griffins | TM Griffins | exposureevents (`tm-griffins`, division "11u - Boys (Pink)") | Tracked explicitly. Sibling program to TM Falcons under the "TM" umbrella, but distinct (different age band). |
| BGA | ? | — | **Needs verification — expansion unknown** |
| All-In | ? | — | **Needs verification** |

### Proposed additional NorCal programs (research candidates)

These came up in research as active NorCal programs. Confirm and add to the directory:

**East Bay**
- Bay Area Wildcats (Oakland)
- Oakland Rebels
- Alameda Youth Basketball (AYB)
- Alameda Vipers
- BullDawgs Basketball Club
- JustHoop (San Leandro / Castro Valley / Oakland / Hayward)
- East Bay Waves
- NorCal Elite Basketball Club (Walnut Creek)

**South Bay / Peninsula**
- Bay Area Mambas (Fremont)
- Team12Sports (Belmont / Burlingame / SF)
- Team NorCal Basketball
- SV Stars (siliconvalleynjb.com)
- SVBA — Silicon Valley Basketball Academy
- SVBC — Silicon Valley Basketball Club

**San Francisco**
- Bay City Basketball
- San Francisco Rebels
- SFBA (SFBA Sport Performance)
- Junior Warriors

**NorCal / Central Valley**
- Team Arsenal AAU
- PHPS NorCal Pharaohs Elite
- PHPS Renegades
- Cal Stars
- West Coast Elite
- Nor Cal Heat Elite (Patterson)

### How the directory grows

1. **Auto-discover:** any team appearing in a NorCal tournament bracket on a supported source gets added as a stub.
2. **On-demand fetch:** user types a team name → scraper enqueues a fresh pull for tournaments mentioning that team.
3. **Manual seeding:** Avery curates aliases and marks teams as NorCal when geography is ambiguous.

## 6. Data sources

### Confirmed

| Source | Status | Notes |
|---|---|---|
| `bracketteam.com` | **Primary** | robots.txt fully open; permissive crawling. |
| `basketball.exposureevents.com` | **Primary** | robots.txt disallows `/api/v1/`, `/*/*/eventgames`, `/*/*/results`, `/*/*/statistics`. **Per Avery, we ignore robots.txt for this source** and scrape these endpoints. ToS not yet read (terms page returned 403/404 — confirm later). |

### Ground rules for exposureevents scraping

Since we're proceeding past their robots.txt, minimize footprint and risk:

- **Rate limit hard.** Single concurrent request, ≥ 2s delay between fetches. Back off exponentially on 429/5xx.
- **Identify ourselves.** Honest User-Agent string with project name and contact email.
- **Cache aggressively.** Treat tournament results as immutable once an event is over; don't re-fetch.
- **Scrape rendered HTML, not the API.** The `/api/v1/` endpoints are explicitly off-limits; reading the same data from the public HTML pages is a softer line.
- **Stop on signal.** If they block our IP or send a takedown, stop and switch to bracketteam-only fallback.
- **Re-check ToS.** Once we can access their `/terms` page, confirm there's no clause that would make this legally risky (e.g. CFAA-style "authorized access" language).

### Other candidate sources (to evaluate in Phase 0)

- Program-specific sites (Soldiers, LakeShow, etc.) often publish their own schedules
- Other tournament hosts: PrepCircuit, Hoop Group, TournamentSR, AAUTourneys, etc.

## 7. Data model

```
Program
  id, canonical_name, region, website, aliases[], parent_program_id (nullable)
  -- parent_program_id supports umbrellas like "TM" with siblings TM Falcons & TM Griffins

Team  (a roster cohort within a program for one season)
  id, program_id, season, age_group_age (7U-17U|null), age_group_grade (2-12|null),
  gender (M|F), coach_lastname (nullable), source_team_names[] (raw strings seen)

Tournament
  id, name, location, start_date, end_date, source, source_url

Game
  id, tournament_id, team_a_id, team_b_id,
  score_a, score_b, date, round (pool|bracket_round_N|championship)

TeamSeason  (materialized view)
  team_id, season, wins, losses, tournaments_played[], avg_margin

TeamAlias  (for fuzzy matching across sources)
  team_id, alias_string, source, confidence
```

### Identity resolution — the hard problem

Real examples from the G365 Sactown Swish tournament (see Appendix B):

- Same program, different age groups (clearly distinct teams):
  - "Renegades" appears in 10U Bronze, 11U, 12U Gold, 13U Silver, 14U Gold, 15U West
- Same program + age, distinguished by color/tier:
  - "Sac Gaels Blue" vs "Sac Gaels Red" (14U Silver)
  - "Vista Talons Blue" vs "Vista Talons White" (13U Silver / Bronze)
  - "Chopp Academy Green" vs "Chopp Academy Grey" (15U East)
  - "Top Flight Elite - Red 1" vs "Top Flight Elite - Red 2" (14U Silver / Bronze)
  - "WeCompete Nation Grizzlies Elite" vs "WeCompete Nation Grizzlies Black"
- Same program + age, distinguished by coach:
  - "DBC 4th (Watts)" — coach in parentheses
  - "Top Flight Elite 6th - Coach Eugene" — coach with "Coach" label and dash
  - "Top Flight Elite (Eugene)" — same coach, different format in a different division
- Age tag inconsistency in same name:
  - "Bay City 10u Select", "Bay City 5th Black", "Bay City 7th Black" — age sometimes as age-U, sometimes as grade
  - "PMA Knights East Bay 12u" — age embedded mid-string
- Region/area-code prefixes that look like part of the program name:
  - "209 Heat" (Central Valley), "707 Soldiers" (North Bay), "916 Dream Chasers" (Sacramento)
  - "13U B2B Built", "14U B2B Pressure", "16U B2B Grind", "17U B2B Prime" — leading number is age, program is "B2B"

**Parsing rules:**

1. **Strip and capture age tokens:** patterns like `\b(7|8|9|10|11|12|13|14|15|16|17)[Uu]\b`, `\b(2nd|3rd|...|12th)\b`. If present both as prefix and suffix, prefer the suffix (e.g. "13U B2B Built" → age=13U, leftover="B2B Built"; "Bay City 7th Black" → age=7th≈13U, leftover="Bay City Black").
2. **Capture coach lastname:** `\(([A-Z][a-z]+)\)$` or `(?:Coach )?([A-Z][a-z]+)$` after a dash.
3. **Capture tier/color:** trailing tokens from a vocabulary `{Black, White, Red, Blue, Green, Grey, Gold, Silver, Bronze, Elite, Select, Premier, Gold, National, Regional, 1, 2}` — first pass uses a hand-tuned set, expanded over time.
4. **Capture gender:** `Girls`/`Lady` → F; otherwise assume M (matches site convention where only girls divisions are explicitly marked, e.g. "HS Girls", "Lady Soldiers").
5. **Remaining tokens = program candidate.** Fuzzy match (Levenshtein + token-set ratio) against curated program alias table.
6. **Composite key for a team:** `(program_id, season, age_group, gender, coach_lastname OR tier_label)`. If neither coach nor tier disambiguates, assume single team; flag for review if a second roster appears.
7. **Always preserve raw strings** in `source_team_names[]` for debugging and re-parsing when rules change.

**Special case — "Lakeshow Elite":** appears in 13U Gold and 13U Silver of this tournament. Likely the user's "LakeShow Hoops" program. Add "Lakeshow Elite" → LakeShow Hoops as an alias. Two 13U entries in the same tournament means *either* (a) two cohorts (need coach/tier to distinguish — neither shown here, flag for manual review) or (b) the source listed them inconsistently.

V1 ships with rules + manual merge override; heuristics improve as data accumulates.

## 8. Key features (V1)

### Team profile page

- Header: program, age group (age + grade), gender, coach (if applicable), aliases shown
- Tournament history table: tournament, date, finish (e.g. "lost in semis"), W-L in that event
- Recent games list: date, opponent (linked), score, tournament
- Season summary: W-L, tournaments entered, common opponents
- "Refresh" button → triggers on-demand re-scrape for this team

### Team directory

- Searchable by name + alias + coach lastname
- Filter by age group (age and/or grade), gender, region, program
- Sort by recent activity / W-L / program

### Program page

- All teams under a program across age groups and genders
- Program-level activity (where they play, total events)

### Tournament page

- Bracket view (if source provides)
- List of participating teams (linked to profiles)
- Date, location, source link

### Search

- Single search box, top of every page
- Matches canonical names + aliases + coach lastnames (e.g. "TM Johnson 13U" resolves)
- Typeahead suggestions

### Admin / merge UI (V1, minimal)

- List of "suspected duplicates" — pairs with high similarity but unconfirmed
- One-click merge / split / mark as different
- Edit canonical program names and aliases

## 9. Ingestion strategy

- **Scheduled scrape:** weekly cron pulls new/active tournament data from each source.
- **On-demand fetch:** team profile "Refresh" enqueues a job that re-scrapes any tournaments mentioning that team.
- **Backfill:** Phase 0 one-time historical pull for each source going back ~2 seasons.
- **Dedup:** same game from two sources merges on (date, both team aliases, score).
- **Politeness:** rate-limited, identifies via User-Agent string, caches aggressively. Respects robots.txt for `bracketteam.com`; deliberately ignores it for `basketball.exposureevents.com` (see §6 ground rules).

## 10. Tech stack

- **Frontend / backend:** Next.js (App Router)
- **Database:** Postgres
- **Job queue:** BullMQ (Redis) or pg-boss (Postgres-only — simpler)
- **Scraping:** Plain fetch + light HTML parsing for both primary sources. exposureevents data turns out to be served by an XHR endpoint that returns clean JSON (see Appendix D) — no headless browser needed. Keep Playwright in the toolkit for unknown future sources, but it's not required for V1.
- **Hosting:** Vercel (web) + Neon/Railway (Postgres) + Upstash (Redis if BullMQ)
- **Auth (later):** Clerk or NextAuth — V1 is public read-only

## 11. Open questions

1. **BGA / All-In** — what are the full program names? Couldn't verify from public sources. (TM = TM Falcons, confirmed.)
2. **WHPH vs SF Soldiers** — same program or related-but-distinct? Their website uses both names.
3. **Grade↔age mapping** — is the standard `grade + 6 = age_group` close enough, or do we need a per-tournament override?
4. **Admin auth** — who can do merges in V1? Just you, or a small trusted group?

## 12. Phased roadmap

**Phase 0 — Research & spike (1–2 weeks)**
- Verify TM, BGA, All-In program names
- Confirm/refine the proposed NorCal program list
- bracketteam.com scrape feasibility: end-to-end pull of one tournament
- exposureevents scrape feasibility: end-to-end pull of one tournament (HTML pages, with rate limit + custom UA)
- Build single team profile vertical slice: scrape → store → render
- Read exposureevents ToS once accessible; flag anything legally concerning

**Phase 1 — MVP (4–6 weeks)**
- Ingestion pipeline (scheduled + on-demand) for bracketteam.com **and** basketball.exposureevents.com
- Identity resolution (rules + alias table + manual merge UI)
- Team profile, program page, directory, search
- Full coverage of seed list + proposed programs across current season

**Phase 2 — Coverage & quality**
- Add more sources (program sites)
- Auto-discover NorCal teams from brackets
- Improve merge heuristics with feedback from real data

**Phase 3 — Nice-to-haves**
- Tournament comparison view
- Head-to-head history between two teams
- Notifications ("LakeShow's next tournament is…")
- Embed-friendly team cards
- Public API

## 13. Success metrics

- # of NorCal teams with ≥ 1 tournament tracked
- Avg games per team in last 90 days
- Fresh-data SLA: weekly scrape lands < 24h after tournament completes
- Identity-resolution quality: < 5% of teams flagged as "needs merge review" after 2 months
- Qualitative: "I found what I needed" feedback from a handful of parents

---

## Appendix B — Real example: G365 Sactown Swish

URL: https://basketball.exposureevents.com/252018/g365-sactown-swish/teams

**URL pattern:** `/{tournament_id}/{tournament-slug}/teams[/{team-slug}]`
- `252018` = numeric tournament ID
- `g365-sactown-swish` = human-readable slug (probably derived from name)
- Team detail pages exist at `…/teams/{team-slug}`

**Tournament metadata available on this page:**
- Name: "G365 Sactown Swish"
- Dates: May 30–31, 2026
- Location: Roseville, CA
- Organizer: Grassroots 365

**Division naming convention observed:**
- `10U/4th Grade Gold`, `12U/6th Bronze`, `15U West`, `16U East`, `HS Girls`, etc.
- Encodes: age (NU), grade (Nth), tier (Gold/Silver/Bronze), bracket region (East/West — *within tournament*, not geography), gender (only "Girls" marked; boys is the implicit default).

**Divisions and team counts (this tournament):**

| Division | Teams |
|---|---|
| 10U/4th Grade Gold | 4 |
| 10U/4th Grade Bronze | 4 |
| 11U/5th Grade | 7 |
| 12U/6th Gold/Silver | 8 |
| 12U/6th Bronze | 5 |
| 13U/7th Gold | 4 |
| 13U/7th Silver | 7 |
| 13U/7th Bronze | 5 |
| 14U/8th Gold | 7 |
| 14U/8th Silver | 8 |
| 14U/8th Bronze | 9 |
| 15U West / East | 5 / 8 |
| 16U West / East | 4 / 4 |
| 17U West / East | 4 / 5 |
| HS Girls | 3 |

**Programs spotted in this tournament not already in §5:**

209 Heat, 707 Soldiers, 916 Dream Chasers, AIBA, B2B, Bay Area Lakers, Bay City, Chico Tarheels, Chopp Academy, Crossover, CTBxGU, DBC, Delta Heat, Dream Team, Eden Athletic Club, Golden State Dubs, Gym Rats, JBE / Just Breathe Elite, Just Us Basketball, Lady Soldiers, Lakeshow Elite *(likely = LakeShow Hoops)*, M.I.E, OGB Elite, Orland Panthers, Payton's Place Elite, PMA Knights, PTPYB, Renegades, Sac Dream Basketball, Sac Gaels, Sacramento Yellow Jackets, Sactown Panthers, Showtime XVI, Start II Finish, Swish Army, Team Esface, Team Rize, Team TET, Top Flight Elite, Triple Threat (Regional / National), Tumakbo, Vista Talons, WeCompete Nation, YBA (Rize / Elite Rize / Evolution)

This single tournament alone roughly **doubles** our known-program count and confirms auto-discovery from brackets is the right strategy.

---

## Appendix D — exposureevents data API (reverse-engineered)

The SPA is built on Knockout.js and loads game data via XHR. Plain page-source fetches show no scores; the XHR endpoint returns clean JSON.

### Recipe — discover tournaments (events search)

The `youth-basketball-events/{state}` page lists tournaments. The page itself loads them via XHR back to its own URL.

1. **GET** `/youth-basketball-events/california` — establishes session cookies, embeds `tokenValue: '…'` in inline JS.
2. **POST** the same URL with:
   - `Content-Type: application/json` *(this is the trap — the SPA's `app.call` defaults to JSON, not form-encoded)*
   - `X-Exposure-Token: <tokenValue>`
   - `X-Requested-With: XMLHttpRequest`
   - Session cookie
   - Body: `{"Page": N, "sportType": 1, "StartDateString": "M/D/YYYY", "EndDateString": "M/D/YYYY"}`
3. Response: `{Total, Page, PageSize, Results: [...]}` — Results have `Id`, `Name`, `Slug`, `StartDate`, `EndDate`, `City`, `OrganizationId`, etc.

Limits:
- 50 results per page; page until `len(seen) >= Total`.
- Date range must not exceed 1 year (API error `Code 19: Start Date/End Date must not exceed a year`).
- Without a date range, only *future* events are returned (~553 in CA as of 2026-05-30). With a 12-month past window, ~1,617 CA events surface.

State scoping: the URL path (`/california`) is the only state hint that works — `stateRegion` in body is partially honored but unreliable.

### Recipe — fetch games (per tournament, per division)

1. **GET** `https://basketball.exposureevents.com/{tid}/{slug}/schedule`
   - Establishes a session cookie.
   - Inline `<script>` block initializes `app.viewModel.schedule` with the full **divisions list** as JSON: `divisions: [{Id, Name}, ...]`. Parse with a regex like `/divisions:\s*(\[.+?\]),/s`.
   - Also exposes `gamesUrl`, `standingsUrl`, `statisticsUrl`, `bracketUrl`, and `locations[]`.

2. **POST** `https://basketball.exposureevents.com/{tid}/{slug}/eventgames`
   - Headers:
     - `X-Requested-With: XMLHttpRequest` *(required — plain GET returns 401)*
     - `Referer: …/schedule`
     - `Accept: application/json, text/javascript, */*; q=0.01`
     - `Content-Type: application/x-www-form-urlencoded; charset=UTF-8`
   - Body: `divisionid={N}&eventid={tid}`
   - Cookie: session from step 1
   - Response: JSON array of game-day groups:
     ```jsonc
     [
       { "Name": "Saturday, May 9, 2026",
         "Open": true,
         "Games": [ { Game }, ... ] }
     ]
     ```

### Game object — fields we care about

| Field | Use |
|---|---|
| `Id` | Source-side game primary key |
| `DivisionId`, `DivisionName` | Division this game belongs to |
| `HomeDivisionTeamId`, `AwayDivisionTeamId` | Per-team-per-tournament IDs — the durable key |
| `HomeTeamName`, `AwayTeamName` | Raw display strings (need parsing for program/tier/coach/age) |
| `HomeTeamNameSlug`, `AwayTeamNameSlug` | URL slugs (sometimes encode tier, sometimes don't — don't trust) |
| `HomeTeamScoreDisplay`, `AwayTeamScoreDisplay` | Scores (string) |
| `HomeTeamIsWinner`, `AwayTeamIsWinner` | Win flags |
| `Status` | "Final", "Scheduled", "In Progress", etc. |
| `HideScores` | Per-game suppression flag (respect it) |
| `GameTypeName` | "Pool A", "Gold (G2)", "Platinum (G5)", etc. — useful for round inference |
| `VenueName`, `CourtName`, `Venue` | Location |
| `DateFormatted`, `TimeFormatted`, `TimeZone` | Game datetime |
| `Started` | Live-game flag |

### Verified working example

`POST /247159/alicia-renee-anderson-memorial-shootout/eventgames` with `divisionid=1207171` returned the 11U Pink division's complete schedule including:
- *Pool B Final*: TM Griffins beat Dublin United and beat Firmly Rooted EOYDC — TM Griffins went 2-0 in pool play.

`POST /253070/las-vegas-memorial-day-classic/eventgames` with `divisionid=1342856` returned TM Falcons' four 13U games at Vegas Memorial Day Classic (lost three pool games to Team Right Now, R&T Lions, Vegas Elite - Gray; beat Central Valley Legends 59–46 in the consolation round).

### Division naming — yet another variant

Same site, different tournaments use very different division name formats:
- Alicia Renee (Hayward, May 2026): `11u - Boys (Pink)`, `13u - Boys (White)`, `Girls High School`
- LV Memorial Day Classic: `Boys - 13U/7th Grade - 2031`, `Girls - 12U/13U - 2031/2032`
- G365 Sactown Swish: `13U/7th Grade Gold`, `15U East`, `HS Girls`

The `- 2031`-style suffix is the projected HS graduation year (recruiting-class convention). Normalizer needs to handle all three. Strip year suffix when present.

### Ground rules carried over from §6

- Rate limit (1 concurrent, ≥2s delay) and back off on 429/5xx
- Honest UA string
- Cache aggressively (completed tournament games are immutable)
- Stop on IP block or takedown
- Don't store games where `HideScores: true`

---

## Appendix C — Team detail page learnings (TM Falcons Black)

URL: `https://basketball.exposureevents.com/247159/alicia-renee-anderson-memorial-shootout/teams/tm-falcons-black?divisionteamid=5240173`

**URL pattern (team within tournament):**
`/{tournament_id}/{tournament-slug}/teams/{team-slug}?divisionteamid={N}`
- `divisionteamid` is the durable per-team-per-tournament identifier — use as the source-side primary key when scraping.

**Division string format on team page differs from list page:**
- List page: `13U/7th Bronze` (combines age + grade + tier, slash-separated)
- Team page: `13u - Boys (White)` (lowercase age, gender explicit, tier in parens)
- Implication: parser must handle multiple formats; do case-insensitive matching; treat `(Color)` and trailing `Color` and slash-suffix `/Color` as equivalent tier expressions.

**Scores are JavaScript-rendered.** Plain HTTP fetches return empty schedule sections. Confirmed by attempting `/results` and `/eventgames` (404) and `/schedule` (returns shell but "No scheduled games found" — content loads via JS). This is why §10 commits to **Playwright as required**, not optional.

**Empty-schedule case:** When a tournament hasn't published its schedule yet, the team page shows: *"This participant isn't participating in any games or the schedule hasn't been posted yet."* Treat this as a valid empty state; re-scrape later. Don't store as "0 games played."

**Team slug inconsistency (same tournament, two TM teams):**
- `tm-falcons-black` (tier in slug) — division "13u - Boys (White)"
- `tm-griffins` (no tier in slug) — division "11u - Boys (Pink)"
- Tier may or may not be encoded in the slug. **Do not rely on slug to derive tier/division** — always parse from the division string on the page. Use `divisionteamid` as the source-side primary key.

**"TM" is an umbrella, not a single program:**
- TM Falcons (13U Boys in this tournament) and TM Griffins (11U Boys) are *distinct programs/cohorts* under the TM umbrella. Avery wants both tracked explicitly. Modeling implication: it's fine to have a "TM" Program record with Falcons / Griffins as siblings, OR to have two top-level Programs ("TM Falcons", "TM Griffins") that share a `parent_program` reference. Pick the simpler one for V1 (probably two top-level Programs + an optional `parent_program` field).

**Open scraping questions resolved by Appendix D spike:** the SPA calls a per-event `/eventgames` XHR that returns clean JSON. Per-division fetch (no tournament-wide endpoint found yet — may exist but per-division is sufficient).
