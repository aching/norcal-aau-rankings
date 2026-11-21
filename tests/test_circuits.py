import csv
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_circuits_site import APP_JS, SLIM_FIELDS, export_site
from build_site import render_circuit_games
from export_circuits_2026 import FIELDS
from scrape_uaa import parse_page
from circuit_identity import enrich_games, identity_parts
from team_identity import age_cohort, division_age, resolve


class CircuitSiteTests(unittest.TestCase):
    def test_export_uses_external_json_and_sanitizes_urls(self):
        game = {field: "" for field in FIELDS}
        game.update(circuit="UAA", series="UAA", division="17U",
                    event="Fixture", date="2026-07-18", home_team="Home <One>",
                    away_team="Away <Two>", home_score="60", away_score="55",
                    status="Final", game_id="game-1", url="javascript:alert(1)",
                    home_canonical_team="home one:15u", home_age_cohort=15,
                    home_resolution="normalized", home_match_status="matched",
                    home_aau_team_url="teams/15u/home-one.html",
                    away_aau_team_url="javascript:alert(1)")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            event_csv = tmp / "events.csv"
            event_csv.write_text("circuit,series,event_id,event,games,final_games,first_date,last_date,url\n")
            export_site([game], event_csv, tmp / "site")
            data = json.loads((tmp / "site" / "games.json").read_text())
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0][SLIM_FIELDS.index("url")], "")
            self.assertEqual(data[0][SLIM_FIELDS.index("home_team")], "Home <One>")
            self.assertEqual(data[0][SLIM_FIELDS.index("home_aau_team_url")],
                             "../teams/15u/home-one.html")
            self.assertEqual(data[0][SLIM_FIELDS.index("away_aau_team_url")], "")
            self.assertNotIn("innerHTML", APP_JS)
            self.assertIn("startsWith('../teams/')", APP_JS)
            page_html = (tmp / "site" / "index.html").read_text()
            self.assertNotIn("Fixture", page_html)
            self.assertIn("<strong>1</strong> link directly to an existing AAU team profile", page_html)
            self.assertNotIn("innerHTML", APP_JS)
            self.assertNotIn("document.write", APP_JS)
            self.assertTrue((tmp / "site" / "events.csv").exists())
            with (tmp / "site" / "games.csv").open() as f:
                self.assertEqual(next(csv.DictReader(f))["game_id"], "game-1")

    def test_uaa_parser_handles_classless_wrapper_and_named_teams(self):
        source = """
<div class='avt'>Girls 14U</div><div class="ToggleSubheaderH2CustomHighlight">Girls 14U</div>
<div class='synGamesWrapper'><div class='ozaccbtn small'>Session 1 &#8211; 04 17, 2026</div>
<div class='synGame' data-home='Carolina Flames' data-away='FBC United Reign'><follow>
<div class='synTeamResults bold'><div class='synTeam team-CarolinaFlames'>Carolina Flames</div><div class='synScore'>50</div></div>
<div class='synTeamResults '><div class='synTeam team-FBCUnitedReign'>FBC United Reign</div><div class='synScore'>43</div></div>
</follow></div></div>
"""
        records = parse_page({"content": {"rendered": source}}, "girls-uaa")
        self.assertEqual(len(records), 1)
        game = records[0]
        self.assertEqual(game["date"], "2026-04-17")
        self.assertEqual((game["home_team"], game["away_team"]),
                         ("Carolina Flames", "FBC United Reign"))
        self.assertEqual((game["home_score"], game["away_score"]), ("50", "43"))
        self.assertEqual((game["home_won"], game["away_won"]), (1, 0))
        self.assertEqual(game["url"], "https://underarmournext.com/basketball/girls-uaa/")


class CircuitIdentityTests(unittest.TestCase):
    def test_circuit_shorthand_and_grade_cohorts(self):
        self.assertEqual(division_age("EYCL 15'S"), "15u")
        self.assertEqual(division_age("EYCL 17’S"), "17u")
        self.assertEqual(age_cohort("8th"), 14)
        self.assertEqual(age_cohort("11th"), 17)
        self.assertEqual(resolve("Soldiers Camo", "EYCL 15'S"),
                         ("soldiers camo:15u", "normalized"))
        self.assertEqual(identity_parts("Example Elite 15U", "9th Grade")[2], 15)

    def test_scoped_camo_2030_alias_does_not_merge_other_grades(self):
        self.assertEqual(identity_parts("Oakland Soldiers Camo", "8th Grade Boys (2030)")[:3],
                         ("oakland soldiers camo:14u", "curated", 14))
        self.assertEqual(identity_parts("Oakland Soldiers Camo", "7th Grade Boys (2031)")[:3],
                         ("oakland soldiers camo:7th", "normalized", 13))
        self.assertEqual(identity_parts("Oakland Soldiers Camo", "6th Grade Boys (2032)")[:3],
                         ("oakland soldiers camo:6th", "normalized", 12))
        self.assertEqual(identity_parts("Other Soldiers Camo", "8th Grade Boys (2030)")[:3],
                         ("other soldiers camo:8th", "normalized", 14))

    def test_profile_circuit_renderer_escapes_names_and_shows_results(self):
        game = {
            "date": "2026-04-17", "time": "9:10 AM", "circuit": "EYBL",
            "series": "Junior EYBL", "division": "8th Grade Boys (2030)",
            "home_team": "Oakland Soldiers Camo", "away_team": "Gen <Team>",
            "home_score": "77", "away_score": "50", "home_won": "1", "away_won": "0",
            "event": "2026 Jr. EYBL - West", "url": "https://peachjam.nikeeyb.com/peach-jam",
            "status": "Final", "game_id": "eybl-camo-1",
        }
        page = render_circuit_games([(game, "home", "away")])
        self.assertIn('id="circuit-games"', page)
        self.assertIn("W 77–50", page)
        self.assertIn("Gen &lt;Team&gt;", page)
        self.assertIn("not included in AAU record or ranking totals", page)
        self.assertIn('href="https://peachjam.nikeeyb.com/peach-jam"', page)

    def test_camo_matches_respect_cohort_and_unknown_age(self):
        camo8 = "oakland soldiers camo:8th"
        camo6 = "oakland soldiers camo:6th"
        entries = [
            {"raw_name": "Oakland Soldiers Camo", "division_hint": "8th Grade Boys (2031)",
             "team_id": camo8, "resolution": "normalized"},
            {"raw_name": "Oakland Soldiers Camo", "division_hint": "6th Grade Boys (2032)",
             "team_id": camo6, "resolution": "normalized"},
            {"raw_name": "Example Elite 15U", "division_hint": "9th Grade",
             "team_id": "example elite:15u", "resolution": "normalized"},
            {"raw_name": ": Qualifier", "division_hint": "9th Grade",
             "team_id": "prog:qualifier", "resolution": "bare"},
            {"raw_name": "Test Elite", "division_hint": "17U Girls",
             "team_id": "test elite:17u girls", "resolution": "normalized"},
            {"raw_name": "AOT", "division_hint": "EYCL 17'S",
             "team_id": "prog:aot", "resolution": "bare"},
            {"raw_name": "TM Falcons", "division_hint": "14U",
             "team_id": "tm:falcons-14u", "resolution": "override"},
            {"raw_name": "FRO 13u (CA)", "division_hint": "14U",
             "team_id": "fro ca:13u", "resolution": "normalized"},
        ]
        games = [
            {"circuit": "EYBL", "division": "8th Grade Boys (2031)",
             "home_team": "Oakland Soldiers Camo", "away_team": "Other Team"},
            {"circuit": "EYBL", "division": "6th Grade Boys (2032)",
             "home_team": "Oakland Soldiers Camo", "away_team": "Other Team"},
            {"circuit": "EYBL", "division": "9th Grade",
             "home_team": "Example Elite 15U", "away_team": ": Qualifier"},
            {"circuit": "UAA", "division": "17U", "gender": "girls",
             "home_team": "Test Elite", "away_team": "No Age Club"},
            {"circuit": "3SSB", "division": "Open", "home_team": "No Age Club",
             "away_team": "Example Elite 15U", "home_team_id": "provider-uuid"},
            {"circuit": "EYBL", "division": "EYCL 17'S", "home_team": "AOT",
             "away_team": "Other Team"},
            {"circuit": "3SSB", "division": "Open", "home_team": "TM Falcons",
             "away_team": "Other Team"},
            {"circuit": "3SSB", "division": "14U", "home_team": "FRO 13u (CA)",
             "away_team": "Other Team"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for cohort, name in (("14u", "camo8.html"), ("12u", "camo6.html"),
                                 ("14u", "tm.html"), ("14u", "fro.html")):
                path = Path(tmp) / "teams" / cohort / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("profile")
            page_of = {camo8: ("14u", "camo8.html"), camo6: ("12u", "camo6.html"),
                       "tm:falcons-14u": ("14u", "tm.html"),
                       "fro ca:13u": ("14u", "fro.html")}
            appearances = Counter({("Oakland Soldiers Camo", "8th Grade Boys (2031)"): 37})
            report = enrich_games(games, entries, page_of, appearances, site_root=tmp)

        self.assertEqual(games[0]["home_canonical_team"], camo8)
        self.assertEqual(games[0]["home_aau_team_url"], "teams/14u/camo8.html")
        self.assertEqual(games[1]["home_canonical_team"], camo6)
        self.assertEqual(games[1]["home_aau_team_url"], "teams/12u/camo6.html")
        self.assertEqual(games[2]["home_age_cohort"], 15)
        self.assertEqual(games[2]["away_match_status"], "matched")
        self.assertEqual(games[2]["away_aau_team_url"], "")
        self.assertEqual(games[3]["home_canonical_team"], "test elite:17u girls")
        self.assertEqual(games[3]["away_match_status"], "unmatched")
        self.assertEqual(games[4]["home_match_status"], "ambiguous")
        self.assertEqual(games[4]["home_team_id"], "provider-uuid")
        camo_report = next(r for r in report if r["canonical_team_id"] == camo8)
        self.assertEqual(camo_report["aau_appearances"], 37)
        self.assertEqual(games[5]["home_match_status"], "matched")
        aot_report = next(r for r in report if r["raw_name"] == "AOT")
        self.assertEqual(aot_report["canonical_team_id"], "aot:17u")
        self.assertEqual(aot_report["aau_stored_ids"], "prog:aot")
        self.assertEqual(games[6]["home_match_status"], "age_unknown")
        self.assertEqual(games[6]["home_aau_team_url"], "")
        self.assertEqual(games[7]["home_age_cohort"], 13)
        self.assertEqual(games[7]["home_match_status"], "matched")
        self.assertEqual(games[7]["home_aau_team_url"], "")


if __name__ == "__main__":
    unittest.main()
