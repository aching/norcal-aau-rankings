import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from team_identity import resolve


MISSPELLED = "Barnstomers 14U"
CANONICAL = "barnstormers:14u"


class BarnstormersIdentityTests(unittest.TestCase):
    def test_confirmed_fourteen_u_misspelling_is_merged(self):
        team_id, confidence = resolve(MISSPELLED, "8th Grade (14U) Boys Division")
        self.assertEqual(team_id, CANONICAL)
        self.assertEqual(confidence, "override")

    def test_correct_spelling_keeps_the_same_canonical_identity(self):
        self.assertEqual(resolve("BARNSTORMERS (14U)", "14u Boys Red")[0], CANONICAL)

    def test_other_cohorts_stay_separate_and_bare_eighth_grade_merges(self):
        self.assertEqual(resolve("Barnstomers 10U", "4th Grade Boys")[0],
                         "barnstomers:10u")
        self.assertEqual(resolve("Barnstomers 13U", "13u Boys")[0],
                         "barnstomers:13u")
        # Latest user confirmation: bare 8th Barnstormers is the same 14U squad.
        self.assertEqual(resolve("Barnstormers", "8th Grade Boys Silver")[0],
                         "barnstormers:14u")

    def test_girls_division_does_not_use_boys_override(self):
        team_id, confidence = resolve(MISSPELLED, "14u Girls Red")
        self.assertNotEqual(team_id, CANONICAL)
        self.assertNotEqual(confidence, "override")


if __name__ == "__main__":
    unittest.main()
