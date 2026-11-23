import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from team_identity import resolve


CONFIRMED_ALIAS = "NBBA 8th UA (K. Winter) 8th/14U"
CANONICAL = "nbba:14u"


class NBBAIdentityTests(unittest.TestCase):
    def test_confirmed_fastbreak_alias_uses_bare_nbba_identity(self):
        team_id, confidence = resolve(CONFIRMED_ALIAS, "14u Gold")
        self.assertEqual(team_id, CANONICAL)
        self.assertEqual(confidence, "override")

    def test_bare_nbba_remains_the_same_identity(self):
        self.assertEqual(resolve("NBBA", "14u Gold")[0], CANONICAL)

    def test_other_nbba_cohorts_and_unconfirmed_labels_stay_separate(self):
        other_age = resolve("NBBA 7th UA (K. Winter)", "13u Invite Only")[0]
        other_label = resolve("NBBA UA 8th (K. Winter) 8th/14U", "14u Gold")[0]
        self.assertNotEqual(other_age, CANONICAL)
        self.assertEqual(other_label, "nbba ua 8th k winter 8th:14u")

    def test_girls_division_does_not_use_boys_override(self):
        team_id, confidence = resolve(CONFIRMED_ALIAS, "14u Girls Gold")
        self.assertNotEqual(team_id, CANONICAL)
        self.assertNotEqual(confidence, "override")


if __name__ == "__main__":
    unittest.main()
