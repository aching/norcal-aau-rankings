import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_site
from profile_aliases import profile_aliases, render_aliases


class ProfileAliasTests(unittest.TestCase):
    def test_database_aliases_are_scoped_to_canonical_identity(self):
        con = sqlite3.connect(":memory:")
        self.addCleanup(con.close)
        con.execute("CREATE TABLE team_names (raw_name TEXT, division_hint TEXT, team_id TEXT)")
        con.executemany(
            "INSERT INTO team_names VALUES (?, ?, ?)",
            [("LGSR", "14u Black", "lgsr:14u"),
             ("LGSR 8th/14U", "14u Gold", "lgsr:14u"),
             ("lgsr", "14u Gold", "lgsr:14u"),
             ("LGSR Warriors & Sons <b>", "14u Gold", "lgsr:14u"),
             ("LGSR", "14u Girls", "lgsr:14u girls")])
        aliases = profile_aliases(con)
        self.assertEqual(aliases["lgsr:14u"][:2], ["LGSR", "LGSR 8th/14U"])
        self.assertEqual(len(aliases["lgsr:14u"]), 3)
        self.assertNotIn("lgsr:14u girls", aliases)

    def test_collapsed_renderer_sorts_dedupes_and_escapes(self):
        html = render_aliases(["Zebra <b>", "alpha & beta", "ZEBRA <b>"])
        self.assertIn("Known aliases (2)", html)
        self.assertIn("<details", html)
        self.assertNotIn("<details open", html)
        self.assertIn("Zebra &lt;b&gt;", html)
        self.assertIn("alpha &amp; beta", html)
        self.assertNotIn("Zebra <b>", html)

    def test_single_source_name_has_no_alias_section(self):
        self.assertEqual(render_aliases(["Only Name"]), "")
        self.assertEqual(render_aliases([]), "")
        self.assertEqual(render_aliases(None), "")

    def test_team_page_places_aliases_below_the_profile_header(self):
        row = {"team": "lgsr:14u", "log": [], "wl": "0-0", "tier": "gold",
               "rank": 0, "score": 0.0, "titles": 0, "titlelist": [],
               "ppg": None, "sos": 0.0, "why": []}
        html = build_site.team_page(
            "14u", "14U", row, "2026-11-22", {"lgsr:14u": "teams/14u/lgsr-14u.html"},
            {}, aliases=["LGSR", "LGSR 8th/14U"])
        self.assertIn("Known aliases (2)", html)
        self.assertLess(html.index("detail-head"), html.index("Known aliases"))
        self.assertLess(html.index("Known aliases"), html.index("Full record"))


if __name__ == "__main__":
    unittest.main()
