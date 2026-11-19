#!/usr/bin/env python3
"""
Load data/*.json (exposureevents) + data/bt_*.json (bracketteam) into SQLite.

Usage:
  python3 build_db.py [db_path]     # default: data/aau.db (rebuilt from scratch)

Per PRD: skips games with HideScores=true, dedups identical rows, preserves
raw team-name strings for later identity resolution. Bracketteam matches round
to winner by score (no isWinner flag); forfeits and sets stored as-is.

Schema:
  ee_tournaments(tournament_id, slug, title, scraped_at)
  ee_divisions(tournament_id, division_id, name)
  ee_games(tournament_id, game_id, date, time, game_type, division_id, division_name,
           home_team, away_team, home_score, away_score, home_won, away_won,
           status, venue, court, day_group)
  bt_events(event_id, name, start_date, end_date)
  bt_divisions(event_id, division_id, name)
  bt_teams(event_id, team_id, name, alias, main_team)
  bt_games(event_id, match_id, date, start_hour, division_id, division_name,
           pool, bracket_id, home_team, away_team, home_score, away_score,
           winner ('H'/'A'/NULL), forfeit_winner, is_exhibition, unscheduled,
           has_result, venue, court, home_team_id, away_team_id)
"""
import json, glob, sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrape_state import load as load_state
from team_identity import resolve as resolve_team, SUCCESSORS

SCHEMA = """
CREATE TABLE ee_tournaments(tournament_id TEXT PRIMARY KEY, slug TEXT, title TEXT, scraped_at TEXT);
CREATE TABLE ee_divisions(tournament_id TEXT, division_id INTEGER, name TEXT,
  PRIMARY KEY(tournament_id, division_id));
CREATE TABLE ee_games(tournament_id TEXT, game_id INTEGER, date TEXT, time TEXT,
  game_type TEXT, division_id INTEGER, division_name TEXT,
  home_team TEXT, away_team TEXT, home_score TEXT, away_score TEXT,
  home_won INTEGER, away_won INTEGER, status TEXT, venue TEXT, court TEXT, day_group TEXT,
  home_slug TEXT, away_slug TEXT, home_dt_id INTEGER, away_dt_id INTEGER,
  PRIMARY KEY(tournament_id, game_id));
CREATE TABLE bt_events(event_id INTEGER PRIMARY KEY, name TEXT, start_date TEXT, end_date TEXT,
  scraped_at TEXT);
CREATE TABLE scrape_runs(source TEXT, job TEXT, started_at TEXT, finished_at TEXT,
  status TEXT, stats TEXT, note TEXT, PRIMARY KEY(source, job));
CREATE TABLE scrape_content(source TEXT PRIMARY KEY, last_event_end TEXT, last_event_id TEXT,
  last_game_date TEXT, updated_at TEXT);
CREATE TABLE teams(team_id TEXT PRIMARY KEY, program TEXT, level TEXT,
  confidence TEXT, successor_of TEXT);
CREATE TABLE team_names(raw_name TEXT, division_hint TEXT, team_id TEXT, confidence TEXT,
  PRIMARY KEY(raw_name, division_hint));
CREATE TABLE bt_divisions(event_id INTEGER, division_id INTEGER, name TEXT,
  PRIMARY KEY(event_id, division_id));
CREATE TABLE bt_teams(event_id INTEGER, team_id INTEGER, name TEXT, alias TEXT, main_team TEXT,
  PRIMARY KEY(event_id, team_id));
CREATE TABLE bt_games(event_id INTEGER, match_id INTEGER, date TEXT, start_hour TEXT,
  division_id INTEGER, division_name TEXT, pool TEXT, bracket_id INTEGER,
  home_team TEXT, away_team TEXT, home_score INTEGER, away_score INTEGER,
  winner TEXT, forfeit_winner TEXT, is_exhibition INTEGER, unscheduled INTEGER,
  has_result INTEGER, venue TEXT, court TEXT, home_team_id INTEGER, away_team_id INTEGER,
  PRIMARY KEY(event_id, match_id));
CREATE TABLE fb_events(event_id TEXT PRIMARY KEY, slug TEXT, title TEXT,
  start_date TEXT, end_date TEXT, city TEXT, tenant INTEGER, scraped_at TEXT);
CREATE TABLE fb_divisions(event_id TEXT, division_id INTEGER, name TEXT,
  games INTEGER, scored INTEGER, PRIMARY KEY(event_id, division_id));
CREATE TABLE fb_games(event_id TEXT, game_id INTEGER, date TEXT, weekday TEXT,
  time TEXT, division_name TEXT, pool TEXT, home_team TEXT, away_team TEXT,
  home_score INTEGER, away_score INTEGER, home_won INTEGER, away_won INTEGER,
  status TEXT, venue TEXT, court TEXT,
  PRIMARY KEY(event_id, game_id));
CREATE INDEX idx_ee_team_home ON ee_games(home_team);
CREATE INDEX idx_ee_team_away ON ee_games(away_team);
CREATE INDEX idx_ee_date ON ee_games(date);
CREATE INDEX idx_bt_team_home ON bt_games(home_team);
CREATE INDEX idx_bt_team_away ON bt_games(away_team);
CREATE INDEX idx_bt_date ON bt_games(date);
CREATE INDEX idx_fb_team_home ON fb_games(home_team);
CREATE INDEX idx_fb_team_away ON fb_games(away_team);
CREATE INDEX idx_fb_date ON fb_games(date);
"""


def load_ee(cur, path):
    d = json.load(open(path))
    tid = str(d["tournament_id"])
    title = ((d.get("metadata") or {}).get("title", "").replace("&#39;", "'"))
    cur.execute("INSERT OR REPLACE INTO ee_tournaments VALUES (?,?,?,?)",
                (tid, d.get("tournament_slug"), title, d.get("scraped_at")))
    for dv in d.get("divisions", []):
        cur.execute("INSERT OR REPLACE INTO ee_divisions VALUES (?,?,?)",
                    (tid, dv["Id"], dv.get("Name")))
    n = skipped = 0
    for g in d.get("games", []):
        if g.get("HideScores"):
            skipped += 1
            continue
        cur.execute("""INSERT OR REPLACE INTO ee_games VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            tid, g.get("Id"), g.get("DateFormatted"), g.get("TimeFormatted"),
            g.get("GameTypeName"), g.get("DivisionId"),
            g.get("_division_name") or g.get("DivisionName"),
            g.get("HomeTeamName"), g.get("AwayTeamName"),
            g.get("HomeTeamScoreDisplay"), g.get("AwayTeamScoreDisplay"),
            None if g.get("HomeTeamIsWinner") is None else int(g["HomeTeamIsWinner"]),
            None if g.get("AwayTeamIsWinner") is None else int(g["AwayTeamIsWinner"]),
            g.get("Status"), g.get("Venue") or g.get("VenueName"), g.get("CourtName"),
            g.get("_day_group"),
            g.get("HomeTeamNameSlug"), g.get("AwayTeamNameSlug"),
            g.get("HomeDivisionTeamId"), g.get("AwayDivisionTeamId")))
        n += 1
    return n, skipped


def load_bt(cur, path):
    d = json.load(open(path))
    eid = int(d["event_id"])
    cur.execute("INSERT OR REPLACE INTO bt_events VALUES (?,?,?,?,?)",
                (eid, d.get("event_name"), d.get("start_date"), d.get("end_date"),
                 d.get("scraped_at")))
    for dv in d.get("divisions", []):
        cur.execute("INSERT OR REPLACE INTO bt_divisions VALUES (?,?,?)",
                    (eid, dv["id"], dv.get("division_name")))
    for tm in d.get("teams", []):
        cur.execute("INSERT OR REPLACE INTO bt_teams VALUES (?,?,?,?,?)",
                    (eid, tm["id"], tm.get("name"), tm.get("alias"), tm.get("main_team")))
    n = 0
    for m in d.get("games", []):
        hs, aws = m.get("score_home_team"), m.get("score_away_team")
        winner = None
        if isinstance(hs, int) and isinstance(aws, int) and m.get("has_result"):
            winner = "H" if hs > aws else ("A" if aws > hs else None)
        court = m.get("court") or {}
        venue = (court.get("venue") or {}).get("name")
        cur.execute("""INSERT OR REPLACE INTO bt_games VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            eid, m.get("id"), m.get("date"), m.get("start_hour"),
            m.get("_division_id"), m.get("_division_name"),
            (m.get("pool") or {}).get("pool_name"),
            m.get("bracket_id"), m.get("top"), m.get("bottom"), hs, aws,
            winner, m.get("forfeit_winner"),
            int(bool(m.get("is_exhibition") or m.get("home_exhibition") or m.get("away_exhibition"))),
            int(bool(m.get("unscheduled"))), int(bool(m.get("has_result"))),
            venue, court.get("court_name"), m.get("home_team_id"), m.get("away_team_id")))
        n += 1
    return n


def load_fb(cur, path):
    """Load a FastBreak Compete scrape (data/fb_<event_id>.json)."""
    d = json.load(open(path))
    meta = d.get("metadata", {})
    eid = str(meta.get("event_id"))
    cur.execute("INSERT OR REPLACE INTO fb_events VALUES (?,?,?,?,?,?,?,?)",
                (eid, meta.get("slug"), meta.get("title"),
                 meta.get("start_date"), meta.get("end_date"),
                 meta.get("city"), meta.get("tenant"),
                 d.get("scraped_at")))
    for dv in d.get("divisions", []):
        cur.execute("INSERT OR REPLACE INTO fb_divisions VALUES (?,?,?,?,?)",
                    (eid, dv["Id"], dv.get("Name"), dv.get("games"),
                     dv.get("scored")))
    n = 0
    for g in d.get("games", []):
        if g.get("home_score") is None and g.get("away_score") is None:
            continue
        hw = 1 if g.get("home_winner") else (0 if g.get("away_winner") else None)
        aw = 1 if g.get("away_winner") else (0 if g.get("home_winner") else None)
        cur.execute("""INSERT OR REPLACE INTO fb_games VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            eid, int(g.get("game_id") or 0), g.get("date"),
            g.get("weekday"), g.get("time"), g.get("division_name"),
            g.get("pool"), g.get("home_team"), g.get("away_team"),
            g.get("home_score"), g.get("away_score"), hw, aw,
            g.get("status"), g.get("venue"), g.get("court")))
        n += 1
    return n


def build_teams(cur):
    """Resolve every distinct (raw name, division) pair to a team_id.

    teams: one row per team_id (program + level split on last ':').
    team_names: the mapping actually used at query time.
    """
    pairs = set()
    for tbl, hcol, acol, dcol in [
            ("ee_games", "home_team", "away_team", "division_name"),
            ("bt_games", "home_team", "away_team", "division_name"),
            ("fb_games", "home_team", "away_team", "division_name")]:
        for col in (hcol, acol):
            for (name, div) in cur.execute(
                    f"SELECT DISTINCT {col}, {dcol} FROM {tbl} WHERE {col} IS NOT NULL AND {col} != ''"):
                pairs.add((name.strip(), (div or "").strip()))
    for raw, div in sorted(pairs):
        team_id, conf = resolve_team(raw, div)
        if ":" in team_id:
            program, level = team_id.rsplit(":", 1)
        else:
            program, level = team_id, ""
        succ = SUCCESSORS.get(team_id)
        cur.execute("INSERT OR IGNORE INTO teams VALUES (?,?,?,?,?)",
                    (team_id, program, level,
                     "curated" if conf == "override" else conf, succ))
        cur.execute("INSERT OR REPLACE INTO team_names VALUES (?,?,?,?)",
                    (raw, div, team_id, conf))
    return len(pairs)


def main(db_path="data/aau.db"):
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.executescript(SCHEMA)
    ee_n = ee_skip = bt_n = fb_n = 0
    ee_files = sorted(glob.glob("data/[0-9]*.json"))
    bt_files = sorted(glob.glob("data/bt_*.json"))
    fb_files = sorted(glob.glob("data/fb_*.json"))
    for f in ee_files:
        try:
            n, s = load_ee(cur, f); ee_n += n; ee_skip += s
            try:
                from scrape_state import mark_processed
                mark_processed("ee", Path(f).stem, n)
            except Exception:
                pass
        except Exception as e:
            print(f"EE FAIL {f}: {e}")
    for f in bt_files:
        try:
            bt_n += load_bt(cur, f)
            try:
                from scrape_state import mark_processed
                import re as _re
                _m = _re.match(r"bt_(.+)\.json$", Path(f).name)
                if _m:
                    mark_processed("bt", _m.group(1), None)
            except Exception:
                pass
        except Exception as e:
            print(f"BT FAIL {f}: {e}")
    for f in fb_files:
        try:
            fb_n += load_fb(cur, f)
            try:
                from scrape_state import mark_processed
                import re as _re
                _m = _re.match(r"fb_(.+)\.json$", Path(f).name)
                if _m:
                    mark_processed("fb", _m.group(1), None)
            except Exception:
                pass
        except Exception as e:
            print(f"FB FAIL {f}: {e}")
    state = load_state()
    for key, r in state.get("runs", {}).items():
        cur.execute("INSERT OR REPLACE INTO scrape_runs VALUES (?,?,?,?,?,?,?)",
                    (r.get("source"), r.get("job"), r.get("started_at"),
                     r.get("finished_at"), r.get("status"),
                     json.dumps(r.get("stats", {})), r.get("note")))
    for source, c in state.get("content", {}).items():
        cur.execute("INSERT OR REPLACE INTO scrape_content VALUES (?,?,?,?,?)",
                    (source, c.get("last_event_end"), str(c.get("last_event_id"))
                     if c.get("last_event_id") is not None else None,
                     c.get("last_game_date"), c.get("updated_at")))
    n_pairs = build_teams(cur)
    con.commit()
    print(f"teams: {n_pairs} (raw name, division) pairs resolved")
    print(f"ee: {len(ee_files)} tournaments, {ee_n} games loaded ({ee_skip} HideScores skipped)")
    print(f"bt: {len(bt_files)} events, {bt_n} games loaded")
    print(f"fb: {len(fb_files)} events, {fb_n} games loaded")
    for row in cur.execute("SELECT COUNT(DISTINCT home_team) FROM ee_games"):
        print("ee distinct home teams:", row[0])
    for row in cur.execute("SELECT COUNT(DISTINCT home_team) FROM bt_games"):
        print("bt distinct home teams:", row[0])
    for row in cur.execute("SELECT COUNT(DISTINCT home_team) FROM fb_games"):
        print("fb distinct home teams:", row[0])
    con.close()
    print(f"-> {db_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/aau.db")
