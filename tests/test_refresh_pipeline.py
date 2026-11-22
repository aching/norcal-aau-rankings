import contextlib
import io
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import refresh
import storage


class RefreshPipelineTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.events_lock = threading.Lock()
        self.patchers = []

        def note(label):
            with self.events_lock:
                self.events.append(label)

        self.note = note
        for target in ("ee_watermark", "bt_watermark"):
            patcher = mock.patch.object(
                refresh, target, side_effect=lambda label=target: note(label))
            self.patchers.append(patcher)
            patcher.start()
        for target, label in (("build_db.main", "db"),
                              ("refresh.show_status", "status")):
            patcher = mock.patch(
                target, side_effect=lambda *args, _label=label, **kwargs: note(_label))
            self.patchers.append(patcher)
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()

    def source_pair(self, rendezvous=None, ee_error=None):
        def fake_ee(since, today, interactive=True):
            self.note("ee:start")
            if rendezvous:
                rendezvous.wait(timeout=2)
            if ee_error:
                raise ee_error
            refresh.ee_watermark()
            self.note("ee:end")

        def fake_bt(interactive=True, out_dir=None):
            self.note("bt:start")
            if rendezvous:
                rendezvous.wait(timeout=2)
            if rendezvous:
                # Keep BT unfinished briefly after EE returns so the test also
                # exercises waiting for the second branch, not just the first.
                time.sleep(0.02)
            refresh.bt_watermark()
            self.note("bt:end")

        return (mock.patch.object(refresh, "_run_ee", side_effect=fake_ee),
                mock.patch.object(refresh, "_run_bt", side_effect=fake_bt))

    def test_sources_overlap_and_db_waits_for_both(self):
        rendezvous = threading.Barrier(2)
        ee_patch, bt_patch = self.source_pair(rendezvous)
        with ee_patch as ee, bt_patch as bt, contextlib.redirect_stdout(io.StringIO()):
            refresh._run_pipeline(since="2026-05-30")

        self.assertIn("ee:start", self.events)
        self.assertIn("bt:start", self.events)
        self.assertLess(self.events.index("ee:start"), self.events.index("ee_watermark"))
        self.assertLess(self.events.index("ee_watermark"), self.events.index("ee:end"))
        self.assertLess(self.events.index("bt:start"), self.events.index("bt_watermark"))
        self.assertLess(self.events.index("bt_watermark"), self.events.index("bt:end"))
        for event in ("ee:end", "bt:end", "ee_watermark", "bt_watermark"):
            self.assertLess(self.events.index(event), self.events.index("db"))
        self.assertLess(self.events.index("db"), self.events.index("status"))
        self.assertEqual(self.events.count("ee_watermark"), 1)
        self.assertEqual(self.events.count("bt_watermark"), 1)
        self.assertFalse(ee.call_args[0][2])
        self.assertFalse(bt.call_args[0][0])


    def test_source_failure_waits_for_other_branch_and_skips_db(self):
        rendezvous = threading.Barrier(2)
        ee_patch, bt_patch = self.source_pair(rendezvous, ValueError("synthetic EE failure"))
        with ee_patch, bt_patch, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "synthetic EE failure"):
                refresh._run_pipeline()

        self.assertIn("bt:end", self.events)
        self.assertNotIn("db", self.events)
        self.assertNotIn("ee_watermark", self.events)
        self.assertIn("bt_watermark", self.events)

    def test_dual_source_failures_are_both_reported(self):
        rendezvous = threading.Barrier(2)

        def fail_ee(*args):
            rendezvous.wait(timeout=2)
            raise ValueError("EE broke")

        def fail_bt(*args):
            rendezvous.wait(timeout=2)
            raise RuntimeError("BT broke")

        with (mock.patch.object(refresh, "_run_ee", side_effect=fail_ee),
              mock.patch.object(refresh, "_run_bt", side_effect=fail_bt),
              contextlib.redirect_stdout(io.StringIO())):
            with self.assertRaises(RuntimeError) as raised:
                refresh._run_pipeline()
        self.assertIn("EE broke", str(raised.exception))
        self.assertIn("BT broke", str(raised.exception))
        self.assertNotIn("db", self.events)

    def test_no_db_computes_each_source_watermark_in_its_branch(self):
        ee_patch, bt_patch = self.source_pair()
        with ee_patch, bt_patch, contextlib.redirect_stdout(io.StringIO()):
            refresh._run_pipeline(do_db=False)

        self.assertEqual(self.events.count("ee_watermark"), 1)
        self.assertEqual(self.events.count("bt_watermark"), 1)
        self.assertNotIn("db", self.events)

    def test_db_adds_only_unselected_source_watermarks(self):
        ee_patch, bt_patch = self.source_pair()
        with ee_patch as ee, bt_patch, contextlib.redirect_stdout(io.StringIO()):
            refresh._run_pipeline(do_ee=False)

        ee.assert_not_called()
        self.assertEqual(self.events.count("ee_watermark"), 1)
        self.assertEqual(self.events.count("bt_watermark"), 1)
        self.assertLess(self.events.index("bt_watermark"), self.events.index("db"))

    def test_global_refresh_lock_excludes_overlap_and_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "refresh.lock"
            with (mock.patch.object(refresh, "RUN_LOCK_PATH", lock_path),
                  mock.patch.object(refresh, "_run_pipeline") as pipeline):
                with storage.file_lock(lock_path, blocking=False):
                    with self.assertRaises(storage.LockUnavailable):
                        refresh.run_pipeline()
                pipeline.assert_not_called()
                refresh.run_pipeline(do_bt=False, since="2026-05-30")
                pipeline.assert_called_once_with(
                    do_ee=True, do_bt=False, do_db=True, since="2026-05-30")

    def test_run_command_and_legacy_flags_parse_strictly(self):
        with mock.patch.object(refresh, "run_pipeline") as pipeline:
            self.assertEqual(refresh.main([
                "run", "--no-ee", "--no-db", "--since", "2026-01-31"]), 0)
            pipeline.assert_called_once_with(
                do_ee=False, do_bt=True, do_db=False, since="2026-01-31")

            pipeline.reset_mock()
            self.assertEqual(refresh.main(["--no-bt", "--since=2026-02-01"]), 0)
            pipeline.assert_called_once_with(
                do_ee=True, do_bt=False, do_db=True, since="2026-02-01")

            pipeline.reset_mock()
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    refresh.main(["run", "--not-a-real-flag"])
            self.assertEqual(error.exception.code, 2)
            pipeline.assert_not_called()

    def test_main_reports_an_existing_refresh_without_traceback(self):
        with (mock.patch.object(refresh, "run_pipeline",
                                side_effect=storage.LockUnavailable("held")),
              contextlib.redirect_stderr(io.StringIO()) as stderr):
            self.assertEqual(refresh.main(["run"]), 2)
        self.assertIn("already running", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
