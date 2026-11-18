'''
streamem: tests for the progress manifest
'''

# Import external dependencies
import sqlite3, threading
from pathlib import Path

# Import internal streamem objects
from streamem.utils.empiar import RemoteFile
from streamem.utils.manifest import Manifest

# TestManifest: queue semantics, resume, summaries
class TestManifest:
    # test_claim_each_file_once: claims drain the queue in order, then return None
    def test_claim_each_file_once(self, manifest: Manifest) -> None:
        assert manifest.claim() == ('s', 'a.mrc')
        assert manifest.claim() == ('s', 'b.mrc')
        assert manifest.claim() is None
        assert manifest.counts() == {'pending': 0, 'running': 2, 'done': 0, 'failed': 0}

    # test_claims_are_unique_across_threads: four threads draining 100 files never share one
    def test_claims_are_unique_across_threads(self, tmp_path: Path) -> None:
        manifest = Manifest(tmp_path / 'm.db')
        manifest.add('s', [RemoteFile(str(n), 1) for n in range(100)])
        claimed: list[tuple[str, str]] = []
        lock = threading.Lock()

        # work: claim until the queue is empty
        def work() -> None:
            while (item := manifest.claim()) is not None:
                with lock:
                    claimed.append(item)

        threads = [threading.Thread(target=work) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(claimed) == 100
        assert len(set(claimed)) == 100

    # test_add_keeps_existing_status: re-adding files never resets progress or duplicates rows
    def test_add_keeps_existing_status(self, manifest: Manifest) -> None:
        manifest.claim()
        manifest.finish('s', 'a.mrc', 'done')
        manifest.add('s', [RemoteFile('a.mrc', 10), RemoteFile('b.mrc', 10)])
        assert manifest.counts() == {'pending': 1, 'running': 0, 'done': 1, 'failed': 0}

    # test_resume: running rows go back to pending on reopen, done rows stay done
    def test_resume(self, manifest: Manifest, tmp_path: Path) -> None:
        manifest.claim()
        manifest.finish('s', 'a.mrc', 'done')
        manifest.claim()
        reopened = Manifest(tmp_path / 'm.db')
        assert reopened.counts() == {'pending': 1, 'running': 0, 'done': 1, 'failed': 0}

    # test_retry_failed: failed rows requeue and lose their error
    def test_retry_failed(self, manifest: Manifest) -> None:
        manifest.claim()
        manifest.finish('s', 'a.mrc', 'failed', 'boom')
        manifest.retry_failed()
        assert manifest.counts()['pending'] == 2
        assert manifest.failures() == []

    # test_summary_and_failures: counts and bytes per sub-dataset, failures carry their error
    def test_summary_and_failures(self, tmp_path: Path) -> None:
        manifest = Manifest(tmp_path / 'm.db')
        manifest.add('s', [RemoteFile('a', 10), RemoteFile('b', 20)])
        manifest.claim()
        manifest.finish('s', 'a', 'done')
        manifest.claim()
        manifest.finish('s', 'b', 'failed', 'boom')
        summary = manifest.summary()['s']
        assert summary['done'] == (1, 10)
        assert summary['failed'] == (1, 20)
        assert summary['pending'] == (0, 0)
        assert manifest.failures() == [('s', 'b', 'boom', None)]

    # test_summary_per_sub_dataset: each sub-dataset gets its own row
    def test_summary_per_sub_dataset(self, tmp_path: Path) -> None:
        manifest = Manifest(tmp_path / 'm.db')
        manifest.add('x', [RemoteFile('a', 1)])
        manifest.add('y', [RemoteFile('a', 2)])
        assert set(manifest.summary()) == {'x', 'y'}

    # test_read_only_open: recover=False leaves running rows alone
    def test_read_only_open(self, manifest: Manifest, tmp_path: Path) -> None:
        manifest.claim()
        assert Manifest(tmp_path / 'm.db', recover=False).counts()['running'] == 1
        assert Manifest(tmp_path / 'm.db').counts()['pending'] == 2

    # test_finish_records_stage: a failure keeps the stage it was given
    def test_finish_records_stage(self, manifest: Manifest) -> None:
        manifest.claim()
        manifest.finish('s', 'a.mrc', 'failed', 'boom', 'fetch')
        assert manifest.failures() == [('s', 'a.mrc', 'boom', 'fetch')]

    # test_retry_only_stage: only failures at the given stage are requeued, others stay failed
    def test_retry_only_stage(self, manifest: Manifest) -> None:
        manifest.claim()
        manifest.finish('s', 'a.mrc', 'failed', 'x', 'fetch')
        manifest.claim()
        manifest.finish('s', 'b.mrc', 'failed', 'y', 'exec')
        manifest.retry_failed('fetch')
        assert manifest.counts() == {'pending': 1, 'running': 0, 'done': 0, 'failed': 1}
        assert manifest.failures() == [('s', 'b.mrc', 'y', 'exec')]

    # test_timings: mean seconds per done file, and a file claimed twice counts as retried
    def test_timings(self, manifest: Manifest, monkeypatch: pytest.MonkeyPatch) -> None:
        from streamem.utils import manifest as manifest_module
        clock = iter([100.0, 104.0, 200.0, 210.0])
        monkeypatch.setattr(manifest_module, 'time', lambda: next(clock))
        manifest.claim()
        manifest.finish('s', 'a.mrc', 'done')
        manifest.claim()
        manifest.finish('s', 'b.mrc', 'done')
        assert manifest.timings() == {'s': (7.0, 0)}

    # test_retried_counts_attempts: a requeued file claimed again has two attempts
    def test_retried_counts_attempts(self, manifest: Manifest) -> None:
        manifest.claim()
        manifest.finish('s', 'a.mrc', 'failed', 'boom', 'exec')
        manifest.retry_failed()
        manifest.claim()
        assert manifest.timings()['s'][1] == 1

    # test_old_database_is_migrated: a v0.2 table gains the new columns and works as normal
    def test_old_database_is_migrated(self, tmp_path: Path) -> None:
        db = sqlite3.connect(tmp_path / 'old.db')
        db.execute('CREATE TABLE files (sub TEXT, name TEXT, size INTEGER, status TEXT NOT NULL, error TEXT, pair TEXT, PRIMARY KEY (sub, name))')
        db.execute("INSERT INTO files VALUES ('s', 'a', 1, 'pending', NULL, NULL)")
        db.commit()
        db.close()
        reopened = Manifest(tmp_path / 'old.db')
        assert reopened.claim() == ('s', 'a')
