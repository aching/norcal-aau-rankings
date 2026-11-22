import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import scrape_state


class ScrapeStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state_path = root / "scrape_state.json"
        for name, value in (("STATE_PATH", self.state_path),
                            ("LOCK_PATH", root / "scrape_state.lock")):
            patcher = mock.patch.object(scrape_state, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_concurrent_writers_do_not_lose_events(self):
        def write_event(i):
            source = "ee" if i % 2 else "bt"
            scrape_state.record_event(source, i, "downloaded", games=i)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write_event, range(40)))

        state = json.loads(self.state_path.read_text())
        self.assertEqual(len(state["events"]), 40)
        for i in range(40):
            source = "ee" if i % 2 else "bt"
            event = state["events"][f"{source}:{i}"]
            self.assertEqual(event["games"], i)
            self.assertEqual(event["attempts"], 1)

    def test_concurrent_run_and_watermark_updates_share_one_transaction(self):
        def write_run(i):
            scrape_state.record("ee" if i % 2 else "bt", f"job-{i}")

        def write_watermark(i):
            scrape_state.update_content("ee" if i % 2 else "bt",
                                        {"last_event_id": i})

        with ThreadPoolExecutor(max_workers=8) as pool:
            jobs = [pool.submit(write_run, i) for i in range(20)]
            jobs += [pool.submit(write_watermark, i) for i in range(20)]
            for job in jobs:
                job.result()

        # Publish known final values after the concurrent writers finish;
        # lock acquisition order among the workers is intentionally unspecified.
        scrape_state.update_content("ee", {"last_event_id": 99})
        scrape_state.update_content("bt", {"last_event_id": 98})
        state = json.loads(self.state_path.read_text())
        self.assertEqual(len(state["runs"]), 20)
        self.assertEqual(state["content"]["ee"]["last_event_id"], 99)
        self.assertEqual(state["content"]["bt"]["last_event_id"], 98)

    def test_pending_seed_is_attempt_free_and_preserves_existing_progress(self):
        scrape_state.record_event("ee", "existing", "failed")
        original = scrape_state.load()["events"]["ee:existing"].copy()
        self.assertIsNone(scrape_state.seed_pending_event("ee", "existing"))
        self.assertEqual(scrape_state.load()["events"]["ee:existing"], original)

        seeded = scrape_state.seed_pending_event("ee", "new", name="New event")
        self.assertEqual(seeded["attempts"], 0)
        self.assertNotIn("last_attempt", seeded)
        self.assertEqual(seeded["next_retry"], "")

    def test_batch_processed_rows_use_one_atomic_write(self):
        rows = [("ee", str(i), i) for i in range(10)]
        with mock.patch.object(scrape_state, "atomic_write_json",
                               wraps=scrape_state.atomic_write_json) as write:
            scrape_state.mark_processed_many(rows)
        write.assert_called_once()
        events = scrape_state.load()["events"]
        self.assertEqual([events[f"ee:{i}"]["games"] for i in range(10)],
                         list(range(10)))

    def test_parallel_progress_mode_never_uses_carriage_returns(self):
        stdout = mock.Mock()
        stdout.isatty.return_value = True
        with mock.patch.object(scrape_state.sys, "stdout", stdout):
            progress = scrape_state.Progress(1, interactive=False)
            progress.render("item")
            progress.finish("done")
        writes = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertNotIn("\r", writes)
        self.assertNotIn("\x1b[K", writes)

    def test_failed_transaction_does_not_publish_partial_update(self):
        scrape_state.record("ee", "before")
        original = self.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "synthetic"):
            with scrape_state.edit_state() as state:
                state["runs"].clear()
                raise ValueError("synthetic")
        self.assertEqual(self.state_path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
