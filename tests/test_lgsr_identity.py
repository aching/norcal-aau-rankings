import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from team_identity import resolve


CONFIRMED_ALIAS = "LGSR 8th/14U"
CANONICAL = "lgsr:14u"


class LGSRIdentityTests(unittest.TestCase):
    def test_confirmed_fastbreak_alias_uses_bare_lgsr_identity(self):
        team_id, confidence = resolve(CONFIRMED_ALIAS, "14u Gold")
        self.assertEqual(team_id, CANONICAL)
        self.assertEqual(confidence, "override")

    def test_bare_lgsr_remains_the_same_identity(self):
        self.assertEqual(resolve("LGSR", "14u Black Division")[0], CANONICAL)

    def test_other_lgsr_cohorts_stay_separate(self):
        other = resolve("LGSR Academy Elite - Jared", "Boys 7th")[0]
        self.assertEqual(other, "lgsr academy elite jared:7th")

    def test_girls_division_does_not_use_boys_override(self):
        team_id, confidence = resolve(CONFIRMED_ALIAS, "14u Girls Gold")
        self.assertNotEqual(team_id, CANONICAL)
        self.assertNotEqual(confidence, "override")


if __name__ == "__main__":
    unittest.main()
