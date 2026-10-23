'''
streamem: SQLite manifest of per-file progress
'''

# Import external dependencies
import sqlite3, threading
from pathlib import Path
from typing import Literal, get_args

# Import internal streamem objects
from streamem.utils.empiar import RemoteFile

# Status: lifecycle of one file
Status = Literal['pending', 'running', 'done', 'failed']

# Manifest: thread-safe progress table, one row per remote file
class Manifest:
    # __init__: open the database, optionally putting interrupted files back in the queue
    def __init__(self, path: Path, *, recover: bool = True) -> None:
        # one shared connection behind a lock, every write is tiny
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.execute(
                'CREATE TABLE IF NOT EXISTS files '
                '(sub TEXT, name TEXT, size INTEGER, status TEXT NOT NULL, error TEXT, PRIMARY KEY (sub, name))'
            )
            # a row still running means the last run died mid-file, but a reader must not touch a live run
            if recover:
                self._db.execute('UPDATE files SET status = ? WHERE status = ?', ('pending', 'running'))

    # add: register files of a sub-dataset, existing rows keep their status
    def add(self, sub: str, files: list[RemoteFile]) -> None:
        with self._lock, self._db:
            self._db.executemany(
                'INSERT OR IGNORE INTO files (sub, name, size, status) VALUES (?, ?, ?, ?)',
                [(sub, f.name, f.size, 'pending') for f in files],
            )

    # claim: atomically take the next pending file and mark it running
    def claim(self) -> tuple[str, str] | None:
        with self._lock, self._db:
            row = self._db.execute(
                'SELECT sub, name FROM files WHERE status = ? ORDER BY rowid LIMIT 1', ('pending',)
            ).fetchone()
            if row is not None:
                self._db.execute('UPDATE files SET status = ? WHERE sub = ? AND name = ?', ('running', *row))
        return row

    # finish: record the outcome of a claimed file
    def finish(self, sub: str, name: str, status: Status, error: str | None = None) -> None:
        with self._lock, self._db:
            self._db.execute(
                'UPDATE files SET status = ?, error = ? WHERE sub = ? AND name = ?', (status, error, sub, name)
            )

    # retry_failed: put failed files back in the queue
    def retry_failed(self) -> None:
        with self._lock, self._db:
            self._db.execute('UPDATE files SET status = ?, error = NULL WHERE status = ?', ('pending', 'failed'))

    # counts: number of files in each status, zero when absent
    def counts(self) -> dict[str, int]:
        with self._lock:
            found = dict(self._db.execute('SELECT status, COUNT(*) FROM files GROUP BY status').fetchall())
        return {status: found.get(status, 0) for status in get_args(Status)}

    # summary: per sub-dataset (file count, bytes) for every status
    def summary(self) -> dict[str, dict[str, tuple[int, int]]]:
        with self._lock:
            rows = self._db.execute(
                'SELECT sub, status, COUNT(*), COALESCE(SUM(size), 0) FROM files GROUP BY sub, status'
            ).fetchall()
        out: dict[str, dict[str, tuple[int, int]]] = {}
        for sub, status, n, size in rows:
            out.setdefault(sub, {s: (0, 0) for s in get_args(Status)})[status] = (n, size)
        return out

    # failures: (sub-dataset, file, error) for every failed file
    def failures(self) -> list[tuple[str, str, str | None]]:
        with self._lock:
            return self._db.execute(
                'SELECT sub, name, error FROM files WHERE status = ? ORDER BY rowid', ('failed',)
            ).fetchall()
