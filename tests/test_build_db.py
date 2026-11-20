import contextlib
import io
import sqlite3
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_db


class BuildDbTests(unittest.TestCase):
    @staticmethod
    def create_existing_db(path):
        with contextlib.closing(sqlite3.connect(path)) as con:
            con.execute("CREATE TABLE existing_marker(value TEXT)")
            con.execute("INSERT INTO existing_marker VALUES ('old')")
            con.commit()

    def assert_failed_source_preserves_database(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "aau.db"
            self.create_existing_db(db_path)
            original = db_path.read_bytes()
            filename = "123.json" if source == "ee" else f"{source}_123.json"
            patterns = {
                "data/[0-9]*.json": [],
                "data/bt_*.json": [],
                "data/fb_*.json": [],
            }
            pattern = {
                "ee": "data/[0-9]*.json",
                "bt": "data/bt_*.json",
                "fb": "data/fb_*.json",
            }[source]
            patterns[pattern] = [f"data/{filename}"]

            def fail_after_insert(cur, _path):
                if source == "ee":
                    cur.execute("INSERT INTO ee_tournaments VALUES (?,?,?,?)",
                                ("123", "bad", "bad", "now"))
                elif source == "bt":
                    cur.execute("INSERT INTO bt_events VALUES (?,?,?,?,?)",
                                (123, "bad", "now", "now", "now"))
                else:
                    cur.execute("INSERT INTO fb_events VALUES (?,?,?,?,?,?,?,?)",
                                ("123", "bad", "bad", "now", "now", "bad", 1, "now"))
                raise ValueError("synthetic malformed tournament")

            with (mock.patch.object(build_db.glob, "glob",
                                    side_effect=lambda pattern: patterns[pattern]),
                  mock.patch.object(build_db, f"load_{source}",
                                    side_effect=fail_after_insert),
                  mock.patch.object(build_db.os, "replace", wraps=build_db.os.replace) as replace,
                  mock.patch("scrape_state.mark_processed") as mark_processed,
                  contextlib.redirect_stderr(io.StringIO())):
                with self.assertRaisesRegex(RuntimeError, "database left unchanged"):
                    build_db.main(str(db_path))

            self.assertEqual(db_path.read_bytes(), original)
            replace.assert_not_called()
            mark_processed.assert_not_called()
            self.assertEqual(list(root.glob("*.tmp")), [])

    def test_failed_loads_preserve_database_for_every_source(self):
        for source in ("ee", "bt", "fb"):
            with self.subTest(source=source):
                self.assert_failed_source_preserves_database(source)

    def test_success_replaces_database_and_then_updates_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "aau.db"
            self.create_existing_db(db_path)
            db_path.chmod(0o640)
            side_effects = []

            def load_one(cur, _path):
                cur.execute("INSERT INTO ee_tournaments VALUES (?,?,?,?)",
                            ("123", "event", "Event", "now"))
                return 0, 0

            def fake_glob(pattern):
                return ["data/123.json"] if pattern == "data/[0-9]*.json" else []

            with (mock.patch.object(build_db.glob, "glob", side_effect=fake_glob),
                  mock.patch.object(build_db, "load_ee", side_effect=load_one),
                  mock.patch.object(build_db, "load_state", return_value={}),
                  mock.patch("scrape_state.mark_processed",
                             side_effect=lambda *args: side_effects.append("ledger")) as mark_processed,
                  mock.patch("builtins.print",
                             side_effect=lambda *args, **kwargs: side_effects.append("print"))):
                build_db.main(str(db_path))

            with contextlib.closing(sqlite3.connect(db_path)) as con:
                self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(con.execute(
                    "SELECT tournament_id, title FROM ee_tournaments").fetchall(),
                    [("123", "Event")])
                self.assertEqual(con.execute(
                    "SELECT count(*) FROM sqlite_master WHERE name='existing_marker'").fetchone()[0], 0)
            mark_processed.assert_called_once_with("ee", "123", 0)
            self.assertEqual(side_effects[0], "ledger")
            self.assertEqual(stat.S_IMODE(db_path.stat().st_mode), 0o640)
            self.assertEqual(list(root.glob("*.tmp")), [])

    def test_active_wal_aborts_and_closed_wal_replaces_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "aau.db"
            old_con = sqlite3.connect(db_path)
            self.assertEqual(old_con.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
            old_con.execute("CREATE TABLE existing_marker(value TEXT)")
            old_con.execute("INSERT INTO existing_marker VALUES ('old')")
            old_con.commit()
            self.assertTrue(Path(str(db_path) + "-wal").exists())

            def load_one(cur, _path):
                cur.execute("INSERT INTO ee_tournaments VALUES (?,?,?,?)",
                            ("123", "event", "Event", "now"))
                return 0, 0

            def run_rebuild():
                with (mock.patch.object(build_db.glob, "glob",
                                        side_effect=lambda pattern: ["data/123.json"]
                                        if pattern == "data/[0-9]*.json" else []),
                      mock.patch.object(build_db, "load_ee", side_effect=load_one),
                      mock.patch.object(build_db, "load_state", return_value={}),
                      mock.patch("scrape_state.mark_processed"),
                      contextlib.redirect_stdout(io.StringIO()),
                      contextlib.redirect_stderr(io.StringIO())):
                    build_db.main(str(db_path))

            with self.assertRaisesRegex(RuntimeError, "quiesce|WAL"):
                run_rebuild()
            self.assertEqual(old_con.execute(
                "SELECT value FROM existing_marker").fetchone()[0], "old")
            old_con.close()

            run_rebuild()
            with contextlib.closing(sqlite3.connect(db_path)) as con:
                self.assertEqual(con.execute(
                    "SELECT count(*) FROM ee_tournaments").fetchone()[0], 1)
                self.assertEqual(con.execute(
                    "SELECT count(*) FROM sqlite_master WHERE name='existing_marker'").fetchone()[0], 0)
            for suffix in ("-wal", "-shm"):
                self.assertFalse(Path(str(db_path) + suffix).exists())
            self.assertEqual(list(root.glob("*.tmp")), [])

    def test_empty_corpus_does_not_replace_existing_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "aau.db"
            db_path.write_bytes(b"known-good-database")
            with (mock.patch.object(build_db.glob, "glob", return_value=[]),
                  contextlib.redirect_stderr(io.StringIO())):
                with self.assertRaisesRegex(RuntimeError, "no source tournament files"):
                    build_db.main(str(db_path))
            self.assertEqual(db_path.read_bytes(), b"known-good-database")
            self.assertEqual(list(root.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
