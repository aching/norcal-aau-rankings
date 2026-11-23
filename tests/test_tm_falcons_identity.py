import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from team_identity import event_provider_alias, resolve


CANONICAL = "tm:falcons-14u"


class FalconsIdentityTests(unittest.TestCase):
    def test_black_and_established_fourteen_u_aliases_use_main_identity(self):
        variants = [("TM Falcons Black 14U", "8th Grade (14U) Boys Division"),
                    ("TM Falcons Black", "14u Boys"),
                    ("TM Falcons 14U", "14u Boys Gold"),
                    ("TM Dashawn", "8th Grade Boys Silver / Bronze"),
                    ("TM Basketball", "14u Boys Black"),
                    ("TM Falcons 14u 8th/14U", "14u Silver Sat Only")]
        for name, division in variants:
            with self.subTest(name=name, division=division):
                self.assertEqual(resolve(name, division), (CANONICAL, "override"))

    def test_fastbreak_provider_alias_uses_main_identity(self):
        self.assertEqual(event_provider_alias("11535", 280786), CANONICAL)

    def test_black_thirteen_u_and_red_fourteen_u_stay_separate(self):
        self.assertEqual(resolve("TM Falcons Black", "13u - Boys (White)"),
                         ("tm:falcons-black-13u", "override"))
        self.assertNotEqual(resolve("TM Falcons Red", "14u Boys Open")[0],
                            CANONICAL)
        self.assertNotEqual(resolve("TM Falcons Red", "13u Boys Open")[0],
                            CANONICAL)

    def test_girls_division_does_not_use_boys_override(self):
        team_id, confidence = resolve("TM Falcons Black", "14u Girls Gold")
        self.assertNotEqual(team_id, CANONICAL)
        self.assertNotEqual(confidence, "override")

    def test_prior_bare_falcons_history_remains_on_the_canonical_team(self):
        self.assertEqual(resolve("TM FALCONS (13U)", "13U/7TH GRADE - BOYS")[0],
                         CANONICAL)


if __name__ == "__main__":
    unittest.main()
