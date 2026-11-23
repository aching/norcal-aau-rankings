import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_clubs


class ClubCleanupTests(unittest.TestCase):
    def test_retired_generated_club_pages_are_removed_before_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / "scripts"
            scripts.mkdir()
            out = root / "site" / "clubs"
            out.mkdir(parents=True)
            (root / "data").mkdir()
            retired = out / "barnstomers.html"
            retired.write_text("stale generated club page")
            asset = out / "keep.txt"
            asset.write_text("not an HTML page")
            with (mock.patch.object(build_clubs, "HERE", scripts),
                  mock.patch.object(build_clubs, "OUT", out),
                  mock.patch.object(build_clubs, "all_pages_map", return_value={}),
                  mock.patch.object(build_clubs, "load_boards", return_value={})):
                build_clubs.main()
            self.assertFalse(retired.exists())
            self.assertEqual(asset.read_text(), "not an HTML page")
            self.assertTrue((root / "site" / "clubs.html").exists())
            self.assertEqual((root / "data" / "club_slugs.json").read_text(), "{}")


if __name__ == "__main__":
    unittest.main()
