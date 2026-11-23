import copy
import datetime as dt
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_db import SCHEMA, build_teams, load_fb
from rank_teams import games_for_team
from team_identity import event_provider_alias
from upcoming_games import fastbreak_date, render_upcoming_games, upcoming_by_team

# User-confirmed alias: 14U TM Falcons Black and bare TM Falcons are the
# same cohort. The FastBreak provider/event scope assertions are unchanged.
BLACK = "tm:falcons-14u"
OPPONENT = "Hoop Famillia (Mayan) 8th/14U"
OTHER = "East Bay Athletics 14u Red (Jeremy) 8th/14U"


def game(game_id, home, away, home_id, away_id, time, date="Nov 21, 2026",
         status="Scheduled", score=None):
    return {"game_id": str(game_id), "division_name": "14u Silver Sat Only",
            "pool": "Pool A", "date": date, "weekday": "Saturday", "time": time,
            "venue": "The Ultimate Fieldhouse", "court": "1", "home_team": home,
            "away_team": away, "home_team_id": home_id, "away_team_id": away_id,
            "home_score": score, "away_score": score, "home_winner": False,
            "away_winner": False, "status": status}


class FastbreakScheduleTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.executescript(SCHEMA)
        self.source_data = {
            "metadata": {"event_id": 11535, "slug": "thanksgiving-hoopfest",
                         "title": "Thanksgiving HoopFest", "start_date": "2026-11-21T00:00:00Z",
                         "end_date": "2026-11-22T00:00:00Z", "city": "Walnut Creek",
                         "tenant": 654, "url": "https://buzzerbeaterevents.fastbreakcompete.ai/event/11535-thanksgiving-hoopfest"},
            "scraped_at": "2026-11-20T00:00:00Z",
            "divisions": [{"Id": 55585, "Name": "14u Silver Sat Only", "games": 4, "scored": 1}],
            "games": [
                game(469635, OPPONENT, "TM Falcons 14u 8th/14U", "280893", 280786, "2:00 PM PT"),
                game(469638, "TM Falcons 14u 8th/14U", OTHER, 280786, "280891", "2:55 PM PT"),
                game(469699, "TM Falcons 14u 8th/14U", "TBD", 280786, "", "10:00 AM PT", "Nov 22, 2026"),
                game(469700, "TM Falcons 14u 8th/14U", OPPONENT, 280786, "280893", "9:00 AM PT", status="FINAL", score=58),
            ],
        }
        with mock.patch("builtins.open", new_callable=mock.mock_open), \
                mock.patch("build_db.json.load", return_value=self.source_data):
            self.assertEqual(load_fb(self.con.cursor(), "unused.json"), 4)
        build_teams(self.con.cursor())
        self.opponent_id = self.con.execute(
            "SELECT team_id FROM team_names WHERE raw_name=? AND division_hint=?",
            (OTHER, "14u Silver Sat Only")).fetchone()[0]
        self.assertTrue(self.opponent_id.endswith(":14u"), self.opponent_id)
        self.assertNotIn("/:", self.opponent_id)

    def tearDown(self):
        self.con.close()

    def test_scoped_alias_does_not_extend_to_other_events(self):
        self.assertEqual(event_provider_alias(11535, 280786), BLACK)
        self.assertIsNone(event_provider_alias(12345, 280786))
        self.assertIsNone(event_provider_alias(11535, 999999))
        self.assertEqual(self.con.execute(
            "SELECT count(*) FROM fb_team_links WHERE team_id=?", (BLACK,)).fetchone()[0], 4)

    def test_schedule_joins_specific_games_and_filters_results_and_tbd(self):
        rows = upcoming_by_team(self.con.cursor(), dt.date(2026, 11, 20))[BLACK]
        self.assertEqual(len(rows), 3)
        confirmed = [row for row in rows if not row["opponent_pending"]]
        self.assertEqual([(g["opponent"], g["time"], g["side"]) for g in confirmed],
                        [(OPPONENT, "2:00 PM PT", "away"),
                         (OTHER, "2:55 PM PT", "home")])
        self.assertEqual(confirmed[1]["opponent_team_id"], self.opponent_id)
        self.assertTrue(rows[2]["opponent_pending"])
        self.assertEqual(rows[0]["url"], "https://buzzerbeaterevents.fastbreakcompete.ai/event/11535-thanksgiving-hoopfest")
        self.assertEqual(rows[0]["court"], "1")

    def test_scheduled_placeholder_scores_are_not_treated_as_results(self):
        data = copy.deepcopy(self.source_data)
        data["games"].append(game(469777, "TM Falcons 14u 8th/14U", OPPONENT,
                                  280786, "280893", "4:00 PM PT", score=5))
        with mock.patch("builtins.open", new_callable=mock.mock_open), \
                mock.patch("build_db.json.load", return_value=data):
            self.assertEqual(load_fb(self.con.cursor(), "scheduled.json"), 5)
        rows = upcoming_by_team(self.con.cursor(), dt.date(2026, 11, 20))[BLACK]
        self.assertEqual(len(rows), 4)
        self.assertIn(469777, [row["game_id"] for row in rows])
        rendered = render_upcoming_games(rows, {})
        self.assertNotIn("5–5", rendered)

    def test_result_dates_and_winner_evidence(self):
        con = sqlite3.connect(":memory:")
        con.executescript(SCHEMA)
        con.execute("INSERT INTO fb_events(event_id,title,start_date,url) VALUES ('9000','Date event','2026-11-21T00:00:00Z','https://example.test/event')")
        con.execute("INSERT INTO team_names VALUES ('Alpha','14u Silver Sat Only','alpha:14u','normalized')")
        def insert(gid, date, hs, aws, hw, aw, status="FINAL"):
            con.execute("INSERT INTO fb_games VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("9000", gid, date, "Saturday", "1:00 PM PT",
                         "14u Silver Sat Only", "Pool A", "Alpha", "Opponent",
                         hs, aws, hw, aw, status, "Gym", "1"))
        insert(1, "Nov 21, 2026", 58, 43, 1, 0)
        insert(2, "Nov 22", 30, 51, 0, 1)
        insert(3, "garbage", 58, 43, 1, 0)
        insert(4, "Nov 23, 2026", 58, 58, 0, 0)
        insert(5, "Nov 24, 2026", None, None, 1, 0)
        rows = games_for_team(con.cursor(), "alpha:14u", None, None)
        self.assertEqual([g[0] for g in rows], ["2026-11-22", "2026-11-21"])
        self.assertNotIn("2026-01-01", [g[0] for g in rows])
        con.close()

    def test_fastbreak_date_uses_event_year_near_boundaries(self):
        self.assertEqual(fastbreak_date("Nov 21", "2026-11-21T00:00:00Z"),
                         dt.date(2026, 11, 21))
        self.assertEqual(fastbreak_date("Jan 1", "2026-12-31T00:00:00Z"),
                         dt.date(2027, 1, 1))
        self.assertIsNone(fastbreak_date("unknown", "2026-11-21T00:00:00Z"))

    def test_renderer_links_safe_sources_and_does_not_link_javascript(self):
        rows = upcoming_by_team(self.con.cursor(), dt.date(2026, 11, 20))[BLACK]
        html = render_upcoming_games(rows, {self.opponent_id: "teams/14u/east-bay-red.html"})
        self.assertIn("Upcoming schedule (3)", html)
        self.assertIn("2:00 PM PT", html)
        self.assertIn("2:55 PM PT", html)
        self.assertIn("The Ultimate Fieldhouse", html)
        self.assertIn("Court 1", html)
        self.assertIn("../../teams/14u/east-bay-red.html", html)
        self.assertIn("opponent pending", html)
        unsafe = copy.deepcopy(rows[0])
        unsafe["url"] = "javascript:alert(1)"
        self.assertNotIn("javascript:", render_upcoming_games([unsafe], {}))


if __name__ == "__main__":
    unittest.main()
