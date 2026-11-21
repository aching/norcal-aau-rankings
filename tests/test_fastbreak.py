import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scrape_fastbreak import parse_games


HTML = """
<h2>Games on Nov 21, 2026</h2>
<div>
  <div
    class="card divisions-and-teams-card card-game"
    data-game-id="469635"
    data-from-id=""
    data-from="division"
  >
    <div class="card-header">
      <div title="2:00 PM PT">2:00 PM PT,</div>
      <div title="The Ultimate Fieldhouse">The Ultimate Fieldhouse</div>
      <div title="1">(1)</div>
    </div>
    <div class="card-body p-0 d-flex">
      <div class="card-team-container">
        <span title="Hoop Famillia (Mayan) 8th/14U"
              data-team-id="280893" data-team-name="Hoop Famillia (Mayan) 8th/14U">Hoop</span>
        <div class="card-team-info">0 - 0</div>
      </div>
      <div class="card-team-container">
        <div class="team-logo"></div>
        <span title="TM Falcons 14u 8th/14U"
              data-team-id="280786" data-team-name="TM Falcons 14u 8th/14U">TM</span>
        <div class="card-team-info">0 - 0</div>
      </div>
    </div>
    <div class="card-info-container"><div>Saturday</div><div>Nov 21</div></div>
    <div class="card-footer-info"><div title="Pool A">Pool A</div></div>
  </div>
  <div class="card divisions-and-teams-card card-game" data-game-id="469638">
    <div class="card-header">
      <div title="2:55 PM PT">2:55 PM PT,</div>
      <div title="A &amp; B High School">A &amp; B High School</div>
      <div title="2">(2)</div>
    </div>
    <div class="card-body">
      <div class="card-team-container">
        <span data-team-id="280786" data-team-name="TM Falcons 14u 8th/14U">TM</span>
        <div class="card-team-info">0 - 0</div>
      </div>
      <div class="card-team-container">
        <div class="card-team-container">
          <span data-team-id="280891" data-team-name="East Bay Athletics 14u Red (Jeremy) 8th/14U">EBA</span>
          <div class="card-team-info">0 - 0</div>
        </div>
      </div>
    </div>
    <div class="card-info-container"><div>Saturday</div><div>Nov 21</div></div>
    <div class="card-footer-info"><div title="Pool A">Pool A</div></div>
  </div>
</div>
"""


class FastbreakParserTests(unittest.TestCase):
    def test_current_layout_preserves_schedule_and_source_ids(self):
        games = parse_games(HTML, "14u Silver Sat Only")
        self.assertEqual(len(games), 2)
        first, second = games
        self.assertEqual(first["game_id"], "469635")
        self.assertEqual(first["time"], "2:00 PM PT")
        self.assertEqual(first["venue"], "The Ultimate Fieldhouse")
        self.assertEqual(first["court"], "1")
        self.assertEqual(first["date"], "Nov 21, 2026")
        self.assertEqual(first["weekday"], "Saturday")
        self.assertEqual(first["pool"], "Pool A")
        self.assertEqual(first["away_team"], "TM Falcons 14u 8th/14U")
        self.assertEqual(first["away_team_id"], "280786")
        self.assertIsNone(first["home_score"])
        self.assertIsNone(first["away_score"])
        self.assertEqual(first["status"], "Scheduled")
        self.assertEqual(second["venue"], "A & B High School")
        self.assertEqual(second["home_team_id"], "280786")
        self.assertEqual(second["away_team"],
                         "East Bay Athletics 14u Red (Jeremy) 8th/14U")


if __name__ == "__main__":
    unittest.main()
