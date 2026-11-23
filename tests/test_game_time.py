import datetime as dt
import shutil
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from game_time import order_games, source_time, timestamp_ms


def milliseconds(year, month, day, hour):
    return int(dt.datetime(year, month, day, hour, tzinfo=dt.timezone.utc).timestamp() * 1000)


class GameTimeTests(unittest.TestCase):
    def test_explicit_ee_timezone_is_normalized_to_utc(self):
        info = source_time("2026-11-21", "8:00 AM PST", "Pacific Standard Time", "ee")
        self.assertEqual(info["utc"], "2026-11-21T16:00:00Z")
        self.assertEqual(info["utc_ms"], milliseconds(2026, 11, 21, 16))
        self.assertFalse(info["assumed_pacific"])

    def test_provider_without_timezone_is_disclosed_assumption(self):
        info = source_time("2026-11-22", "14:25", None, "bt")
        self.assertTrue(info["assumed_pacific"])
        self.assertEqual(info["source_timezone"], "America/Los_Angeles")
        self.assertEqual(info["utc"], "2026-11-22T22:25:00Z")

    def test_pt_suffix_respects_daylight_saving_and_explicit_offsets(self):
        summer = source_time("2026-07-15", "9:00 AM PDT", None, "fb")
        winter = source_time("2026-11-22", "09:00", None, "bt")
        self.assertEqual(summer["utc"], "2026-07-15T16:00:00Z")
        self.assertEqual(winter["utc"], "2026-11-22T17:00:00Z")
        explicit = source_time("2026-11-22", "9:00 AM -05:00", None, "ee")
        self.assertEqual(explicit["utc"], "2026-11-22T14:00:00Z")

    def test_unrecognized_time_or_timezone_never_becomes_timestamp(self):
        self.assertIsNone(source_time("2026-11-21", "TBD", "Pacific Standard Time", "ee"))
        self.assertIsNone(source_time("2026-11-21", "12:99", None, "bt"))
        self.assertIsNone(source_time("2026-11-22", "12:10 PM", "Mars/Olympus", "ee"))
        self.assertIsNone(source_time("2026-11-22", "10:00 AM", "UTC+15:00", "ee"))
        self.assertIsNone(source_time("2026-11-22", "10:00 AM", "Pacific Standard Time", "1992"))

    def test_date_precedes_time_then_clock_and_unknowns_sort_last(self):
        late = ("2026-11-21", True, 1, "open", "e", "14u", "self", "a", 1, 1, None,
                {"tipoff": "8:00 AM PST", "time_zone": "Pacific Standard Time", "source": "ee"})
        next_day = ("2026-11-22", True, 1, "open", "f", "14u", "self", "b", 1, 1, None,
                    {"tipoff": "8:00 AM", "source": "bt"})
        untimed = late[:-1] + (dict(late[-1], tipoff=None),)
        soon = late[:-1] + (dict(late[-1], tipoff="9:40 AM PST"),)
        ordered = order_games([late, next_day, late, soon, untimed])
        self.assertEqual(ordered[0], next_day)
        self.assertEqual([g[11]["tipoff"] for g in ordered[1:3]],
                         ["9:40 AM PST", "8:00 AM PST"])
        self.assertIsNone(ordered[-1][11]["tipoff"])

    def test_ee_metadata_reaches_rank_export_without_changing_link_payload(self):
        try:
            import rank_teams
        except ImportError:
            self.fail("rank_teams import failed")

        class Query:
            rows = []

            def execute(self, sql, params=()):
                if "FROM team_names" in sql:
                    self.rows = [("Vision (Edwards) Black 14U", "14u Open")]
                elif "FROM ee_games" in sql:
                    self.rows = [("11/21/2026", "Vision (Edwards) Black 14U", "Opp", "60", "35", 1, 0,
                                  "Final", "273463", "14u Open", "Pool A",
                                  "vision-edwards-black-14u", "opp-slug", 5680402, 0, 81, 555,
                                  "8:00 AM PST", "Pacific Standard Time")]
                else:
                    self.rows = []
                return self

            def fetchall(self):
                return self.rows

        query = Query()
        games = rank_teams.games_for_team(query, "vision edwards black:14u", None, "boys")
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0][11]["tipoff"], "8:00 AM PST")
        self.assertEqual(games[0][11]["time_zone"], "Pacific Standard Time")
        self.assertEqual(games[0][11]["dt"], 5680402)

    def test_mexico_windows_timezone_uses_its_iana_zone(self):
        info = source_time("2026-11-21", "8:00 AM PST",
                           "Pacific Standard Time (Mexico)", "ee")
        self.assertEqual(info["utc"], "2026-11-21T16:00:00Z")
        self.assertEqual(info["source_timezone"], "Pacific Standard Time (Mexico)")
        self.assertFalse(info["assumed_pacific"])

    def test_html_utc_fallback_preserves_source_metadata(self):
        from build_site import game_time_cells

        info = source_time("2026-11-21", "8:00 AM PST", "Pacific Standard Time", "ee")
        attrs, date_cell, time_cell = game_time_cells(
            {"d": "2026-11-21", "tipoff": info})
        self.assertIn(f'data-utc-ms="{info["utc_ms"]}"', attrs)
        self.assertIn('data-known-time="1"', attrs)
        self.assertIn('data-assumed-pacific="0"', attrs)
        self.assertEqual(date_cell, '<td data-cell="date">11-21</td>')
        self.assertIn("16:00 UTC", time_cell)
        self.assertIn("Pacific Standard Time", time_cell)
        self.assertIn('datetime="2026-11-21T16:00:00Z"', time_cell)

    def test_html_date_boundaries_assumptions_and_unknowns(self):
        from build_site import game_time_cells

        cross_day = source_time("2026-11-21", "11:30 PM PST",
                                "Pacific Standard Time", "ee")
        attrs, date_cell, _ = game_time_cells(
            {"d": "2026-11-21", "tipoff": cross_day})
        self.assertIn('data-source-date="2026-11-21"', attrs)
        self.assertEqual(date_cell, '<td data-cell="date">11-22</td>')

        assumed, _, _ = game_time_cells(
            {"d": "2026-11-22", "tipoff": "13:50"})
        self.assertIn('data-assumed-pacific="1"', assumed)
        attrs, _, cell = game_time_cells({"d": "2026-11-21", "tipoff": "TBD"})
        self.assertIn('data-utc-ms=""', attrs)
        self.assertIn('data-known-time="0"', attrs)
        self.assertEqual(cell, '<td data-cell="tipoff">—</td>')
        self.assertNotIn("00:00", cell)

    @unittest.skipUnless(shutil.which("node"), "optional Node runtime is unavailable")
    def test_browser_conversion_and_primary_date_sort(self):
        result = subprocess.run(
            ["node", str(ROOT / "tests" / "game_sort.test.js")],
            cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
