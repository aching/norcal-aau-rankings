import json
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_organizers import upcoming_item
from html_utils import esc, external_link, json_for_script, safe_url
from team_identity import resolve


class TagProbe(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class HtmlUtilsTests(unittest.TestCase):
    def test_inline_json_cannot_terminate_script_and_round_trips(self):
        payload = "</script><script>alert(1)</script>&\u2028"
        team_id, _ = resolve(payload, "14U Boys")
        value = [{"team": team_id, "titlelist": [["champ " + payload, "", ""]]}]
        encoded = json_for_script(value)
        self.assertNotIn("</script>", encoded)
        self.assertNotIn("<", encoded)
        self.assertNotIn(">", encoded)
        self.assertNotIn("&", encoded)
        self.assertEqual(json.loads(encoded), value)

        probe = TagProbe()
        probe.feed("<script>const DATA = " + encoded + ";</script>")
        self.assertEqual([tag for tag, _ in probe.tags], ["script"])

    def test_quotes_cannot_create_new_html_attributes(self):
        url = 'https://example.test/event" onmouseover="alert(1)'
        probe = TagProbe()
        probe.feed(external_link(url, "Event <One>"))
        self.assertEqual(len(probe.tags), 1)
        tag, attrs = probe.tags[0]
        self.assertEqual(tag, "a")
        self.assertNotIn("onmouseover", attrs)
        self.assertIn("onmouseover=", attrs["href"])

    def test_esc_handles_single_and_double_quotes(self):
        self.assertEqual(esc("\"'&<>"), "&quot;&#x27;&amp;&lt;&gt;")

    def test_external_url_allowlist(self):
        self.assertEqual(safe_url("HTTPS://example.test/a"), "HTTPS://example.test/a")
        self.assertEqual(safe_url("http://example.test"), "http://example.test")
        for url in ("javascript:alert(1)", "data:text/html,<b>x</b>",
                    "//example.test/path", "/relative/path", "",
                    "https://", "https://exa\nmple.test"):
            with self.subTest(url=url):
                self.assertEqual(safe_url(url), "")

    def test_external_link_falls_back_to_text_for_unsafe_url(self):
        rendered = external_link("javascript:alert(1)", "Event <One>")
        self.assertEqual(rendered, "Event &lt;One&gt;")
        self.assertNotIn("<a", rendered)

    def test_organizer_item_does_not_link_unsafe_url(self):
        rendered = upcoming_item({
            "date": "2026-12-01", "url": "javascript:alert(1)",
            "name": "Event <One>", "src": "BT", "status": "announced",
        })
        self.assertNotIn("<a", rendered)
        self.assertIn("Event &lt;One&gt;", rendered)


if __name__ == "__main__":
    unittest.main()
