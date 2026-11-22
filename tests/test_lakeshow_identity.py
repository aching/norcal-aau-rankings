import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from team_identity import resolve


CONFIRMED_ALIAS = "Lakeshow 14U (Fuca) 8th/14U"
CANONICAL = "lakeshow fuca:14u"


class LakeshowIdentityTests(unittest.TestCase):
    def test_confirmed_fastbreak_alias_uses_history_carrying_identity(self):
        team_id, confidence = resolve(CONFIRMED_ALIAS, "14u Gold")
        self.assertEqual(team_id, CANONICAL)
        self.assertEqual(confidence, "override")

    def test_existing_fastbreak_spelling_still_uses_same_identity(self):
        team_id, _ = resolve("Lakeshow 14U Fuca 8th/14U", "14u Gold")
        self.assertEqual(team_id, CANONICAL)

    def test_other_lakeshow_cohorts_stay_separate(self):
        self.assertEqual(resolve("Lakeshow 13U Fuca", "13u Gold")[0],
                         "lakeshow fuca:13u")
        self.assertEqual(resolve("Lakeshow 11U Fuca", "11u Gold")[0],
                         "lakeshow fuca:11u")

    def test_girls_division_does_not_use_boys_override(self):
        team_id, confidence = resolve(CONFIRMED_ALIAS, "14u Girls Gold")
        self.assertNotEqual(team_id, CANONICAL)
        self.assertNotEqual(confidence, "override")


if __name__ == "__main__":
    unittest.main()
