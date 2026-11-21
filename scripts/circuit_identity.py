#!/usr/bin/env python3
"""Resolve circuit team labels against existing AAU identities, conservatively."""
import csv
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from team_identity import GIRLS, age_cohort, division_age, normalize, resolve

IDENTITY_SIDES = ("canonical_team", "age_cohort", "resolution", "match_status",
                  "aau_team_url")
IDENTITY_FIELDS = [f"{side}_{field}" for side in ("home", "away")
                   for field in IDENTITY_SIDES]

def identity_parts(name, division, gender=""):
    """Resolve using supplied gender as well as the source division label."""
    identity_division = division or ""
    if (gender or "").casefold() == "girls" and not GIRLS.search(identity_division):
        identity_division = f"{identity_division} girls".strip()
    n = normalize(name)
    team_id, resolution = resolve(name, identity_division)
    # Age in the squad name is authoritative in resolve(), even when a team
    # plays up into an older division. Cohort matching must use that same age.
    age = n.get("age") or n.get("grade") or division_age(division) or ""
    return team_id, resolution, age_cohort(age), identity_division


def load_aau_entries(db_path):
    """Load aliases, age-compatible identities, and AAU appearance counts."""
    db_path = Path(db_path)
    uri = f"file:{db_path.resolve()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        entries = [{"raw_name": raw, "division_hint": division, "team_id": team,
                    "resolution": resolution}
                   for raw, division, team, resolution in con.execute(
                       "SELECT raw_name, division_hint, team_id, confidence FROM team_names")]
        appearances = Counter()
        for source in ("ee", "bt", "fb"):
            table = f"{source}_games"
            if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                               (table,)).fetchone():
                continue
            query = (f"SELECT home_team, division_name FROM {table} "
                     f"UNION ALL SELECT away_team, division_name FROM {table}")
            appearances.update(con.execute(query))
    finally:
        con.close()
    return entries, appearances


def build_indexes(entries, appearances=None):
    index = defaultdict(list)
    alias_counts = Counter()
    for stored in entries:
        team_id, resolution, cohort, _ = identity_parts(
            stored["raw_name"], stored["division_hint"])
        if cohort is None:
            continue
        entry = dict(stored, canonical_team_id=team_id, resolution=resolution)
        key = (team_id, cohort)
        index[key].append(entry)
        if appearances is not None:
            alias_counts[key] += appearances.get(
                (entry["raw_name"], entry["division_hint"]), 0)
    return index, alias_counts


def enrich_games(games, entries, page_of, appearances=None, site_root="site"):
    """Add identity fields to each side and return a row-per-variant report.

    No name-only or cross-cohort links are made. Bare/age-less identities stay
    unlinked even when they resemble a known club or another age group.
    """
    index, alias_counts = build_indexes(entries, appearances)
    cache = {}
    report_games = Counter()
    for game in games:
        for side in ("home", "away"):
            raw = game.get(f"{side}_team", "")
            division = game.get("division", "")
            gender = game.get("gender", "")
            circuit = game.get("circuit", "")
            key = (circuit, raw, division, gender)
            report_games[key] += 1
            if key not in cache:
                team_id, resolution, cohort, identity_division = identity_parts(
                    raw, division, gender)
                aliases = index.get((team_id, cohort), []) if cohort is not None else []
                if resolution == "bare":
                    status = "ambiguous"
                elif cohort is None:
                    status = "age_unknown"
                elif aliases:
                    status = "matched"
                else:
                    status = "unmatched"
                cohort_page = page_of.get(team_id)
                profile = ""
                if (status == "matched" and cohort_page
                        and age_cohort(cohort_page[0]) == cohort):
                    profile = f"teams/{cohort_page[0]}/{cohort_page[1]}"
                    if not (Path(site_root) / profile).is_file():
                        profile = ""
                cache[key] = {
                    "circuit": circuit, "raw_name": raw, "division": division,
                    "gender": gender, "canonical_team_id": team_id,
                    "age_cohort": cohort if cohort is not None else "",
                    "resolution": resolution, "match_status": status,
                    "identity_division": identity_division,
                    "aau_aliases": "; ".join(sorted({a["raw_name"] for a in aliases})),
                    "aau_divisions": "; ".join(sorted({a["division_hint"] for a in aliases})),
                    "aau_stored_ids": "; ".join(sorted({a["team_id"] for a in aliases})),
                    "aau_appearances": alias_counts.get((team_id, cohort), 0),
                    "profile_path": profile,
                }
            info = cache[key]
            game[f"{side}_canonical_team"] = info["canonical_team_id"]
            game[f"{side}_age_cohort"] = info["age_cohort"]
            game[f"{side}_resolution"] = info["resolution"]
            game[f"{side}_match_status"] = info["match_status"]
            game[f"{side}_aau_team_url"] = info["profile_path"]

    report = []
    for key in sorted(cache):
        info = cache[key]
        info["circuit_appearances"] = report_games[key]
        report.append(info)
    return report


def export_match_report(report, path):
    fields = ["circuit", "raw_name", "division", "gender", "canonical_team_id",
              "age_cohort", "resolution", "match_status", "identity_division",
              "circuit_appearances", "aau_appearances", "aau_aliases",
              "aau_divisions", "aau_stored_ids", "profile_path"]
    with Path(path).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows([{field: r.get(field, "") for field in fields} for r in report])
