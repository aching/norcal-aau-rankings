import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_circuits_site import APP_JS, SLIM_FIELDS, export_site
from export_circuits_2026 import FIELDS
from scrape_uaa import parse_page


class CircuitSiteTests(unittest.TestCase):
    def test_export_uses_external_json_and_sanitizes_urls(self):
        game = {field: "" for field in FIELDS}
        game.update(circuit="UAA", series="UAA", division="17U",
                    event="Fixture", date="2026-07-18", home_team="Home <One>",
                    away_team="Away <Two>", home_score="60", away_score="55",
                    status="Final", game_id="game-1", url="javascript:alert(1)")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            event_csv = tmp / "events.csv"
            event_csv.write_text("circuit,series,event_id,event,games,final_games,first_date,last_date,url\n")
            export_site([game], event_csv, tmp / "site")
            data = json.loads((tmp / "site" / "games.json").read_text())
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0][SLIM_FIELDS.index("url")], "")
            self.assertEqual(data[0][SLIM_FIELDS.index("home_team")], "Home <One>")
            self.assertNotIn("Fixture", (tmp / "site" / "index.html").read_text())
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


if __name__ == "__main__":
    unittest.main()
