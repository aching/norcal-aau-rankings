import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import list_events


class FakeResponse:
    def __init__(self, body):
        self.body = body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.body


class FakeOpener:
    def __init__(self):
        self.calls = []
        self.addheaders = []
        self.responses = iter([
            FakeResponse("<script>tokenValue: 'test-token'</script>"),
            FakeResponse(json.dumps({"Results": [], "Total": 0})),
        ])

    def open(self, request, **kwargs):
        self.calls.append((request, kwargs))
        return next(self.responses)


class RefreshHardeningTests(unittest.TestCase):
    def test_every_discovery_request_has_timeout(self):
        opener = FakeOpener()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "events.json"
            with (mock.patch.object(list_events.urllib.request,
                                    "build_opener", return_value=opener),
                  mock.patch.object(list_events, "record"),
                  contextlib.redirect_stdout(io.StringIO())):
                list_events.main(out_name=str(output))
            self.assertEqual(json.loads(output.read_text()), [])
        self.assertEqual(len(opener.calls), 2)
        for _, kwargs in opener.calls:
            self.assertEqual(kwargs.get("timeout"), 30)

    def test_pages_actions_are_pinned_to_full_commit_shas(self):
        workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text()
        uses = re.findall(r"uses:\s+([\w/-]+)@([^\s#]+)", workflow)
        self.assertEqual(len(uses), 4)
        for action, revision in uses:
            with self.subTest(action=action):
                self.assertRegex(revision, r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
