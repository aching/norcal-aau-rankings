#!/usr/bin/env python3
"""Combine cached 2026 UAA, Nike EYBL, and West circuit game data."""
import csv
import datetime as dt
import html
import json
from collections import Counter
from pathlib import Path

from build_site import all_pages_map
from circuit_identity import (IDENTITY_FIELDS, enrich_games,
                              export_match_report, load_aau_entries)

FIELDS = ["source", "circuit", "series", "gender", "division", "event_id",
          "event", "session", "date", "time", "game_type", "home_team",
          "away_team", "home_score", "away_score", "home_won", "away_won",
          "status", "venue", "court", "game_id", "home_team_id",
          "away_team_id", "url", "source_pages"] + IDENTITY_FIELDS


def row(**values):
    result = {field: "" for field in FIELDS}
    result.update(values)
    return result


def iso_date(value):
    return dt.datetime.strptime(value, "%m/%d/%Y").date().isoformat()


def load_west():
    rows = []
    with Path("data/circuits_2026_west.csv").open() as f:
        for r in csv.DictReader(f):
            title = html.unescape(r["event"])
            title_lower = title.lower()
            if r["circuit"] == "EYBL":
                series = "Junior EYBL"
            elif "3stripes gold" in title_lower:
                series = "3SSB Gold"
            elif "jr. 3ssb" in title_lower or "jr 3ssb" in title_lower:
                series = "Junior 3SSB"
            else:
                series = "3SSB"
            gender = ("girls" if "girls" in r["division"].lower()
                      else "boys" if "boys" in r["division"].lower() else "")
            source_url = r["url"]
            r.update(event=title, series=series, gender=gender,
                     date=iso_date(r["date"]) if r["date"] else "",
                     session="", source_pages=source_url)
            rows.append(row(**r))
    return rows


def load_nike():
    rows = []
    for phase in ("previous", "current"):
        path = Path(f"data/nike_eybl_2026_{phase}.json")
        payload = json.loads(path.read_text())
        event = payload["event"]
        for g in payload["games"]:
            code = g["divisionCode"]
            division = {"EYBL": "17U", "E16": "16U", "E15": "15U", "PIT": "17U"}.get(code, code)
            series = "PIT" if code == "PIT" else "EYCL" if code.startswith("EYCL") else "EYBL"
            home, away = g["homeTeam"], g["awayTeam"]
            hs, away_score = home.get("score"), away.get("score")
            final = hs is not None and away_score is not None
            rows.append(row(
                source="peachjam.nikeeyb.com/exposure-schedule", circuit="EYBL",
                series=series, gender="boys", division=division, event_id=event["id"],
                event=event["title"], session="", date=g["date"], time=g.get("time", ""),
                game_type=g.get("round") or str(g.get("type") or ""),
                home_team=home["name"], away_team=away["name"],
                home_score=hs if hs is not None else "",
                away_score=away_score if away_score is not None else "",
                home_won=int(hs > away_score) if final else None,
                away_won=int(away_score > hs) if final else None,
                status="Final" if final else "Scheduled", venue=g.get("venue", ""),
                court=g.get("court", ""), game_id=g["id"], home_team_id=home.get("id", ""),
                away_team_id=away.get("id", ""),
                url="https://peachjam.nikeeyb.com/peach-jam",
                source_pages=str(path)))
    return rows


def load_uaa():
    rows = []
    # The EE aggregate schedule below supersedes these overlapping girls UAA rows.
    with Path("data/circuits_2026_uaa.csv").open() as f:
        for r in csv.DictReader(f):
            if r["gender"] == "girls" and r["series"] == "UAA":
                continue
            rows.append(row(**r))
    payload = json.loads(Path("data/265832.json").read_text())
    title = payload["metadata"]["title"].split(" - Schedule - ")[0]
    for g in payload["games"]:
        division = g.get("_division_name", "")[:3].upper()
        rows.append(row(
            source="exposureevents", circuit="UAA", series="UAA", gender="girls",
            division=division, event_id="265832", event=title, session="",
            date=iso_date(g["DateFormatted"]), time=g.get("TimeFormatted", ""),
            game_type=g.get("GameTypeName", ""), home_team=g["HomeTeamName"],
            away_team=g["AwayTeamName"], home_score=g.get("HomeTeamScoreDisplay", ""),
            away_score=g.get("AwayTeamScoreDisplay", ""), home_won=int(g["HomeTeamIsWinner"]),
            away_won=int(g["AwayTeamIsWinner"]), status=g.get("Status", ""),
            venue=g.get("VenueName", ""), court=g.get("CourtName", ""), game_id=g["Id"],
            home_team_id=g.get("HomeDivisionTeamId", ""),
            away_team_id=g.get("AwayDivisionTeamId", ""),
            url="https://basketball.exposureevents.com/265832/girls-under-armour-association-2026/schedule",
            source_pages="data/265832.json"))
    return rows


def main():
    rows = load_west() + load_nike() + load_uaa()
    entries, appearances = load_aau_entries("data/aau.db")
    report = enrich_games(rows, entries, all_pages_map(), appearances)
    export_match_report(report, "data/circuit_team_matches_2026.csv")
    matched_variants = sum(r["match_status"] == "matched" for r in report)
    matched_appearances = sum(r["circuit_appearances"] for r in report
                              if r["match_status"] == "matched")
    print(f"AAU identity: {matched_variants}/{len(report)} variants matched; "
          f"{matched_appearances}/{2*len(rows)} team appearances cohort-matched")
    rows.sort(key=lambda r: (r["date"], r["circuit"], r["series"], r["event_id"],
                             r["division"], r["time"], str(r["game_id"])))
    out = Path("data/circuits_2026_all.csv")
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    Path("data/circuits_2026_all.json").write_text(json.dumps(rows, indent=2) + "\n")

    grouped = {}
    for r in rows:
        key = (r["circuit"], r["series"], r["event_id"], r["event"])
        event = grouped.setdefault(key, {"games": 0, "final_games": 0,
                                         "dates": [], "url": r["url"]})
        event["games"] += 1
        event["final_games"] += r["status"].lower() == "final"
        event["dates"].append(r["date"])
    event_fields = ["circuit", "series", "event_id", "event", "games",
                    "final_games", "first_date", "last_date", "url"]
    with Path("data/circuits_2026_events.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=event_fields, lineterminator="\n")
        writer.writeheader()
        for key in sorted(grouped):
            event = grouped[key]
            writer.writerow(dict(zip(event_fields[:4], key), games=event["games"],
                final_games=event["final_games"], first_date=min(event["dates"]),
                last_date=max(event["dates"]), url=event["url"]))
    print(f"wrote data/circuits_2026_events.csv: {len(grouped)} event groups")

    counts = Counter((r["circuit"], r["series"]) for r in rows)
    print(f"wrote {out} and data/circuits_2026_all.json: {len(rows)} games")
    for group in sorted(counts):
        print(f"{group[0]:4s}  {group[1]:15s} {counts[group]:5d}")
    print("final scores:", sum(r["status"].lower() == "final" for r in rows))
    print("missing score rows:", sum(not str(r["home_score"]) or not str(r["away_score"]) for r in rows))


if __name__ == "__main__":
    main()
