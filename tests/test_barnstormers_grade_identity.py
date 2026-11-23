import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from team_identity import resolve


CANONICAL = "barnstormers:14u"


class BarnstormersGradeIdentityTests(unittest.TestCase):
    def test_bare_eighth_grade_name_merges_into_fourteen_u_team(self):
        for division in ("8th Grade Boys Silver / Bronze",
                         "8th Grade (14U) Boys Division", "Boys 14U Gold"):
            with self.subTest(division=division):
                self.assertEqual(resolve("Barnstormers", division),
                                 (CANONICAL, "override"))

    def test_explicit_fourteen_u_label_keeps_the_main_identity(self):
        self.assertEqual(resolve("BARNSTORMERS (14U)", "14U/8TH Grade Boys")[0],
                         CANONICAL)

    def test_other_cohorts_and_color_labels_stay_separate(self):
        for name, division in (("Barnstormers", "7th Grade Boys"),
                               ("Barnstormers Gold", "12u Boys"),
                               ("Barnstormers Red", "14u Boys")):
            with self.subTest(name=name, division=division):
                self.assertNotEqual(resolve(name, division)[0], CANONICAL)

    def test_girls_division_does_not_use_boys_override(self):
        team_id, confidence = resolve("Barnstormers", "14u Girls Gold")
        self.assertNotEqual(team_id, CANONICAL)
        self.assertNotEqual(confidence, "override")


if __name__ == "__main__":
    unittest.main()
