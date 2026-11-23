import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from team_identity import resolve


CANONICAL = "all in elite:14u"


class AllInEliteIdentityTests(unittest.TestCase):
    def test_confirmed_uaa_spellings_merge_to_main_identity(self):
        variants = [("All In Elite UAA 14u", "Boys-14u National"),
                    ("All-In Elite UAA", "14U/8th Grade Gold"),
                    ("all in elite uaa", "Boys 8th National")]
        for name, division in variants:
            with self.subTest(name=name, division=division):
                self.assertEqual(resolve(name, division),
                                 (CANONICAL, "override"))

    def test_existing_all_in_name_keeps_main_identity(self):
        self.assertEqual(resolve("ALL IN ELITE 14U", "Boys-14u National")[0],
                         CANONICAL)

    def test_thirteen_u_with_same_label_does_not_merge(self):
        self.assertEqual(resolve("All In Elite UAA", "13u Division 1")[0],
                         "all in elite uaa:13u")
        self.assertEqual(resolve("All In Elite UAA 13u", "Boys-13u National")[0],
                         "all in elite uaa:13u")

    def test_extra_sibling_roster_words_do_not_trigger_exact_merge(self):
        for name in ("All In Elite UAA Black", "All In Elite UAA Select"):
            team_id, confidence = resolve(name, "Boys-14u National")
            self.assertNotEqual(team_id, CANONICAL)
            self.assertNotEqual(confidence, "override")

    def test_girls_division_does_not_use_boys_override(self):
        team_id, confidence = resolve("All-In Elite UAA", "Girls 14U")
        self.assertNotEqual(team_id, CANONICAL)
        self.assertNotEqual(confidence, "override")


if __name__ == "__main__":
    unittest.main()
