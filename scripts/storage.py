"""Small stdlib-only helpers for atomic JSON snapshots and file locks."""
import fcntl
import json
import os
import stat
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path


class LockUnavailable(RuntimeError):
    """Raised when a non-blocking file lock is already held."""


_THREAD_LOCKS = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock(path):
    key = str(Path(path).resolve())
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.Lock())


@contextmanager
def file_lock(path, *, blocking=True):
    """Hold one advisory lock across threads and processes on this host.

    The lock file is persistent: unlinking a lock file while another process
    waits on its inode would allow a third process to lock a different inode.
    """
    path = Path(path)
    thread_lock = _thread_lock(path)
    if not thread_lock.acquire(blocking=blocking):
        raise LockUnavailable(f"lock already held: {path}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            try:
                fcntl.flock(handle.fileno(), operation)
            except BlockingIOError as exc:
                raise LockUnavailable(f"lock already held: {path}") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        thread_lock.release()


def _fsync_directory(path):
    """Persist a directory entry where directory fsync is supported."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        try:
            os.fsync(fd)
        except OSError:
            # Some filesystems/platforms do not support syncing directories.
            pass
    finally:
        os.close(fd)


def atomic_write_json(path, payload, *, indent=2):
    """Atomically replace path with a durable, complete JSON document.

    Readers see either the previous or new complete document. Existing modes
    are preserved; new public-corpus files use the conventional 0644 mode.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        mode = 0o644

    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=indent)
            handle.flush()
            os.chmod(tmp_path, mode)
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        _fsync_directory(path.parent)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
