import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_reports import refresh_rankings
from rank_teams import DEFAULT_WINDOW_DAYS, apply_circuit_tier, tier_of


class CircuitTierTests(unittest.TestCase):
    def test_default_form_window_is_one_year(self):
        self.assertEqual(DEFAULT_WINDOW_DAYS, 365)

    def game(self, event_id):
        return ("2026-05-17", True, tier_of("open")[1], "open", event_id,
                "8th Grade Boys (2030)", "Oakland Soldiers Camo", "Rose City Rebels",
                57, 30, "Pool B", {"dt": 4903888, "gid": 38139016})

    def test_verified_circuit_game_becomes_national_without_mutation(self):
        original = self.game("261349")
        changed = apply_circuit_tier([original], {"261349"})[0]
        self.assertEqual(changed[2], tier_of("national")[1])
        self.assertEqual(changed[3], "national")
        self.assertEqual(changed[2] / original[2], 2.0)
        self.assertEqual(changed[4:], original[4:])
        self.assertEqual(original[2:4], (tier_of("open")[1], "open"))

    def test_non_circuit_and_house_events_keep_their_existing_tier(self):
        for event_id in ("264028", "275133", "999999"):
            original = self.game(event_id)
            changed = apply_circuit_tier([original], {"261349"})
            self.assertEqual(changed, [original])

    def test_string_id_boundary_does_not_drop_numeric_event_ids(self):
        changed = apply_circuit_tier([self.game(261349)], {"261349"})[0]
        self.assertEqual(changed[3], "national")
        self.assertEqual(changed[4], 261349)

    def test_bt_event_with_same_numeric_id_does_not_inherit_ee_tier(self):
        original = list(self.game("261349"))
        original[11] = {"source": "bt", "divid": 1, "mid": 2}
        original = tuple(original)
        self.assertEqual(apply_circuit_tier([original], {"261349"}), [original])

    def test_report_refresh_synchronizes_json_and_markdown(self):
        calls = []

        def fake_run(command, check, stdout):
            calls.append(command)
            return mock.Mock(stdout=(b'{"rank":11,"team":"camo","games":[]}\n'
                                     if "--dump-games" in command else b"# ranking\n"))

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("build_reports.subprocess.run", side_effect=fake_run):
                refresh_rankings({"14u": ("14U/8th", "14u,8th")}, tmp)
            self.assertEqual((Path(tmp) / "games_14u.jsonl").read_text(),
                             '{"rank":11,"team":"camo","games":[]}\n')
            self.assertEqual((Path(tmp) / "rankings" / "14u.md").read_text(),
                             "# ranking\n")
        self.assertEqual(len(calls), 2)
        for command in calls:
            self.assertEqual(command[command.index("--level") + 1], "14u,8th")
            self.assertEqual(command[command.index("--last") + 1], "15")
        self.assertIn("--dump-games", calls[0])
        self.assertNotIn("--dump-games", calls[1])


if __name__ == "__main__":
    unittest.main()
