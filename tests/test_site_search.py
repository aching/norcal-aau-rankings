import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_site


class SiteSearchTests(unittest.TestCase):
    def test_board_search_data_includes_unranked_team_profiles(self):
        rows = [[
            "1", "fury:14u", "0.100", "1-0 (last 1)", "gold",
            "0.100", "+5.0", "2026-11-07", "Form 1-0",
        ]]
        logs = {
            "fury:14u": [{"d": "2026-11-07", "w": True, "score": "50-45"}],
            "hoop familia guerrero:14u": [
                {"d": "2026-11-07", "w": True, "score": "48-40"},
                {"d": "2026-11-07", "w": False, "score": "35-42"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(build_site, "OUT", Path(tmp)), \
                patch.object(build_site, "parse_rep",
                             return_value=(rows, [], "", {}, {})), \
                patch.object(build_site, "game_logs", return_value=logs), \
                patch.object(build_site, "upcoming_rosters", return_value={}), \
                patch.object(build_site, "circuit_team_games", return_value={}), \
                patch.object(build_site, "team_page", return_value="profile"):
            build_site.build_board("14u", "14U/8th Grade", "test", "2026-11-20")
            board = (Path(tmp) / "14u.html").read_text()
            unranked = (Path(tmp) / "14u-unranked.html").read_text()
            profile = Path(tmp) / "teams/14u/hoop-familia-guerrero-14u.html"
            profile_text = profile.read_text()

        match = re.search(r"const DATA = (.*);\nlet sortKey", board)
        self.assertIsNotNone(match)
        data = {r["team"]: r for r in json.loads(match.group(1))}
        self.assertEqual(set(data), set(logs))
        self.assertEqual(data["hoop familia guerrero:14u"]["rank"], 0)
        self.assertEqual(
            data["hoop familia guerrero:14u"]["page"],
            "teams/14u/hoop-familia-guerrero-14u.html",
        )
        self.assertIn("(needle || r.rank) &&", board)
        self.assertIn('["num", r.rank ? "#" + (ranked ? r.rank : (i + 1)) : "UR"]',
                      board)
        self.assertIn('href="teams/14u/hoop-familia-guerrero-14u.html"', unranked)
        self.assertEqual(profile_text, "profile")


if __name__ == "__main__":
    unittest.main()
