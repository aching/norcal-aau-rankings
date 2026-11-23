import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from team_identity import resolve


CONFIRMED_ALIAS = "Lakeshow 14U Duckett 8th/14U"
CANONICAL = "lakeshow duckett:14u"


class DuckettIdentityTests(unittest.TestCase):
    def test_confirmed_eighth_grade_label_merges_into_fourteen_u_team(self):
        team_id, confidence = resolve(CONFIRMED_ALIAS, "14U Silver East")
        self.assertEqual(team_id, CANONICAL)
        self.assertEqual(confidence, "override")

    def test_existing_bare_label_keeps_the_same_identity(self):
        self.assertEqual(resolve("Lakeshow Duckett", "14U/8th Grade Silver/Bronze")[0],
                         CANONICAL)

    def test_explicit_play_up_and_other_cohorts_remain_separate(self):
        self.assertEqual(resolve("Lakeshow 13U (Duckett) 8th/14U",
                                 "14u Silver West")[0],
                         "lakeshow duckett 8th:13u")
        self.assertEqual(resolve("Lakeshow 11U Duckett", "5th Boys Gold")[0],
                         "lakeshow duckett:11u")

    def test_girls_division_does_not_use_boys_override(self):
        team_id, confidence = resolve(CONFIRMED_ALIAS, "14u Girls Gold")
        self.assertNotEqual(team_id, CANONICAL)
        self.assertNotEqual(confidence, "override")


if __name__ == "__main__":
    unittest.main()
