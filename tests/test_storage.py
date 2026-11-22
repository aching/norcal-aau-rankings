import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import storage


class StorageTests(unittest.TestCase):
    def test_atomic_json_write_preserves_existing_file_on_encode_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("known-good")
            with self.assertRaises(TypeError):
                storage.atomic_write_json(path, {"bad": object()})
            self.assertEqual(path.read_text(), "known-good")
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    def test_atomic_json_replaces_complete_document_and_preserves_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "event.json"
            path.write_text('{"old": true}')
            path.chmod(0o640)
            storage.atomic_write_json(path, {"new": [1, 2, 3]})
            self.assertEqual(json.loads(path.read_text()), {"new": [1, 2, 3]})
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    def test_new_json_file_uses_public_corpus_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "new.json"
            storage.atomic_write_json(path, {"new": True})
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_nonblocking_lock_rejects_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "refresh.lock"
            with storage.file_lock(lock_path, blocking=False):
                with self.assertRaises(storage.LockUnavailable):
                    with storage.file_lock(lock_path, blocking=False):
                        self.fail("overlapping lock acquisition should not succeed")

    def test_failed_lock_acquisition_can_be_retried_after_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "refresh.lock"
            with storage.file_lock(lock_path, blocking=False):
                pass
            with storage.file_lock(lock_path, blocking=False):
                pass


if __name__ == "__main__":
    unittest.main()
