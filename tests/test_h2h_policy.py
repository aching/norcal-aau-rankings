import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from rank_teams import h2h_reorder


def rows(scores):
    return [(score, 0.0, 0.0, len(scores), 0, f"team-{i}:14u")
            for i, score in enumerate(scores)]


class HeadToHeadPolicyTests(unittest.TestCase):
    def test_far_head_to_head_win_does_not_swap_positions(self):
        ranked = rows([0.200 - i * 0.001 for i in range(19)])
        ranked[0] = ranked[0][:5] + ("all in elite:14u",)
        ranked[17] = ranked[17][:5] + ("showtime xvi 2031:14u",)
        wins = {("showtime xvi 2031:14u", "all in elite:14u"): 1}
        result, swaps = h2h_reorder(ranked, wins, 0.01)
        self.assertEqual(result, ranked)
        self.assertEqual(swaps, [])

    def test_close_score_win_can_move_one_place(self):
        ranked = rows([0.100, 0.099, 0.080])
        wins = {("team-1:14u", "team-0:14u"): 1}
        result, swaps = h2h_reorder(ranked, wins, 0.01)
        self.assertEqual(result[0][5], "team-1:14u")
        self.assertEqual(result[1][5], "team-0:14u")
        self.assertEqual(swaps, [("team-1:14u", "team-0:14u")])

    def test_more_than_two_places_is_disallowed_even_when_scores_close(self):
        ranked = rows([0.100, 0.099, 0.098, 0.097, 0.080])
        wins = {("team-3:14u", "team-0:14u"): 1}
        result, swaps = h2h_reorder(ranked, wins, 0.01)
        self.assertEqual(result, ranked)
        self.assertEqual(swaps, [])

    def test_no_sos_diagnostic_completes_without_ranked_win_override(self):
        result = subprocess.run(
            [sys.executable, "scripts/rank_teams.py", "--level", "14u",
             "--last", "3", "--no-sos"],
            cwd=ROOT, text=True, capture_output=True, timeout=120, check=False)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        self.assertNotIn("NameError", result.stderr)
        self.assertIn("# ranking:", result.stdout)


if __name__ == "__main__":
    unittest.main()
