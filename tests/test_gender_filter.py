import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from rank_teams import games_for_team


class NamesOnlyDB:
    def __init__(self, names):
        self.names = names
        self.result = []
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        self.result = self.names if "FROM team_names" in sql else []
        return self

    def fetchall(self):
        return self.result


class BoysGenderFilterTests(unittest.TestCase):
    def test_explicit_girls_squad_is_excluded_even_in_boys_division(self):
        db = NamesOnlyDB([("24/8 Academy", "Boys 8th Gold")])
        games = games_for_team(db, "24 8 academy:14u girls", None, "boys")
        self.assertEqual(games, [])
        self.assertEqual(db.calls, [])

    def test_girls_or_mixed_cli_mode_keeps_grade_source_aliases(self):
        for gender in ("girls", None):
            db = NamesOnlyDB([("24/8 Academy", "14u/8th Grade Boys")])
            games_for_team(db, "24 8 academy:14u girls", None, gender)
            self.assertTrue(db.calls, gender)

    def test_raw_girls_label_is_excluded_without_division_or_id_marker(self):
        db = NamesOnlyDB([("ALAMEDA VIPERS - MANABAT (11U GIRLS)", "11U/12U")])
        games = games_for_team(db, "alameda vipers manabat:11u", None, "boys")
        self.assertEqual(games, [])
        self.assertEqual(len(db.calls), 1)

    def test_boys_mode_still_excludes_girls_divisions_without_name_suffix(self):
        db = NamesOnlyDB([("Example", "Girls 8th Silver")])
        games = games_for_team(db, "example:14u", None, "boys")
        self.assertEqual(games, [])
        self.assertEqual(len(db.calls), 1)


if __name__ == "__main__":
    unittest.main()
