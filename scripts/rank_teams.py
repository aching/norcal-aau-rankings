#!/usr/bin/env python3
"""
Rank teams in an age/grade cohort by last-N-games form.

Usage:
  python3 rank_teams.py --level 14u --last 15
  python3 rank_teams.py --level 8th --last 15 --region 'Palo Alto' --miles 50
  python3 rank_teams.py --level 14u --last 15 --boys-only
  python3 rank_teams.py --level 14u --region 'San Ramon' --miles 25 --min-games 5

What it does:
  1. Finds team_ids in `teams` at the requested level (e.g. 14u, 8th).
  2. For each team, joins ee_games/bt_games -> team_names on
     (raw_name, division_hint) and takes the N most recent Finals.
  3. Ranks by (win%, then point margin, then games played).

Region filter:
  The corpus has no per-team hometowns — it has tournament Cities
  (events_ca*.json snapshots + venue/city on games). So the filter keeps
  only games played at tournaments whose City is within --miles of
  --region. A small Bay Area city-coordinate table lives below; teams
  are NOT geolocated, their games are.

  This means: it answers "who's hottest among teams that play near X",
  not "which teams are headquartered near X".

W/L rules (mirror scout.py + build_db.py):
  EE: Status == 'Final' decides played; HomeTeamIsWinner/AwayTeamIsWinner
      flags decide the winner. Forfeit scores ('F-W' strings) carry winner
      flags, so they count as W/L. HideScores games never reach the DB.
  BT: has_result=1 decides played; winner 'H'/'A' decides; forfeits and
      unscheduled/exhibition (has_result=0, NULL rows) are skipped.

Caveats printed with every run:
  - `bare`-confidence team_ids (e.g. prog:renegades) are ambiguous program
    labels merged across divisions — excluded by default (--include-bare).
  - Teams with fewer than --min-games are listed separately, unranked.
  - Girls divisions are included unless --boys-only / --girls-only.
  - Coaching labels (Lo/Harvey/Josh) and color squads (Black/Orange) are
    separate team_ids and rank separately.
"""
import argparse
import json
import glob
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from upcoming_games import fastbreak_date

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
DB = DATA / "aau.db"

# Approximate city centroids (city name fragment -> lat, lon).
# Keys match on substring of the snapshot City / game venue string.
CITY_COORDS = {
    "palo alto": (37.4419, -122.1430),
    "san ramon": (37.7799, -121.9780),
    "san jose": (37.3382, -121.8863),
    "santa clara": (37.3541, -121.9552),
    "oakland": (37.8044, -122.2711),
    "san leandro": (37.7249, -122.1561),
    "richmond": (37.9358, -122.3477),
    "san francisco": (37.7749, -122.4194),
    "daly city": (37.6879, -122.4702),
    "san mateo": (37.5630, -122.3255),
    "redwood city": (37.4852, -122.2364),
    "menlo park": (37.4530, -122.1817),
    "mountain view": (37.3861, -122.0839),
    "sunnyvale": (37.3688, -122.0363),
    "milpitas": (37.4323, -121.8996),
    "fremont": (37.5485, -121.9886),
    "hayward": (37.6690, -122.0808),
    "union city": (37.5934, -122.0438),
    "newark": (37.5297, -122.0402),
    "livermore": (37.6819, -121.7680),
    "walnut creek": (37.9101, -122.0652),
    "concord": (37.9780, -121.9438),
    "berkeley": (37.8715, -122.2730),
    "alameda": (37.7652, -122.2416),
    "sacramento": (38.5816, -121.4944),
    "rocklin": (38.7907, -121.2358),
    "stockton": (37.9577, -121.2908),
    "vallejo": (38.1041, -122.2566),
    "fairfield": (38.2494, -122.0390),
    "east bay": (37.8044, -122.2711),  # "East Bay Area" -> Oakland centroid
    "bay area": (37.7749, -122.4194),  # bare "Bay Area" -> SF centroid
}

MI_PER_DEG_LAT = 69.0

# Division tier -> weight. Checked as case-insensitive regexes against the
# division string; a division matching 2+ bands (e.g. "Gold/Silver",
# "D2/D3") gets ("mix", average). Anything else is ("open", 0.5):
# parallel color pools (Black/White/Red), plain "14u"/"8th Boys", etc.
# D1/D2/D3 ladders map onto gold/silver/bronze. Playing-up divisions
# (JV/Varsity/Upperclass/Frosh) get "up". BT's ELITE/Main Event read as
# national; its developmental ladders fall to open (documented limit).
TIER_PATTERNS = [
    # National shoe circuits: EYBL proper (EYBL/E15/E16), EYCL
    # (EYCL 15/16/17), Jr. EYBL (8th/7th/6th grade). These are the
    # highest-prestige competition in the corpus -- above local
    # "national"-named divisions (which stay national 1.0 too; the
    # ceiling logic keys on eyeband, not weight).
    ("national", 1.00, [r"(?<!inter)national(?!s)", r"power\s*32",
                        r"invite only",
                        r"super showcase", r"elite division",
                        r"main event",
                        r"\beybl\b", r"\beycl\b", r"\be1[56]\b",
                        r"jr\.?\s*eybl", r"pit"]),
    ("up",       0.85, [r"varsity", r"\bjv\b", r"upperclass", r"frosh"]),
    ("gold",     0.75, [r"gold", r"(?<![a-z0-9])d1(?![a-z0-9])",
                        r"division\s*1\b", r"divison\s*1\b"]),
    ("silver",   0.50, [r"silver", r"(?<![a-z0-9])d2(?![a-z0-9])",
                        r"division\s*2\b", r"divison\s*2\b",
                        # NorCal Preview flight system (user-confirmed Nov
                        # 2026): National -> American -> International.
                        # American is the second flight = silver weight.
                        # Colors (Black/White/Blue/Red/Yellow) are pool
                        # labels within one bracket, not flights -- they
                        # stay open (no tier info, honestly labeled).
                        r"\bamerican\b"]),
    ("bronze",   0.25, [r"bronze", r"copper", r"(?<![a-z0-9])d3(?![a-z0-9])",
                        r"division\s*3\b", r"divison\s*3\b",
                        # Third flight below American = bronze weight
                        # (was open 0.5x -- the real fix in this change).
                        r"\binternational\b"]),
]
import re as _re
_TIER_RES = [(b, w, [_re.compile(p) for p in ps]) for b, w, ps in TIER_PATTERNS]

BAND_ORDER = ["national", "up", "gold", "open", "silver", "bronze", "mix"]


DEFAULT_WINDOW_DAYS = 365


def is_circuit_event_game(game, circuit_event_ids):
    """Match curated EE event IDs without colliding with BT/FB namespaces."""
    metadata = game[11] if len(game) > 11 and isinstance(game[11], dict) else {}
    if metadata.get("source") not in (None, "ee"):
        return False
    return str(game[4]) in circuit_event_ids


def apply_circuit_tier(games, circuit_event_ids):
    """Use the national tier for verified shoe-circuit event games only."""
    result = []
    for game in games:
        if is_circuit_event_game(game, circuit_event_ids):
            game = game[:2] + (tier_of("national")[1], "national") + game[4:]
        result.append(game)
    return result


def tier_of(division):
    """Return (band, weight) for a division string."""
    s = (division or "").lower()
    hits = [(b, w) for b, w, rs in _TIER_RES if any(r.search(s) for r in rs)]
    if not hits:
        return ("open", 0.5)
    if len(hits) == 1:
        return hits[0]
    bands = sorted(set(b for b, _ in hits))
    return ("mix:" + "/".join(bands),
            sum(w for _, w in hits) / len(hits))


def haversine_miles(a, b):
    lat1, lon1 = a
    lat2, lon2 = b
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    h = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 2 * 69.0 * math.asin(math.sqrt(h))


def city_in_radius(city_str, center, miles):
    """True if any known city fragment in city_str is within miles of center."""
    if not city_str:
        return False
    s = city_str.lower()
    for frag, coord in CITY_COORDS.items():
        if frag in s and haversine_miles(coord, center) <= miles:
            return True
    return False


def resolve_center(region):
    s = region.lower()
    for frag, coord in CITY_COORDS.items():
        if frag in s:
            return coord
    raise SystemExit(f"unknown region {region!r}: no centroid; "
                     f"known: {sorted(CITY_COORDS)}")


def snapshot_cities():
    """tournament_id -> City from events_ca*.json snapshots."""
    out = {}
    for f in sorted(glob.glob(str(DATA / "events_ca*.json"))):
        try:
            evs = json.load(open(f))
        except Exception:
            continue
        for e in evs:
            tid = str(e.get("Id"))
            if tid not in out and e.get("City"):
                out[tid] = e["City"]
    return out


# Prestige operators: winning their 2-day events carries extra weight
# (title bonus). Matched case-insensitively against event-organization
# names and tournament title/slug text.
PRESTIGE_PATTERNS = [
    r"made\s*hoops?",
    r"\bmade\b",
    r"grassroots\s*365?",
    r"\bg365\b",
    r"grassroots",
    r"open\s*gym\s*premier",
    r"\bogp\b",
    r"open\s*gym",
    # national shoe circuits: Nike Jr. EYBL, adidas 3SSB / 3Stripes
    # Gold, Under Armour Next / Rise / Future. Mostly SoCal-based but
    # NorCal teams travel; a circuit win is the highest-prestige
    # signal in the corpus. Camps/tryouts (no bracket games) never
    # match game data anyway, so the pattern is safe to keep broad.
    r"\beybl\b",
    r"jr\.?\s*eybl",
    r"3ssb",
    r"3stripes(\s*gold)?",
    r"earn\s*your\s*stripes",
    r"under\s*armou?r",
    r"\bua\b[\s\-]*(rise|future|next|circuit)",
    r"ua\s*rise",
    r"ua\s*future",
    r"ua\s*next",
]

# EE game_type labels that mark a championship bracket game (as opposed
# to pool play). Consolation is excluded at match time. BT has no
# bracket labels, so BT games never earn title credit.
_CHAMP_RE = _re.compile(r"champ|playoff|bracket|final|semi|quarter", _re.I)
_CONSOL_RE = _re.compile(r"consol", _re.I)
_FAMILY_RE = [("silver", _re.compile(r"silver", _re.I)),
              ("bronze", _re.compile(r"bronze", _re.I)),
              ("gold", _re.compile(r"gold", _re.I))]
_PRESTIGE_RES = [_re.compile(p, _re.I) for p in PRESTIGE_PATTERNS]


def is_champ_game(game_type):
    gt = game_type or ""
    return bool(_CHAMP_RE.search(gt)) and not _CONSOL_RE.search(gt)


def champ_family(game_type):
    gt = game_type or ""
    for fam, rx in _FAMILY_RE:
        if rx.search(gt):
            return fam
    return "main"


_TIME_RE = _re.compile(r"(\d{1,2}):(\d{2})\s*([AaPp])\.?[Mm]\.?")


def _time_key(t):
    """Chronological key for EE time strings like '2:30 PM PDT'.

    Lexicographic string order is NOT chronological across 12-hour
    AM/PM times ('8:30 AM' > '2:30 PM' as strings) -- that bug crowned
    the winner of an 8:30 AM quarterfinal as champion over the 2:30 PM
    final (Fall Extravaganza 275768, user-confirmed Nov 2026)."""
    m = _TIME_RE.search(t or "")
    if not m:
        return (1, 0, t or "")  # unparseable/TBD sorts after real times
    hh, mm, ap = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    hh = (hh % 12) + (12 if ap == "p" else 0)
    return (0, hh * 60 + mm, t or "")


def prestige_events(cur):
    """Return set of prestige tournament_ids (EE) + prestige BT event_ids.

    Made Hoops / Grassroots365 / OGP, matched case-insensitively on org
    name (EE snapshots) or tournament title/slug (EE) / event name (BT).
    """
    prestige_ee, prestige_bt = set(), set()
    try:
        slugs = {t[0]: (t[1], t[2]) for t in
                 cur.execute("SELECT tournament_id, slug, title "
                             "FROM ee_tournaments")}
    except Exception:
        slugs = {}
    for tid, (slug, title) in slugs.items():
        text = " ".join(x for x in (slug, title) if x)
        if any(rx.search(text) for rx in _PRESTIGE_RES):
            prestige_ee.add(tid)
    try:
        import json as _json, glob as _glob
        for f in _glob.glob(str(DATA / "events_ca*.json")):
            try:
                evs = _json.load(open(f))
            except Exception:
                continue
            for e in evs:
                o = (e.get("OrganizationName") or "")
                if any(rx.search(o) for rx in _PRESTIGE_RES):
                    prestige_ee.add(str(e.get("Id")))
    except Exception:
        pass
    try:
        for eid, name in cur.execute("SELECT event_id, name FROM bt_events"):
            if any(rx.search(name or "") for rx in _PRESTIGE_RES):
                # str to match the g[4] ID INVARIANT (games_for_team).
                prestige_bt.add(str(eid))
    except Exception:
        pass
    return prestige_ee, prestige_bt


def title_events(cur, min_teams=8, prestige_boost=1.5):
    """Detect per-team tournament titles from EE games.

    Eligible: a (tournament, division) with games on 2+ distinct dates
    and >= min_teams distinct teams. Within each eligible division,
    championship-bracket games (non-consolation) group into families
    (silver/bronze/gold/main by label); the winner of the last
    chronological family game is the champion, the loser the runner-up.

    Returns dict team_id -> list of title dicts. Prestige events (Made
    Hoops / Grassroots365 / OGP, matched on org name or title/slug)
    are flagged for the larger bonus.
    """
    rows = cur.execute(
        """SELECT rowid, tournament_id, division_id, division_name,
                  game_type, date, time, home_team, away_team,
                  home_won, away_won, home_slug, away_slug,
                  home_dt_id, away_dt_id
           FROM ee_games WHERE status = 'Final'""").fetchall()
    per = {}
    for r in rows:
        per.setdefault((r[1], r[3]), []).append(r)
    prestige, _ = prestige_events(cur)
    titles = {}
    for (tid, div), gs in per.items():
        dates = {g[5] for g in gs if g[5]}
        teams = {g[7] for g in gs} | {g[8] for g in gs}
        if len(dates) < 2 or len(teams) < min_teams:
            continue
        fams = {}
        for g in gs:
            if is_champ_game(g[4]):
                fams.setdefault(champ_family(g[4]), []).append(g)
        if not fams:
            continue
        for fam, fg in fams.items():
            fg.sort(key=lambda g: (g[5], _time_key(g[6])))
            last = fg[-1]
            hw, aw = last[9], last[10]
            if hw == 1 and aw == 1:
                continue  # corrupt flags; skip
            if hw == 1:
                champ, runner = last[7], last[8]
            elif aw == 1:
                champ, runner = last[8], last[7]
            else:
                continue  # no winner recorded
            for role, name in (("champ", champ), ("runner-up", runner)):
                row = cur.execute(
                    "SELECT team_id FROM team_names WHERE raw_name = ? "
                    "AND division_hint = ? LIMIT 1",
                    (name, div)).fetchone()
                if not row:
                    row = cur.execute(
                        "SELECT team_id FROM team_names WHERE raw_name = ? "
                        "LIMIT 1", (name,)).fetchone()
                if row:
                    is_home = (name == last[7])
                    slug = last[11] if is_home else last[12]
                    dt = last[13] if is_home else last[14]
                    titles.setdefault(row[0], []).append({
                        "tid": tid, "div": div, "role": role,
                        "prestige": tid in prestige,
                        "date": last[5],
                        "slug": slug, "dt": dt,
                    })
    return titles


def games_for_team(cur, team_id, region_cities, gender_filter):
    """Return list of (date_iso, won_bool, weight, band, tid, div, self,
    opp, pf, pa, game_type). game_type is None for BT games (no bracket
    labels there). EE game_type marks pool vs championship-bracket play."""
    names = cur.execute(
        "SELECT raw_name, division_hint FROM team_names WHERE team_id = ?",
        (team_id,)).fetchall()
    if not names:
        return []
    out = []
    for raw, div in names:
        if gender_filter == "boys" and ("girl" in (div or "").lower()
                                        or "\u2640" in (div or "")):
            continue
        if gender_filter == "girls" and not ("girl" in (div or "").lower()
                                             or "\u2640" in (div or "")):
            continue
        band, weight = tier_of(div)
        for tbl in ("ee_games", "bt_games", "fb_games"):
            if tbl == "ee_games":
                rows = cur.execute(
                    """SELECT date, home_team, away_team, home_score, away_score,
                              home_won, away_won, status, tournament_id, division_name,
                              game_type, home_slug, away_slug,
                              home_dt_id, away_dt_id, division_id, game_id
                       FROM ee_games
                       WHERE status = 'Final'
                         AND ((home_team = ? AND division_name = ?)
                           OR (away_team = ? AND division_name = ?))""",
                    (raw, div, raw, div)).fetchall()
                for (d, ht, at, hs, aws, hw, aw, st,
                        tid, divname, gtype, hslug, aslug,
                        hdt, adt, divid, gid) in rows:
                    if hw == 1 and aw == 1:
                        continue  # corrupt flags; skip
                    is_home = (ht == raw)
                    won = bool(hw) if is_home else bool(aw)
                    try:
                        pf = int(hs) if is_home else int(aws)
                        pa = int(aws) if is_home else int(hs)
                    except (TypeError, ValueError):
                        pf = pa = None  # forfeit strings like 'F-W'
                    try:
                        m, dd, y = d.split("/")
                        iso = f"{y}-{int(m):02d}-{int(dd):02d}"
                    except Exception:
                        iso = "0000-00-00"
                    _xtra = {"source": "ee", "slug": hslug if is_home else aslug,
                             "dt": hdt if is_home else adt,
                             "divid": divid, "gid": gid}
                    # ID INVARIANT: g[4] is always str (EE tournament_id may
                    # be int or str on disk depending on scraper vintage;
                    # normalize here so every downstream comparison --
                    # prestige, circuit, gates, H2H -- is type-safe).
                    out.append((iso, won, weight, band, str(tid), divname,
                                ht if is_home else at,
                                at if is_home else ht, pf, pa, gtype,
                                _xtra))
            elif tbl == "bt_games":
                rows = cur.execute(
                    """SELECT date, home_team, away_team, home_score, away_score,
                              winner, has_result, event_id, division_name,
                              division_id, match_id
                       FROM bt_games
                       WHERE has_result = 1 AND winner IN ('H','A')
                         AND ((home_team = ? AND division_name = ?)
                           OR (away_team = ? AND division_name = ?))""",
                    (raw, div, raw, div)).fetchall()
                for (d, ht, at, hs, aws, w, hr, eid, divname,
                        divid, mid) in rows:
                    is_home = (ht == raw)
                    won = (w == "H") if is_home else (w == "A")
                    pf = hs if is_home else aws
                    pa = aws if is_home else hs
                    iso = (d or "")[:10]
                    _xtra = {"source": "bt", "divid": divid, "mid": mid}
                    out.append((iso, won, weight, band, str(eid), divname,
                                ht if is_home else at,
                                at if is_home else ht, pf, pa, None,
                                _xtra))
            if tbl == "fb_games":  # fb_games
                # date is "Sep 19" (no year) -- take the year
                # from fb_events; pool holds "Pool A"/"Bracket A".
                rows = cur.execute(
                    """SELECT g.date, g.home_team, g.away_team, g.home_score,
                              g.away_score, g.home_won, g.away_won, g.status,
                              g.event_id, g.division_name, g.pool, e.start_date
                       FROM fb_games g LEFT JOIN fb_events e
                         ON e.event_id = g.event_id
                       WHERE g.status = 'FINAL'
                         AND ((g.home_team = ? AND g.division_name = ?)
                           OR (g.away_team = ? AND g.division_name = ?))""",
                    (raw, div, raw, div)).fetchall()
                for (d, ht, at, hs, aws, hw, aw, st,
                        eid, divname, pool, sdate) in rows:
                    # Do not turn missing scores, draws, or unclear winner
                    # flags into an automatic loss.
                    if hs is None or aws is None or bool(hw) == bool(aw):
                        continue
                    is_home = (ht == raw)
                    won = bool(hw) if is_home else bool(aw)
                    pf = hs if is_home else aws
                    pa = aws if is_home else hs
                    # Full-year and legacy month/day cards both use the
                    # event's own date metadata. Never invent 2026-01-01.
                    game_date = fastbreak_date(d, sdate)
                    if game_date is None:
                        continue
                    iso = game_date.isoformat()
                    gtype = ("pool" if (pool or "").startswith("Pool")
                             else "bracket")
                    out.append((iso, won, weight, band, f"fb{eid}",
                                divname, ht if is_home else at,
                                at if is_home else ht, pf, pa, gtype,
                                {}))
    # region filter on tournament city
    if region_cities is not None:
        out = [g for g in out if region_cities.get(g[4])]
    out.sort(key=lambda g: (g[0], g[4]), reverse=True)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--level", required=True,
                    help="team level(s), e.g. 14u or '14u,8th' for the "
                         "combined 14U/8th-grade cohort (levels are disjoint "
                         "labels in the DB, so combine them explicitly)")
    ap.add_argument("--last", type=int, default=15,
                    help="games of form per team (default 15)")
    ap.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS,
                     help="hard recency floor: games older than this are out "
                          "of the window entirely, not just decayed "
                          "(default 365; 0 disables; 180 restores the former window)")
    ap.add_argument("--min-games", type=int, default=4,
                    help="minimum games to rank (default 4; shrinkage "
                         "discounts thin teams so the floor can stay low)")
    ap.add_argument("--no-circuit-tier", action="store_true",
                     help="keep division-label tiers for vetted shoe circuits instead of the default national tier")
    ap.add_argument("--region", default=None,
                    help="region center, e.g. 'Palo Alto'")
    ap.add_argument("--miles", type=float, default=50,
                    help="radius in miles (default 50)")
    ap.add_argument("--include-bare", action="store_true",
                    help="include bare-confidence program labels")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--boys-only", action="store_true")
    g.add_argument("--girls-only", action="store_true")
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--dump-games", action="store_true",
                    help="emit per-team window game logs as JSON lines "
                         "(for build_site.py) instead of the board")
    ap.add_argument("--no-decay", action="store_true",
                    help="disable recency decay (default: games older than "
                         "~90 days count half, fade to zero by ~1 year)")
    ap.add_argument("--no-sos", action="store_true",
                    help="disable opponent adjustment (pure tier-weighted form)")
    ap.add_argument("--sos-iters", type=int, default=15,
                    help="opponent-score propagation rounds (default 15)")
    ap.add_argument("--title-bonus", type=float, default=1.5, metavar="MULT",
                    help="credit multiplier for championship-bracket wins in "
                         "eligible 2-day titles (default 1.5; 0 disables). "
                         "Runner-up final counts half.")
    ap.add_argument("--min-title-teams", type=int, default=8,
                    help="min distinct teams in a (tournament, division) for "
                         "title detection (default 8)")
    ap.add_argument("--prestige-mult", type=float, default=1.25, metavar="MULT",
                    help="credit multiplier for EVERY win at a prestige event "
                         "(Made Hoops / Grassroots365 / OGP -- pool included; "
                         "default 1.25; 0 disables). Stacks with --title-bonus "
                         "on title-clinching wins.")
    ap.add_argument("--h2h-band", type=float, default=0.01, metavar="GAP",
                    help="head-to-head tiebreak: a lower team that directly "
                         "beat a higher team in-window jumps them when scores "
                         "are within GAP (default 0.01; 0 disables).")
    ap.add_argument("--no-title", action="store_true",
                    help="disable the tournament-title + prestige bonuses")
    ap.add_argument("--no-margin", action="store_true",
                    help="disable the margin-of-victory multiplier (all games 1.0x)")
    ap.add_argument("--ranked-win-top", type=int, default=10,
                    help="only top-N prelim teams confer transitive credit "
                    "(wins/losses vs #N+ earn no opp boost/consolation; "
                    "0 disables: single pass, old behavior)")
    ap.add_argument("--sos-passes", type=int, default=3,
                    help="gated refinement passes: each pass re-ranks under "
                    "the previous pass's top-N credit set, then redefines "
                    "the set (default 3; 1 = old two-pass behavior)")
    ap.add_argument("--verbose", action="store_true",
                    help="log each gated pass's credit set to stderr")
    ap.add_argument("--shrink-k", type=float, default=8.0,
                    help="sample-size prior: scores scale by n/(n+k) (default 8; 0 disables)")
    ap.add_argument("--no-tier-ceiling", action="store_true",
                    help="disable the cross-tier ceiling (default: a team "
                         "cannot outrank the next tier up without beating "
                         "someone from that tier or higher)")
    ap.add_argument("--no-winpct", action="store_true",
                    help="disable the win%% multiplier (default: final "
                         "score x (0.5 + 0.5 x win%%) so winning matters "
                         "outright)")
    ap.add_argument("--no-circuit-floor", action="store_true",
                    help="disable the circuit floor (default: a team with "
                         "a game in a vetted shoe circuit cannot rank "
                         "below the best silver-modal team)")
    ap.add_argument("--no-norcal-gate", action="store_true",
                    help="rank circuit-only (SoCal) teams too (default: excluded)")
    ap.add_argument("--active-days", type=int, default=60,
                    help="only rank teams with at least one game anywhere in "
                         "the last DAYS (default 60); older teams list as "
                         "inactive, recent-but-out-of-region teams as "
                         "active-elsewhere. 0 disables the gate.")
    args = ap.parse_args()

    from datetime import date as _date, timedelta as _td
    today = _date.today().isoformat()
    cutoff = ((_date.today() - _td(days=args.active_days)).isoformat()
              if args.active_days else "0000-00-00")

    def decay(iso):
        if args.no_decay or not iso or len(iso) < 10:
            return 1.0
        try:
            age_days = (_date.fromisoformat(today)
                        - _date.fromisoformat(iso[:10])).days
        except ValueError:
            return 1.0
        if age_days <= 90:
            return 1.0
        if age_days >= 365:
            return 0.0
        return 1.0 - 0.5 * (age_days - 90) / 275.0

    gender = ("boys" if args.boys_only else
              "girls" if args.girls_only else None)
    con = sqlite3.connect(args.db)
    cur = con.cursor()

    levels = [lv.strip().lower() for lv in args.level.split(",") if lv.strip()]
    # Levels in the DB include curated compounds (falcons-14u, mike-8th)
    # and freeform strings (stl 8th black). Match a team when ANY level
    # token equals the requested level (split compounds on - / space).
    allt = cur.execute(
        "SELECT team_id, program, level, confidence FROM teams").fetchall()

    def level_match(team_level):
        toks = _re.split(r"[- /\u2013]+", (team_level or "").lower())
        return any(t in levels for t in toks)

    teams = [(t, p, c) for t, p, lv, c in allt if level_match(lv)]
    if not args.include_bare:
        teams = [t for t in teams if not t[0].startswith("prog:")]

    region_cities = None
    if args.region:
        center = resolve_center(args.region)
        snaps = snapshot_cities()
        region_cities = {tid: True for tid, city in snaps.items()
                         if city_in_radius(city, center, args.miles)}
    # NorCal membership gate (Nov 2026): the boards rank NorCal teams.
    # The SoCal circuit scrape (Jr. EYBL / 3SSB / 3Stripes qualifiers +
    # finals, all SoCal-based) lives in the DB for opposition +
    # prestige purposes, but teams appearing ONLY there are SoCal
    # locals, not NorCal teams. Membership requires >=1 window game in
    # a NorCal-pipeline tournament. Circuit games still score for
    # everyone (prestige-weighted); NorCal teams' road games there
    # count normally. BT event_ids are ints, EE tids strings -- compare
    # as str. Circuit-only teams land in active_elsewhere (visible, not
    # ranked). --no-norcal-gate disables (old behavior: everyone ranks).
    # 275133 (Fall 2026 Season, surname house league) is excluded the
    # same way: rec-league games are not club competition at all.
    NON_NORCAL_EVENTS = {
        "273271",  # Jr. 3SSB West Open Qualifier (Anaheim, Oct 26)
        "261349",  # 2026 Jr. EYBL - West (spring)
        "257749",  # 2026 Jr. EYBL Open West S1
        "257751",  # 2026 Jr. EYBL Open West S2
        "259194",  # 3Stripes Gold West Open Qualifier (May 26)
        "250243",  # Jr. 3SSB West Open Qualifier (May 26)
        "261856",  # Earn Your Stripes West Girls
        "250228",  # Jr. 3SSB West & Mountain Super Regional
        "259196",  # 3Stripes Gold West Championships (Finals)
        "275133",  # Fall 2026 Season (surname house league, not club)
    }
    # Verified shoe-circuit events: Nike Jr. EYBL and adidas 3SSB/3Stripes.
    # Their games use the national tier below unless --no-circuit-tier is
    # set. Selection itself also carries a separate circuit floor when an
    # eligible silver-modal score exists. This is a uniform event-level rule,
    # not a team-specific score adjustment.
    CIRCUIT_EVENTS = (NON_NORCAL_EVENTS - {"275133"}) | {
        "273271",  # Jr. 3SSB West Open Qualifier (Anaheim, Oct 3-4 2026)
        "250214",  # Jr. 3SSB West Tip-Off (Oct 2025)
        "238739",  # 3Stripes Gold Earn Your Stripes / Encore
        "238740",  # 3Stripes Gold West Championship / Final Act
        "259191",  # 3Stripes Gold West Sessions I & II (2026)
        # NOT circuit: Made Hoops events (264028 Norcal Clash, 264307
        # West Live Finale) are open-registration big tournaments, not
        # vetted selection -- prestige multiplier only. 278985 ABCD
        # camp has no bracket games (skipped per policy).
    }
    ranked, thin = [], []
    team_games = {}
    inactive = []       # no game anywhere in the last --active-days
    active_elsewhere = []  # played recently, but nothing in-region
    for team_id, program, conf in teams:
        games = games_for_team(cur, team_id, region_cities, gender)
        if args.window_days:
            # Hard recency floor (user-confirmed Nov 2026): games older
            # than --window-days are OUT, not just decayed. Spring ball
            # with a different roster must not prop up (or drag down)
            # fall rankings. Applied BEFORE the --last slice so the
            # window is "last N games of this season", and shrink prices
            # the missing volume honestly.
            floor = (_date.fromisoformat(today)
                     - _td(days=args.window_days)).isoformat()
            games = [g for g in games if g[0] >= floor]
        games = games[:args.last]
        if args.active_days:
            # activity is a property of the TEAM: check the unfiltered
            # latest game, not the regional slice (a team active in
            # Rocklin but idle near Palo Alto is active, just unsampled).
            allg = games_for_team(cur, team_id, None, gender)
            latest_any = allg[0][0] if allg else ""
            if not allg or latest_any < cutoff:
                inactive.append((team_id, len(allg),
                                 latest_any or "never"))
                continue
        if not args.no_norcal_gate and not any(
                str(g[4]) not in NON_NORCAL_EVENTS for g in games):
            # circuit-only team: visible in active_elsewhere, not ranked
            if games:
                active_elsewhere.append((team_id, len(games),
                                         games[0][0] + " (circuit-only)"))
            continue
        if len(games) < args.min_games:
            if args.active_days:
                active_elsewhere.append((team_id, len(games),
                                         games[0][0] if games
                                         else allg[0][0] + " (out-of-region)"))
            elif games:
                thin.append((team_id, len(games)))
            continue
        if not args.no_circuit_tier:
            games = apply_circuit_tier(games, CIRCUIT_EVENTS)
        team_games[team_id] = games

    # Championship + prestige multipliers ("big-event wins count more").
    # Two stacked layers, both flowing through seed and iteration:
    #   title: champ-bracket wins in a won 2-day event earn --title-bonus x
    #     (runner-up final loss at half). Needs --min-title-teams teams.
    #   prestige: EVERY win at a Made Hoops / Grassroots365 / OGP event
    #     earns --prestige-mult x (default 1.25) -- pool play included.
    #     Title-clinching wins in prestige events stack both (TB x PM).
    use_title = not args.no_title and args.title_bonus and args.title_bonus > 0
    use_prestige = not args.no_title and args.prestige_mult and args.prestige_mult > 0
    title_map = {}   # team_id -> list of title dicts
    title_mult = {}  # team_id -> per-game multipliers, aligned w/ games
    if use_title or use_prestige:
        if use_title:
            title_map = title_events(cur, min_teams=args.min_title_teams)
        prestige_ee, prestige_bt = prestige_events(cur) if use_prestige else (set(), set())
        TB = args.title_bonus
        PM = args.prestige_mult
        for tid, games in team_games.items():
            mults = []
            my = title_map.get(tid, [])
            for g in games:
                m = 1.0
                gtype = g[10] if len(g) > 10 else None
                # layer 1: prestige -- any win in a big event (EE + BT).
                # g[4], prestige_ee, prestige_bt are all str (see the
                # ID INVARIANT at games_for_team and prestige_events).
                if g[1] and use_prestige:
                    if g[4] in prestige_ee or g[4] in prestige_bt:
                        m *= PM
                # layer 2: title -- champ-bracket wins that closed a title.
                # Boost pays only at gold and above (national/up/gold):
                # winning a silver/bronze/open bracket still earns the
                # badge but no score multiplier (user-confirmed Nov 2026:
                # Bay City 8th Black rode a silver title to #22).
                if gtype and is_champ_game(gtype) and use_title:
                    for x in my:
                        if x["tid"] == str(g[4]) and x["div"] == g[5]:
                            band = g[3].split(":")[0]
                            if band not in ("national", "up", "gold"):
                                break
                            t = TB
                            if x["role"] == "runner-up" and not g[1]:
                                # final loss: consolation at half bonus
                                t = 1.0 + (TB - 1.0) / 2.0
                            elif x["role"] == "runner-up" and g[1]:
                                # earlier champ win that didn't close it
                                t = TB
                            m *= t
                            break
                mults.append(m)
            title_mult[tid] = mults

    # Head-to-head aware scoring (transitive strength with bite). Each
    # game is worth credit scaled by the OPPONENT's strength, so beating
    # a strong team moves the needle and losing to a weak team costs
    # more than losing to a killer:
    #   win:  w_tier x decay x margin x (0.25 + 0.75 x opp)
    #   loss: w_tier x decay x margin x 0.25 x opp   (consolation: good losses count)
    # Sample-size shrinkage (regress thin teams to replacement level).
    # A 5-game hot streak is less trustworthy than a 15-game season, so
    # published scores scale by n/(n+k) where n = games in the window
    # and k = --shrink-k (default 8: a 5-game team keeps 38%, 8 games
    # keeps 50%, a full 15-game window keeps 65%). Applied to ranked
    # finals AND to need-opponent seeds (small-sample opponents must
    # not inflate anyone through the 0.75 term). Big-sample teams are
    # barely touched; the league scale is preserved. This is the
    # accomplishment principle: short efficiency streaks must be
    # sustained to hold rank. Disable with --shrink-k 0.
    # Margin curve (symmetric, log with cap): close games ~0.85x at 1pt,
    # 1.0x at ~12pts (median), ~1.15x at 20, caps ~1.3x at 25+. Applied
    # to wins AND losses (close loss keeps consolation; blowout earns
    # almost none). Missing scores (forfeits) get a neutral 1.0x.
    # DO NOT hand-tune these constants for one board -- they set the
    # league-wide meaning of "dominance" and must stay global.
    # Scores iterate (15 rounds): your wins appreciate as your beaten
    # opponents prove strong. Round 0 (seed) = plain tier-weighted form.
    WIN_BASE, WIN_OPP, LOSS_OPP, LOSS_OPP_UP = 0.25, 0.75, 0.25, 0.50
    # LOSS_OPP_UP (user-confirmed Nov 2026): a loss to a HIGHER band
    # keeps 0.5x opp instead of 0.25x. Stepping up and losing close
    # (Falcons gold 0-2: 33-35, 27-40) must cost less than ducking
    # down -- the tier weight already taxes the game, the modal
    # winpct already ignores it. Same-band and step-down losses stay
    # at 0.25x. Band comparison uses the modal bands computed for
    # the ceiling (same definition, same open==silver peer rule).
    SHRINK_K = args.shrink_k
    MARGIN_REF, MARGIN_CAP, MARGIN_LOSS_FLOOR = 12.0, 25.0, 0.2
    BAND_WEIGHT = {"national": 1.0, "up": 0.85, "gold": 0.75,
                   "open": 0.5, "silver": 0.5, "bronze": 0.25}
    BOARD_ORDER = ["national", "up", "gold", "open", "silver",
                   "bronze", "mixed"]
    def resolve_opp(opp_name, divname, tid):
        row = cur.execute(
            "SELECT team_id FROM team_names WHERE raw_name = ? "
            "AND division_hint = ? LIMIT 1", (opp_name, divname)).fetchone()
        if row:
            return row[0]
        row = cur.execute(
            "SELECT team_id FROM team_names WHERE raw_name = ? LIMIT 1",
            (opp_name,)).fetchone()
        return row[0] if row else None

    def margin_mult(game, ghost_opp=False):
        """Log-curve margin multiplier, symmetric for wins and losses.
        dev = ln((1+margin)/(1+REF)), margin capped at MARGIN_CAP:
          win:  1 + 0.3*dev, floored at 0.85 -> squeaker ~0.85x, 12pts
                1.0x (median game), 20pts ~1.15x, 25pts ~1.21x (cap).
          loss: 1 - 1.15*dev, capped at 1.0, floored at 0.2 -> loss by
                <=10pts keeps full consolation, 15pts ~0.76x, 20pts
                ~0.45x, 25pts blowout ~0.2x.
        Games with no numeric scores (forfeits like 'F-W') get 1.0x.
        ghost_opp (user-confirmed Nov 2026): wins over ghosts
        (unresolvable / <9g opponents) cap at 1.0x -- beating an unknown
        by 25 proves nothing beyond the win itself (JavStep White /
        Bay City pattern). Losses keep full consolation either way.
        """
        import math as _m
        if args.no_margin:
            return 1.0
        pf, pa = game[8], game[9]
        try:
            diff = (int(pf) - int(pa)) if game[1] else (int(pa) - int(pf))
        except (TypeError, ValueError):
            return 1.0
        if diff < 0:
            diff = 0  # winner flag disagrees with score; treat as squeaker
        capped = min(diff, MARGIN_CAP)
        dev = _m.log((1.0 + capped) / (1.0 + MARGIN_REF))
        if game[1]:
            m = max(0.85, 1.0 + 0.3 * dev)
            # ghost wins floor at 0.85x instead of capping at 1.0x:
            # squeakers over unknowns pay median, blowouts pay less
            # than squeakers over real teams (Nov 2026).
            return 0.85 if ghost_opp else m
        return max(MARGIN_LOSS_FLOOR, min(1.0, 1.0 - 1.15 * dev))

    _ghost_cache = {}

    def is_ghost(oid):
        """Unproven opponent: unresolvable names and thin teams (<9
        games, any level). Bare program labels (prog:, tm:falcons,
        tm:griffins) with 9+ games are real form -- keep them. Ghosts
        resolve to None in opp_ids so they contribute no opponent
        strength (their blurry ~zero seeds must not launder credit
        through the 0.75 term). Ranked teams are never ghosts.
        """
        if oid is None:
            return True
        if oid in team_games:
            return False
        if oid in _ghost_cache:
            return _ghost_cache[oid]
        try:
            n = len(games_for_team(cur, oid, None, gender))
        except Exception:
            n = 0
        res = n < 9
        _ghost_cache[oid] = res
        return res

    def seed_of(games, mults=None, ghosts=None):
        # Round-0 form: tier x decay x margin (x title) per win. Ghost
        # wins cap margin at 1.0x (margin_mult ghost flag) -- running up
        # the score on unknowns proves nothing; opponent strength is
        # priced in the iteration, not the seed. (Ghosts resolve to
        # None in opp_ids, so they contribute no opp score there.)
        if not games:
            return 0.0
        if mults is None:
            mults = [1.0] * len(games)
        if ghosts is None:
            ghosts = [False] * len(games)
        tot = 0.0
        for g, m, gh in zip(games, mults, ghosts):
            if not g[1]:
                continue
            # ghost wins halve the seed base too (same Nov 2026 fix);
            # non-ghosts keep the unscaled seed (no WIN_BASE there).
            _wb = 0.5 if gh else 1.0
            tot += g[2] * decay(g[0]) * m * margin_mult(g, gh) * _wb
        return tot / len(games)

    opp_ids = {}  # team_id -> list of (opp_team_id or None) per game
    need = set()
    # Modal bands (shared by the step-up loss rule + the ceiling):
    # most common band in-window per team; open==silver peers;
    # up counts as national; mixed bands take the best component.
    CEIL_ORD = ["bronze", "silver", "gold", "national"]
    CEIL_EQ = {"open": "silver", "up": "national"}
    def _flat(b):
        b = b.split(":")[-1] if b.startswith("mix:") else b
        return CEIL_EQ.get(b, b)
    modal = {}
    for tid, games in team_games.items():
        bands = Counter(g[3].split(":")[0] for g in games)
        modal[tid] = max(bands, key=lambda b: (bands[b], BAND_ORDER.index(b) if b in BAND_ORDER else 99))
    for tid, games in team_games.items():
        ids = []
        for g in games:
            oid = resolve_opp(g[7], g[5], g[4])
            if is_ghost(oid):
                oid = None
            ids.append(oid)
            if oid is not None and oid not in team_games:
                need.add(oid)
        opp_ids[tid] = ids
    seed = {tid: seed_of(g, title_mult.get(tid),
                         [o is None for o in opp_ids[tid]])
            for tid, g in team_games.items()}
    def shrink(n):
        return n / (n + SHRINK_K) if SHRINK_K > 0 else 1.0

    # score opponents outside the ranked set (their games unfiltered)
    for oid in need:
        og = games_for_team(cur, oid, None, gender)[:args.last]
        if not args.no_circuit_tier:
            og = apply_circuit_tier(og, CIRCUIT_EVENTS)
        seed.setdefault(oid, seed_of(og, [1.0] * len(og)) * shrink(len(og)))
        # NB: outside-ranked opponents get title_mult=1 (their titles are
        # out-of-scope) but DO get margin_mult via seed_of.

    # Ranked-win gate: only genuinely good opponents confer transitive
    # credit. Pass 1 runs the full pipeline with every ranked opponent
    # counting; the top-N prelim teams (default 10) become the credit
    # set. Pass 2 re-runs the iteration with opp scores reading 0.0 for
    # everyone outside that set -- beating #13 pays the 0.25 floor (you
    # won your scheduled game) but no transitive boost. Beating #1 pays
    # both. The gate kills closed loops where mediocre teams rank each
    # other (Cali Gold <-> NorCal United North). Losses work the same
    # way: only losing to the top-N earns consolation; losing to #13+
    # costs full. Display (vs column), the H2H tiebreak, and titles are
    # ungated -- a direct win is still shown and still flips within its
    # +-2 band. --ranked-win-top 0 disables (single pass, old behavior).
    def run_board(credit):
        """credit: None = every ranked opp score counts (pass 1);
        otherwise only team_ids in the set read nonzero (pass 2)."""
        if args.no_sos:
            return ({tid: seed[tid] for tid in team_games},
                    {tid: 0.0 for tid in team_games})
        _score = dict(seed)
        for _ in range(max(0, args.sos_iters)):
            nxt = {}
            for tid, games in team_games.items():
                tot = 0.0
                mults = title_mult.get(tid, [1.0] * len(games))
                for g, o, m in zip(games, opp_ids[tid], mults):
                    if credit is None:
                        opp = _score.get(o, seed.get(o, 0.0))
                    else:
                        opp = _score.get(o, 0.0) if o in credit else 0.0
                    base = (g[2] * decay(g[0]) * m
                            * margin_mult(g, o is None))
                    if g[1]:
                        # Ghost wins (unresolvable / <9g opponents) prove
                        # little: halve the base on top of the margin cap
                        # (user-confirmed Nov 2026, JavStep/Bay City
                        # pattern). Ranked wins are untouched.
                        _wb = WIN_BASE * (0.5 if o is None else 1.0)
                        tot += base * (_wb + WIN_OPP * opp)
                    elif o is not None and o in modal and tid in modal and _flat(modal[o]) in CEIL_ORD and _flat(modal[tid]) in CEIL_ORD and CEIL_ORD.index(_flat(modal[o])) > CEIL_ORD.index(_flat(modal[tid])):
                        tot += base * LOSS_OPP_UP * opp
                    else:
                        tot += base * LOSS_OPP * opp
                nxt[tid] = tot / len(games) if games else 0.0
            for oid in need:
                nxt.setdefault(oid, seed.get(oid, 0.0))
            _score = nxt
        _final = _score
        _sos = {}
        for tid in team_games:
            if credit is None:
                oscs = [_score.get(o, seed.get(o, 0.0))
                        for o in opp_ids[tid]]
            else:
                oscs = [_score.get(o, 0.0) if o in credit else 0.0
                        for o in opp_ids[tid]]
            oscs = [s for s in oscs if s is not None]
            _sos[tid] = sum(oscs) / len(oscs) if oscs else 0.0
        return _final, _sos

    final, sos_map = run_board(None)
    h2h_map = {tid: [] for tid in team_games}
    if args.ranked_win_top > 0 and not args.no_sos:
        # Multi-pass refinement (user-confirmed Nov 2026): pass-1 order
        # sets the credit set, pass 2 re-ranks under it, then the new
        # order redefines the set for pass 3. Each round re-judges
        # quality-of-wins against the revised rankings, so a team that
        # climbs on legit H2H (e.g. BMG over Cali Gold) starts conferring
        # credit itself. SOS stays ungated for display throughout.
        top = None
        for _pass in range(max(1, args.sos_passes)):
            prelim = sorted(
                team_games,
                key=lambda t: final[t] * shrink(len(team_games[t])),
                reverse=True)
            new_top = set(prelim[:args.ranked_win_top])
            if _pass > 0 and new_top == top:
                if args.verbose:
                    print(f"[pass {_pass + 1}] credit set stable "
                          f"({len(top)}), converged", file=sys.stderr)
                break
            top = new_top
            if args.verbose:
                names = ", ".join(prelim[:args.ranked_win_top])
                print(f"[pass {_pass + 1}] credit set: {names}",
                      file=sys.stderr)
            # SOS stays ungated for display: it describes the schedule you
            # played, not the credit the gate allows. Only the ranking
            # scores come from the gated passes.
            final, _ = run_board(top)
        else:
            if args.verbose:
                print(f"[pass {args.sos_passes}] max passes reached, "
                      f"publishing", file=sys.stderr)

    CEIL_ON = not args.no_tier_ceiling and not args.no_sos
    CEIL_N = 0
    CEIL_INFO = {}
    if CEIL_ON:
        # Cross-tier ceiling, correct scale (user-confirmed Nov 2026):
        # a bronze team's PUBLISHED score cannot exceed the best
        # published score among silver teams that earned it cleanly
        # (no wins over gold/national themselves), and so on up the
        # ladder. Each cross-tier win buys 10% headroom. The clean set
        # is computed iteratively from the top down: national's clean
        # best is just the national max (nothing above); silver's
        # clean best excludes teams whose score exceeds the gold
        # clean best (they're inflated by beating up), etc. Compare
        # against published scores (final*shrink), write back to
        # final (divide by shrink). Modal bands come from the shared
        # computation above (same open==silver peer rule).
        base = {cid: _flat(b) for cid, b in modal.items()}
        beaten = {}
        for cid, cgames in team_games.items():
            bl = []
            for g, o in zip(cgames, opp_ids[cid]):
                if g[1] and o is not None and o in modal:
                    ob = modal[o]
                    ob = ob.split(":")[-1] if ob.startswith("mix:") else ob
                    bl.append(CEIL_EQ.get(ob, ob))
                else:
                    bl.append(None)
            beaten[cid] = bl
        pub = {t: final[t] * shrink(len(team_games[t])) for t in team_games}
        clean_best = {}
        for band in reversed(CEIL_ORD):
            bi = CEIL_ORD.index(band)
            cands = []
            for t, b in base.items():
                if b != band:
                    continue
                # clean: no win over a HIGHER tier, and (if a higher
                # tier's clean best is known) not already above it
                # without cross-tier wins of its own
                if any(x is not None and x in CEIL_ORD and CEIL_ORD.index(x) > bi for x in beaten[t]):
                    continue
                cands.append(pub[t])
            clean_best[band] = max(cands) if cands else 0.0
        for cid in team_games:
            if base[cid] not in CEIL_ORD:
                continue
            mi = CEIL_ORD.index(base[cid])
            if mi >= len(CEIL_ORD) - 1:
                continue
            ni = mi + 1
            xw = sum(1 for x in beaten[cid] if x is not None and x in CEIL_ORD and CEIL_ORD.index(x) >= ni)
            cap = clean_best.get(CEIL_ORD[ni], 0.0) * 0.99 * (1.10 ** xw)
            if cap > 0 and pub[cid] > cap:
                _sh = shrink(len(team_games[cid]))
                final[cid] = cap / _sh if _sh else cap
                pub[cid] = cap
                CEIL_N += 1
                CEIL_INFO[cid] = (CEIL_ORD[ni], xw)

    for team_id, games in team_games.items():
        w = sum(1 for g in games if g[1])
        # tier-weighted seed: each win worth its tier weight (national 1.0
        # ... bronze 0.25) times a recency decay (full <90d, half by ~6mo,
        # zero by 1yr), averaged per game. A perfect Silver run maxes at
        # 0.500; plain win% is kept alongside so the adjustment is visible.
        # final score blends seed 50/50 with mean opponent score (iterated).
        # Win% multiplier (user-confirmed Nov 2026, modal-band +
        # SOS-scaled fixes): score x (0.5 + 0.5 x modal-band win% x
        # sos_scale) so winning matters outright WITHOUT
        # double-punishing step-up games AND without rewarding
        # pillow-soft schedules. A team that goes 0-2 in gold + 6-4
        # in open is judged on its 6-4 open record (x0.80), not its
        # 6-6 overall (x0.75) -- the tier weights already taxed the
        # gold losses. And 5-1 vs ghosts (sos 0.023) pays less than
        # 5-1 vs competition: sos_scale = min(1, sos/0.05), so Blue's
        # bonus halves while Falcons' (sos 0.046) stays nearly full.
        # Modal band = most common band in-window (same definition
        # as the ceiling); open/silver peers; mix takes the best
        # component. Falls back to overall win% when the modal band
        # has <3 games. Disable with --no-winpct (keeps shrink +
        # ceiling only).
        tscore = final[team_id] * shrink(len(games))
        if not args.no_winpct:
            _bands = Counter(g[3].split(":")[0] for g in games)
            _mod = max(_bands, key=lambda b: (_bands[b], BAND_ORDER.index(b) if b in BAND_ORDER else 99))
            _mod = _mod.split(":")[-1] if _mod.startswith("mix:") else _mod
            _inband = [g for g in games if (g[3].split(":")[-1] if g[3].startswith("mix:") else g[3]) == _mod or ({"open": "silver", "silver": "open"}.get(g[3].split(":")[-1] if g[3].startswith("mix:") else g[3], None) == _mod)]
            if len(_inband) >= 3:
                _bw = sum(1 for g in _inband if g[1])
                _wpct = _bw / len(_inband)
            else:
                _wpct = w / len(games)
            _sos_scale = min(1.0, (sos_map.get(team_id, 0.05) or 0.0) / 0.05)
            # (Nov 2026, Issue 2 follow-up): winpct benefit floors at 0.25
            # not 0.5 when SOS is barren -- 8-0 vs ghosts keeps 76% of
            # the winpct factor instead of 84%. Real schedules
            # (scale = 1.0) are untouched.
            tscore *= 0.5 + 0.5 * _wpct * (0.25 + 0.75 * _sos_scale)
        h2h = h2h_map[team_id]
        scored = [(g[8], g[9]) for g in games
                  if g[8] is not None and g[9] is not None]
        margin = ((sum(p for p, _ in scored) - sum(a for _, a in scored))
                  / len(scored)) if scored else 0.0
        bands = Counter(g[3].split(":")[0] for g in games)
        _order = {"national": 0, "up": 1, "gold": 2, "open": 3, "silver": 4,
                  "bronze": 5}
        _mixparts = sorted(bands, key=lambda b: (_order.get(b, 99), -bands[b]))
        tier_mix = ",".join(_mixparts)
        top_band = max(bands, key=lambda b: (bands[b],
                                             BAND_ORDER.index(b)
                                             if b in BAND_ORDER else 99))
        latest = games[0][0]
        stale = ""
        try:
            _age = (_date.fromisoformat(today)
                    - _date.fromisoformat(latest[:10])).days
            if _age > 120:
                stale = f" STALE({_age // 30}mo)"
        except ValueError:
            pass
        ranked.append((tscore, w / len(games), margin, len(games), w,
                       team_id, tier_mix + stale, latest, sos_map[team_id],
                       h2h, len(title_map.get(team_id, []))))
    ranked.sort(key=lambda r: (r[0], r[1], r[2], r[3]), reverse=True)

    # Circuit floor (user-confirmed Nov 2026): selection into a vetted
    # shoe circuit (Jr. EYBL / 3SSB / 3Stripes) is itself a credential --
    # a circuit team must rank above any silver team. Applied as a floor
    # on published score: the max published score among literal
    # silver-modal teams. NOTE: deliberately NOT the ceiling's
    # open==silver peer rule -- most local ball is modal-open, so the
    # peer definition would set the floor near the top of the board and
    # leapfrog gold teams the user wants to stay ahead ("almost every
    # gold team"). Runs AFTER the ceiling (membership outranks it by
    # design) and BEFORE the H2H swaps so direct results still flip
    # within the band. --no-circuit-floor disables. Records into
    # CIRCUIT_FLOOR for the Why-line annotation below.
    CIRCUIT_FLOOR = {}
    if not args.no_circuit_floor and not args.no_sos:
        _pos = {r[5]: i for i, r in enumerate(ranked)}
        _silver_max = 0.0
        for r in ranked:
            if modal.get(r[5], "open") == "silver" and r[0] > _silver_max:
                _silver_max = r[0]
        if _silver_max > 0:
            for tid, games in team_games.items():
                if any(is_circuit_event_game(g, CIRCUIT_EVENTS) for g in games):
                    i = _pos.get(tid)
                    if i is not None and ranked[i][0] < _silver_max:
                        old = ranked[i][0]
                        ranked[i] = (_silver_max,) + ranked[i][1:]
                        CIRCUIT_FLOOR[tid] = (old, _silver_max)
            ranked.sort(key=lambda r: (r[0], r[1], r[2], r[3]), reverse=True)

    # Head-to-head tiebreak (CFP-style): if a lower team directly beat a
    # higher team in-window and their scores are within --h2h-band, the
    # two exchange places. Pairwise on final scores; nobody else moves.
    H2H = args.h2h_band
    h2h_swaps = []
    if H2H and H2H > 0:
        # winner -> set of losers (ranked teams only, in-window games).
        # ONLY same-level games count: curated ids sweep multiple ages
        # (e.g. a 10U or 15U game on a 14U team's record), and a result
        # at another level must not flip this ranking. The game's
        # division string must mention one of the ranked levels.
        _lvl_res = [_re.compile(_re.escape(lv.strip()), _re.I)
                    for lv in args.level.split(",") if lv.strip()]

        def _same_level(div):
            d = div or ""
            return any(rx.search(d) for rx in _lvl_res)
        # h2h evidence must be fresh: same active window as the board
        from datetime import date as _d2, timedelta as _td2
        _cut = ((_d2.today() - _td2(days=args.active_days)).isoformat()
                if args.active_days else "0000-00-00")
        _beat = defaultdict(set)
        for tid, games in team_games.items():
            for g, o in zip(games, opp_ids[tid]):
                if (g[1] and o is not None and o in team_games
                        and o != tid and _same_level(g[5])
                        and (g[0] or "") >= _cut):
                    _beat[tid].add(o)
        # cap swap distance: winner exchanges places with the loser at
        # most 2 spots away, so a single result can't reorder a queue
        # of teams never faced. Swap (not jump): nobody else moves.
        _MAX_JUMP = 2
        order = list(range(len(ranked)))
        # pos: team_id -> current position in order
        for _ in range(2):  # two passes settle cascades (A>B>C)
            pos = {ranked[order[k]][5]: k for k in range(len(order))}
            moved = False
            for tid, losers in _beat.items():
                if tid not in pos:
                    continue
                for los in losers:
                    if los not in pos:
                        continue
                    pi, pj = pos[tid], pos[los]
                    if (pi > pj and pi - pj <= _MAX_JUMP
                            and abs(ranked[order[pi]][0]
                                    - ranked[order[pj]][0]) <= H2H):
                        # winner below loser, within band and reach:
                        # exchange places; everyone else holds still
                        order[pi], order[pj] = order[pj], order[pi]
                        pos = {ranked[order[k]][5]: k
                               for k in range(len(order))}
                        moved = True
                        h2h_swaps.append((tid, los))
            if not moved:
                break
        ranked = [ranked[i] for i in order]
    else:
        h2h_swaps = []

    # post-swap ranks for the vs column (reflect the flips above)
    rank_of = {r[5]: i + 1 for i, r in enumerate(ranked)}

    def opp_short(oid, g):
        # keep parentheticals: "Vipers (Onia)" != "Vipers 14U"
        base = g[7][:30] if len(g[7]) <= 30 else g[7][:27] + "..."
        if oid is not None and oid in team_games:
            return f"#{rank_of.get(oid, '?')}{base}"
        ng = len(games_for_team(cur, oid, region_cities, gender)) \
            if oid else 0
        return f"{base} (unranked,{ng}g)" if oid else f"{base} (?)"
    for idx, r in enumerate(ranked):
        # head-to-head notes: direct results, ranked opps first,
        # wins before losses within each group
        notes = []
        for g, o in zip(team_games[r[5]], opp_ids[r[5]]):
            arrow = "beat" if g[1] else "lost to"
            ranked_opp = o is not None and o in team_games
            notes.append((not ranked_opp, g[1], g[0],
                          f"{arrow} {opp_short(o, g)} {g[0]}"))
        notes.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        ranked_n = [n for rr, _, _, n in notes if not rr][:2]
        unranked_n = [n for rr, _, _, n in notes if rr][:2]
        h2h_map[r[5]] = ranked_n + unranked_n
    ranked = [r[:9] + (h2h_map[r[5]], r[10]) for r in ranked]

    # Data-backed per-team Why: 5 legit bullets each, ranked by how much
    # it explains the team's position (most decisive first). Every bullet
    # reads computed window values only -- no curated text, so nothing
    # goes stale and no team ever falls back to filler.
    def _mdy(iso):
        try:
            y, m, d = iso[:10].split("-")
            return f"{int(m)}/{int(d)}"
        except Exception:
            return iso[:10]

    def _opp_disp(oid, g):
        base = g[7][:26] if len(g[7]) <= 26 else g[7][:23] + "..."
        if oid is not None and oid in team_games:
            return f"#{rank_of.get(oid, '?')} {base}"
        try:
            ng = len(games_for_team(cur, oid, None, gender)) if oid else 0
        except Exception:
            ng = 0
        if oid and not oid.startswith("prog:") and ng >= 9:
            return f"{base} ({ng}g)"
        if oid and ng:
            return f"{base} (ghost,{ng}g)"
        return f"{base} (?)"

    def _pdiff(g):
        try:
            return (int(g[8]) - int(g[9])) if g[1] else (int(g[9]) - int(g[8]))
        except (TypeError, ValueError):
            return None

    def why_bullets(tid, games, oids):
        scored = [(g, o) for g, o in zip(games, oids)]
        w = sum(1 for g, _ in scored if g[1])
        n = len(scored)
        bands = Counter(g[3].split(":")[0] for g in games)
        _mod = max(bands, key=lambda b: (bands[b],
                                         BAND_ORDER.index(b)
                                         if b in BAND_ORDER else 99))
        _mod = _mod.split(":")[-1] if _mod.startswith("mix:") else _mod
        peer = {"open": "silver", "silver": "open"}.get(_mod)
        inb = [g for g in games
               if (g[3].split(":")[-1] if g[3].startswith("mix:")
                   else g[3]) in (_mod, peer)]
        if len(inb) >= 3:
            bw = sum(1 for g in inb if g[1])
            wline = f"{bw}-{len(inb) - bw} in-band ({_mod}, {w}-{n - w} overall)"
        else:
            wline = f"{w}-{n - w} overall"
        lines = [f"Form {wline}; {shrink(n):.0%} sample kept ({n}g)"]
        # best win: highest final opp score among ranked wins (gated
        # credit set), fall back to any in-window win
        bw_best, bw_any = None, None
        for g, o in scored:
            if not g[1] or g[8] is None:
                continue
            try:
                d = int(g[8]) - int(g[9])
            except (TypeError, ValueError):
                continue
            if (o is not None and o in team_games and o != tid
                    and o in (top if args.ranked_win_top > 0 else team_games)):
                key = (final.get(o, 0.0), -abs(d), g[0])
                if bw_best is None or key > bw_best[0]:
                    bw_best = (key, g, o, d)
            key = (final.get(o, 0.0) if o in team_games else -1.0,
                   -abs(d), g[0])
            if bw_any is None or key > bw_any[0]:
                bw_any = (key, g, o, d)
        if bw_best is not None:
            _, g, o, d = bw_best
            lines.append(f"Best win {_opp_disp(o, g)} {g[8]}-{g[9]}"
                         f" ({_mdy(g[0])}, {g[3].split(':')[0]})")
        elif bw_any is not None:
            _, g, o, d = bw_any
            lines.append(f"Best win {_opp_disp(o, g)} {g[8]}-{g[9]}"
                         f" ({_mdy(g[0])}, {g[3].split(':')[0]})")
        else:
            # winless: closest loss stands in for a best win
            near = None
            for g, o in scored:
                d = _pdiff(g)
                if d is None or d >= 0:
                    continue
                key = (d, g[0])
                if near is None or key > near[0]:
                    near = (key, g, o, d)
            if near is not None:
                _, g, o, d = near
                lines.append(f"Winless: closest {_opp_disp(o, g)}"
                             f" {g[8]}-{g[9]} ({_mdy(g[0])})")
            else:
                # unscored (forfeits): name the toughest scheduled opponent
                tough = None
                for g, o in scored:
                    key = (final.get(o, 0.0) if o in team_games else -1.0,
                           g[0])
                    if tough is None or key > tough[0]:
                        tough = (key, g, o)
                if tough is not None:
                    _, g, o = tough
                    lines.append(f"Unscored: scheduled {_opp_disp(o, g)}"
                                 f" ({_mdy(g[0])}, {g[3].split(':')[0]})")
        # hardest test: closest loss to the strongest ranked opponent
        ht = None
        for g, o in scored:
            if g[1] or o is None or o not in team_games or o == tid:
                continue
            try:
                d = int(g[9]) - int(g[8])
            except (TypeError, ValueError):
                continue
            key = (final.get(o, 0.0), -d, g[0])
            if ht is None or key > ht[0]:
                ht = (key, g, o, d)
        if ht is not None:
            _, g, o, d = ht
            extra = " (step-up)" if CEIL_ON and _flat(modal.get(o, "?")) in CEIL_ORD and _flat(modal.get(tid, "?")) in CEIL_ORD and CEIL_ORD.index(_flat(modal[o])) > CEIL_ORD.index(_flat(modal[tid])) else ""
            lines.append(f"Hardest test lost to {_opp_disp(o, g)}"
                         f" {g[8]}-{g[9]} ({_mdy(g[0])}){extra}")
        else:
            # unbeaten: say who they handled best instead
            big = None
            for g, o in scored:
                if not g[1]:
                    continue
                d = _pdiff(g)
                if d is None:
                    continue
                key = (d, g[0])
                if big is None or key > big[0]:
                    big = (key, g, o, d)
            if big is not None:
                _, g, o, d = big
                lines.append(f"Unbeaten: biggest win {_opp_disp(o, g)}"
                             f" {g[8]}-{g[9]} ({_mdy(g[0])})")
        # schedule + margin honesty
        ghost_n = sum(1 for _, o in scored if o is None)
        ghost_txt = f", {ghost_n} ghost" if ghost_n else ", no ghosts"
        lines.append(f"Schedule {bands.most_common(1)[0][0]}-leaning"
                     f" ({'/'.join(f'{b}{c}' for b, c in bands.most_common(3))})"
                     f", sos {sos_map.get(tid, 0.0):.3f}{ghost_txt}")
        # margin: biggest win + closest loss, or spread note
        diffs = [(g, _pdiff(g)) for g, _ in scored]
        diffs = [(g, d) for g, d in diffs if d is not None]
        if diffs:
            wins = sorted([d for g, d in diffs if g[1]], reverse=True)
            loss = sorted([d for g, d in diffs if not g[1]])
            parts = []
            if wins:
                parts.append(f"biggest +{wins[0]}")
            if loss:
                parts.append(f"closest -{loss[0]}")
            if parts:
                lines.append(f"Margin {' / '.join(parts)} (window"
                             f" {margin_of(tid, games):+.1f})")
        # titles / ceiling / staleness / h2h swap participation
        tails = []
        for x in title_map.get(tid, []):
            tails.append(f"{x['role']} {x['div']}"
                         f" ({x['date'][5:] if len(x['date']) > 7 else x['date']})")
            break
        if tid in CEIL_INFO:
            tails.append(f"capped at {_flat(CEIL_INFO[tid][0])}"
                         f" clean-best ({CEIL_INFO[tid][1]:.3f})")
        if tid in CIRCUIT_FLOOR:
            tails.append(f"circuit floor {CIRCUIT_FLOOR[tid][0]:.3f}"
                         f"→{CIRCUIT_FLOOR[tid][1]:.3f}")
        try:
            _age = (_date.fromisoformat(today)
                    - _date.fromisoformat(games[0][0][:10])).days
            if _age > 21:
                tails.append(f"latest {_mdy(games[0][0])} ({_age}d ago)")
            else:
                tails.append(f"fresh {_mdy(games[0][0])}")
        except ValueError:
            tails.append(f"latest {games[0][0][:10]}")
        for a, b in h2h_swaps:
            if tid in (a, b):
                tails.append(f"h2h swap vs {b if tid == a else a}")
                break
        lines.append("; ".join(tails) if tails else
                     f"Latest {_mdy(games[0][0])}")
        return lines[:6]

    def margin_of(tid, games):
        sc = [(g[8], g[9]) for g in games
              if g[8] is not None and g[9] is not None]
        if not sc:
            return 0.0
        return ((sum(p for p, _ in sc) - sum(a for _, a in sc)) / len(sc))

    why_map = {}
    for _r in ranked:
        _tid = _r[5]
        why_map[_tid] = why_bullets(_tid, team_games[_tid], opp_ids[_tid])
    h2h_map = {tid: [] for tid in team_games}

    scope = f"level={args.level} last={args.last}"
    if args.region:
        scope += f" within {args.miles:g}mi of {args.region} (by tournament city)"
    n_titled = sum(1 for t in team_games if title_map.get(t))
    print(f"# ranking: {scope}  (min {args.min_games} games)")
    print(f"# score = per-game credit x opponent strength "
          f"(win: tier x decay x margin x title x prestige x (0.25 + 0.75xopp); "
          f"loss: tier x decay x margin x title x 0.25xopp), "
          f"{args.sos_iters} iters; tier weights nat 1.0 / up .85 / gold .75 / "
          f"open .5 / silver .5 / bronze .25; decay full <90d -> 0 at 1yr; "
          f"margin {'off' if args.no_margin else 'log-cap25 (squeaker ~0.85x, median ~1.0x, 20pts ~1.15x, close loss keeps consolation)'}; "
          f"ghosts (<9g) contribute no opp strength; "
          f"ranked-win credit top-{args.ranked_win_top if args.ranked_win_top else 'off'}; "
          f"tier-ceiling {'off' if args.no_tier_ceiling else f'on ({CEIL_N} capped)'}; "
          f"shrink-k {args.shrink_k} (5g keeps {5/(5+args.shrink_k) if args.shrink_k else 1:.0%}, 15g keeps {15/(15+args.shrink_k) if args.shrink_k else 1:.0%}); "
          f"title x{args.title_bonus if use_title else 0} on champ-bracket wins "
          f"(runner-up final at half) + prestige x{args.prestige_mult if use_prestige else 0} "
          f"on EVERY win at Made Hoops/G365/OGP events; "
          f"{n_titled} ranked teams hold titles; "
          f"h2h tiebreak ±{args.h2h_band if H2H else 0} "
          f"({len(h2h_swaps)} flips: "
          f"{', '.join(f'{a}>={b}' for a, b in h2h_swaps[:8]) or 'none'})")
    print(f"# {len(ranked)} ranked, {len(thin)} below min-games, "
          f"{len(inactive)} inactive (no game anywhere in last "
          f"{args.active_days}d), {len(active_elsewhere)} active elsewhere "
          f"(recent games, none in-region) "
          f"{'(+ bare excluded)' if not args.include_bare else '(bare included)'}")
    print()
    if args.dump_games:
        # Machine-readable export for build_site.py team detail views:
        # full window game log per ranked team (date, W/L, score, teams,
        # division, band, event name). One JSON object per line.
        _ee = {}
        try:
            _ee = {t[0]: (t[1], t[2]) for t in
                   cur.execute("SELECT tournament_id, slug, title "
                               "FROM ee_tournaments")}
        except Exception:
            pass
        _bt = {}
        try:
            _bt = {str(t[0]): t[1] for t in
                   cur.execute("SELECT event_id, name FROM bt_events")}
        except Exception:
            pass
        _fb = {}
        try:
            _fb = {str(t[0]): (t[1], t[2]) for t in
                   cur.execute("SELECT event_id, slug, title FROM fb_events")}
        except Exception:
            pass

        def _ev(tid, g=None):
            """(event name, event page url) for an ee/bt/fb tournament id.

            Link depth: EE per-team page (slug + divisionteamid) when the
            game row carries them, else the EE schedule; BT per-division
            schedule (division_id); FB event page (no deeper link exists).
            g is the games_for_team tuple; g[11] holds the link payload.
            """
            s = str(tid)
            x = g[11] if (g is not None and len(g) > 11
                          and isinstance(g[11], dict)) else {}
            if s.startswith("fb"):
                slug, title = _fb.get(s[2:], ("", s))
                url = (f"https://events.fastbreakcompete.ai/event/"
                       f"{s[2:]}-{slug}") if slug != s[2:] else ""
                return (title, url)
            if s in _bt:
                divid = x.get("divid")
                url = (f"https://bracketteam.com/event/{s}/schedules/"
                       f"schedule?division_id={divid}"
                       if divid else f"https://bracketteam.com/event/{s}")
                return (_bt[s], url)
            slug, title = _ee.get(s, ("", s))
            base = (f"https://basketball.exposureevents.com/{s}/{slug}"
                    if slug != s else "")
            if base and x.get("slug") and x.get("dt"):
                url = (f"{base}/teams/{x['slug']}"
                       f"?divisionteamid={x['dt']}")
            elif base:
                url = f"{base}/schedule"
            else:
                url = ""
            return (title, url)

        import json as _json
        _ranked_ids = {r[5] for r in ranked}
        _dump_ids = [r[5] for r in ranked]
        # every other level team with >=1 scored game gets a page too
        # (rank 0 = unranked: inactive/thin/circuit-only/active-elsewhere).
        # games_for_team(tid, None, gender) ignores region so logs are
        # complete; gender still applies (boys board -> boys games).
        for t, _p, _c in teams:
            if t in _ranked_ids or t.startswith("prog:"):
                continue
            if games_for_team(cur, t, None, gender):
                _dump_ids.append(t)
        for i, tid in enumerate(_dump_ids, 1):
            rank = i if tid in _ranked_ids else 0
            # full record: every scored game in the DB, newest first
            # (window slice team_games[tid] is what the score used)
            full = games_for_team(cur, tid, None, gender)
            # Don't show a generic open band in the detail log when the
            # scoring engine used the verified circuit's national tier.
            if not args.no_circuit_tier:
                full = apply_circuit_tier(full, CIRCUIT_EVENTS)
            log = []
            for g in full:
                try:
                    pf = int(g[8]); pa = int(g[9])
                    score = f"{pf}-{pa}"
                except (TypeError, ValueError):
                    score = "W-F" if g[1] else "F-L"
                _ename, _eurl = _ev(g[4], g)
                _oppid = resolve_opp(g[7], g[5], g[4])
                log.append({"d": g[0][:10], "w": bool(g[1]),
                            "score": score, "self": g[6], "opp": g[7],
                            "opp_id": _oppid,
                            "div": g[5], "band": g[3].split(":")[0],
                            "event": _ename, "event_url": _eurl})
            print(_json.dumps({"rank": rank, "team": tid, "games": log}))
        return
    print("| # | team_id | score | W-L (last N) | tier | sos | vs ranked | avg margin | latest | why |")
    print("|---|---------|-------|--------------|------|-----|-----------|------------|--------|-----|")
    for i, r in enumerate(ranked, 1):
        (tscore, pct, margin, n, w, tid, band, latest, sos, h2h, nt) = r
        vh = ("; ".join(h2h)) if h2h else "-"
        mark = " 🏆" * min(nt, 2) if nt else ""
        why = " // ".join(why_map.get(tid, ["-"]))
        print(f"| {i} | {tid}{mark} | {tscore:.3f} | {w}-{n - w} (last {n}) | "
              f"{band} | {sos:.3f} | {vh} | {margin:+.1f} | {latest} | {why} |")
    if any(title_map.get(t) for t in team_games):
        try:
            _tmap = {t[0]: (t[1], t[2]) for t in
                     cur.execute("SELECT tournament_id, slug, title "
                                 "FROM ee_tournaments")}
        except Exception:
            _tmap = {}
        print()
        print("# titles held by ranked teams (★ prestige: Made Hoops/G365/OGP):")
        seen = set()
        for i, r in enumerate(ranked, 1):
            for x in title_map.get(r[5], []):
                key = (r[5], x["tid"], x["div"], x["role"])
                if key in seen:
                    continue
                seen.add(key)
                _slug, tname = _tmap.get(x["tid"], ("", x["tid"]))
                _turl = ""
                if _slug and x.get("slug") and x.get("dt"):
                    _turl = (f" https://basketball.exposureevents.com/"
                             f"{x['tid']}/{_slug}/teams/"
                             f"{x['slug']}?divisionteamid={x['dt']}")
                print(f"#   #{i} {r[5]}: {x['role']} {x['div']} @ "
                      f"{tname}{' ★' if x['prestige'] else ''} ({x['date']}){_turl}")
                if len(seen) >= 40:
                    break
            if len(seen) >= 40:
                break
    if active_elsewhere:
        print()
        print(f"# active in last {args.active_days}d but no games in-region "
              f"(unranked here):")
        for tid, n, latest in sorted(active_elsewhere, key=lambda x: x[2],
                                     reverse=True)[:30]:
            print(f"#   {tid}: {n} regional games, latest {latest}")
    if inactive:
        print()
        print(f"# inactive (>{args.active_days}d since last game, unranked):")
        for tid, n, latest in sorted(inactive, key=lambda x: x[2],
                                     reverse=True)[:30]:
            print(f"#   {tid}: {n} games, latest {latest}")
    if thin:
        print()
        print(f"# below min-games ({len(thin)}), unranked:")
        for tid, n in sorted(thin, key=lambda x: -x[1])[:30]:
            print(f"#   {tid}: {n} games")


if __name__ == "__main__":
    main()
