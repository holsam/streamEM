'''
streamem: tests for the progress manifest
'''

# Import external dependencies
from pathlib import Path

# Import internal streamem objects
from streamem.utils.empiar import RemoteFile
from streamem.utils.manifest import Manifest

# test_claim_each_file_once: claims drain the queue in order, then return None
def test_claim_each_file_once(tmp_path: Path) -> None:
    manifest = Manifest(tmp_path / 'm.db')
    manifest.add('s', [RemoteFile('a', 1), RemoteFile('b', 1)])
    assert manifest.claim() == ('s', 'a')
    assert manifest.claim() == ('s', 'b')
    assert manifest.claim() is None
    assert manifest.counts() == {'pending': 0, 'running': 0, 'done': 0, 'failed': 0} | {'running': 2}

# test_resume: running rows go back to pending on reopen, done rows stay done, add keeps status
def test_resume(tmp_path: Path) -> None:
    manifest = Manifest(tmp_path / 'm.db')
    manifest.add('s', [RemoteFile('a', 1), RemoteFile('b', 1)])
    manifest.claim()
    manifest.finish('s', 'a', 'done')
    manifest.claim()
    reopened = Manifest(tmp_path / 'm.db')
    reopened.add('s', [RemoteFile('a', 1), RemoteFile('b', 1)])
    assert reopened.counts() == {'pending': 1, 'running': 0, 'done': 1, 'failed': 0}

# test_retry_failed: failed rows requeue
def test_retry_failed(tmp_path: Path) -> None:
    manifest = Manifest(tmp_path / 'm.db')
    manifest.add('s', [RemoteFile('a', 1)])
    manifest.claim()
    manifest.finish('s', 'a', 'failed', 'boom')
    manifest.retry_failed()
    assert manifest.counts()['pending'] == 1
