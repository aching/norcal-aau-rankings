import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_site
from rank_confidence import rate_confidence, render_confidence


def evidence(n, covered, latest="2026-11-22"):
    games = [(f"2026-11-{i:02d}", True) for i in range(1, n + 1)]
    if games:
        games[0] = (latest, True)
    opponents = [f"opp-{i % covered}:14u" if i < covered else None
                 for i in range(n)]
    modeled = {oid for oid in opponents if oid}
    return games, opponents, modeled


class ConfidenceTests(unittest.TestCase):
    def test_empty_or_sparse_sample_is_low(self):
        for n in (0, 4):
            info = rate_confidence(*evidence(n, n), as_of="2026-11-22")
            self.assertEqual(info["level"], "low")
        zero = rate_confidence([], [], set(), "2026-11-22")
        self.assertEqual(zero["coverage"], 0.0)
        self.assertEqual(zero["latest_game"], "")

    def test_showtime_like_nine_games_with_poor_coverage_is_low(self):
        games, opponents, modeled = evidence(9, 4)
        info = rate_confidence(games, opponents, modeled, "2026-11-22")
        self.assertEqual(info["level"], "low")
        self.assertEqual(info["coverage"], 4 / 9)
        self.assertEqual(info["active_games"], 9)

    def test_deep_recent_covered_sample_is_high(self):
        info = rate_confidence(*evidence(12, 12), as_of="2026-11-22")
        self.assertEqual(info["level"], "high")

    def test_recency_and_middle_samples_are_medium(self):
        games, opponents, modeled = evidence(15, 15, "2026-10-01")
        games = [("2026-10-01", g[1]) for g in games]
        self.assertEqual(rate_confidence(games, opponents, modeled,
                                         "2026-11-22")["level"], "medium")
        self.assertEqual(rate_confidence(*evidence(9, 9),
                                         as_of="2026-11-22")["level"], "medium")
        self.assertEqual(rate_confidence(*evidence(15, 9),
                                         as_of="2026-11-22")["level"], "medium")

    def test_modeled_coverage_requires_identity_in_current_model(self):
        games, opponents, modeled = evidence(12, 12)
        info = rate_confidence(games, opponents, set(), "2026-11-22")
        self.assertEqual(info["covered_opponents"], 0)
        self.assertEqual(info["level"], "low")

    def test_renderer_explains_it_is_not_placement_probability(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.json"
            output = io.StringIO()
            game_info = {"rank": 12, "team": "navy 8th:14u", "games": [],
                         "confidence": rate_confidence(*evidence(4, 4),
                                                        as_of="2026-11-22")}
            path.write_text(json.dumps(game_info) + "\n")
            with mock.patch.object(build_site, "Path",
                                   side_effect=lambda v: path if v == "/tmp/games_confidence-test.jsonl" else Path(v)):
                with mock.patch("sys.stderr", new=output):
                    bundles = build_site.game_logs("14u", "confidence-test",
                                                   with_metadata=True)
        info = bundles["navy 8th:14u"]["confidence"]
        html = render_confidence(info)
        self.assertIn("Confidence: Low", html)
        self.assertIn("4 active games", html)
        self.assertIn("4/4 opponents covered (100%)", html)
        self.assertIn("not a probability", html)
        self.assertEqual(render_confidence(None), "")

    def test_team_page_places_confidence_inside_why_section(self):
        row = {"rank": 12, "team": "navy 8th:14u", "log": [], "wl": "4-0",
               "tier": "gold", "score": 0.06, "titles": 0, "titlelist": [],
               "ppg": None, "sos": 0.08, "why": ["Form 4-0 overall"],
               "confidence": rate_confidence(*evidence(4, 4),
                                              as_of="2026-11-22")}
        html = build_site.team_page("14u", "14U", row, "2026-11-22",
                                    {"navy 8th:14u": "teams/14u/navy.html"}, {})
        self.assertIn("Confidence: Low", html)
        self.assertLess(html.index("<h2>Why #12</h2>"),
                        html.index("Confidence: Low"))
        self.assertLess(html.index("Confidence: Low"),
                        html.index("Form 4-0 overall"))


if __name__ == "__main__":
    unittest.main()
