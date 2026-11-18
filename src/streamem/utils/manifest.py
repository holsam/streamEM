'''
streamem: SQLite manifest of per-file progress
'''

# Import external dependencies
import sqlite3, threading
from pathlib import Path
from time import time
from typing import Literal, get_args

# Import internal streamem objects
from streamem.utils.empiar import RemoteFile


# Status: lifecycle of one file
Status = Literal['pending', 'running', 'done', 'failed']

# Stage: where a file failed, downloading (fetch) or running the command (exec)
Stage = Literal['fetch', 'exec']

# COLUMNS: columns added after v0.2.x
COLUMNS = {'stage': 'TEXT', 'started': 'REAL', 'finished': 'REAL', 'attempts': 'INTEGER NOT NULL DEFAULT 0'}

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
                '(sub TEXT, name TEXT, size INTEGER, status TEXT NOT NULL, error TEXT, pair TEXT, PRIMARY KEY (sub, name))'
            )
            have = {row[1] for row in self._db.execute('PRAGMA table_info(files)')}
            for column, declaration in COLUMNS.items():
                if column not in have:
                    self._db.execute(f'ALTER TABLE files ADD COLUMN {column} {declaration}')
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

    # add_pairs: register file pairs under the primary's name, size is the pair total, existing rows keep their status
    def add_pairs(self, sub: str, pairs: list[tuple[RemoteFile, RemoteFile]]) -> None:
        with self._lock, self._db:
            self._db.executemany(
                'INSERT OR IGNORE INTO files (sub, name, size, status, pair) VALUES (?, ?, ?, ?, ?)',
                [(sub, a.name, a.size + b.size, 'pending', b.name) for a, b in pairs],
            )

    # pair_of: partner file name of a paired row, None for an unpaired one
    def pair_of(self, sub: str, name: str) -> str | None:
        with self._lock:
            row = self._db.execute('SELECT pair FROM files WHERE sub = ? AND name = ?', (sub, name)).fetchone()
        return row[0] if row else None

    # claim: atomically take the next pending file and mark it running
    def claim(self) -> tuple[str, str] | None:
        with self._lock, self._db:
            row = self._db.execute('SELECT sub, name FROM files WHERE status = ? ORDER BY rowid LIMIT 1', ('pending',)).fetchone()
            if row is not None:
                self._db.execute('UPDATE files SET status = ?, started = ?, finished = NULL, attempts = attempts + 1 WHERE sub = ? AND name = ?', ('running', time(), *row))
        return row

    # finish: record the outcome of a claimed file, stage says where a failure happened
    def finish(self, sub: str, name: str, status: Status, error: str | None = None, stage: Stage | None = None) -> None:
        # a file requeued by a stop request has no finish time
        finished = time() if status in ('done', 'failed') else None
        with self._lock, self._db:
            self._db.execute('UPDATE files SET status = ?, error = ?, stage = ?, finished = ? WHERE sub = ? AND name = ?', (status, error, stage, finished, sub, name))

    # retry_failed: put failed files back in the queue, only those that failed at the given stage when set
    def retry_failed(self, only: Stage | None = None) -> None:
        with self._lock, self._db:
            self._db.execute('UPDATE files SET status = ?, error = NULL, stage = NULL WHERE status = ? AND (? IS NULL OR stage = ?)', ('pending', 'failed', only, only))

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

    # failures: (sub-dataset, file, error, stage) for every failed file
    def failures(self) -> list[tuple[str, str, str | None, str | None]]:
        with self._lock:
            return self._db.execute('SELECT sub, name, error, stage FROM files WHERE status = ? ORDER BY rowid', ('failed',)).fetchall()

    # timings: per sub-dataset (mean seconds per done file or None, files that needed more than one attempt)
    def timings(self) -> dict[str, tuple[float | None, int]]:
        with self._lock:
            rows = self._db.execute("SELECT sub, AVG(CASE WHEN status = 'done' THEN finished - started END), COALESCE(SUM(attempts > 1), 0) FROM files GROUP BY sub").fetchall()
        return {sub: (mean, retried) for sub, mean, retried in rows}
