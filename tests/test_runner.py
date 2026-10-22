'''
streamem: tests for the worker pool
'''

# Import external dependencies
import threading
from pathlib import Path

# Import internal streamem objects
from streamem.utils.config import Config, SubDataset
from streamem.utils.empiar import RemoteFile
from streamem.utils.manifest import Manifest
from streamem.utils.runner import LOG, run

# _config: two-worker config with one sub-dataset running cmd
def _config(tmp_path: Path, cmd: str) -> Config:
    sub = SubDataset(
        name='s', directory='data/s', cmd=cmd, outdir=tmp_path / 'out', n_files=2, mean_bytes=10, max_bytes=10
    )
    return Config(entry='EMPIAR-1', workdir=tmp_path / 'scratch', budget_gb=1, workers=2, subdatasets=[sub])

# _fetch: fake download that writes the file name into dest
def _fetch(directory: str, name: str, dest: Path, stop: threading.Event) -> None:
    dest.write_text(name)

# _manifest: manifest holding files a.mrc and b.mrc
def _manifest(tmp_path: Path) -> Manifest:
    manifest = Manifest(tmp_path / 'm.db')
    manifest.add('s', [RemoteFile('a.mrc', 10), RemoteFile('b.mrc', 10)])
    return manifest

# test_success: command sees expanded placeholders and env, raw files are deleted
def test_success(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    run(_config(tmp_path, 'cp {file} {outdir}/copy && echo $STREAMEM_NAME > {outdir}/name'), manifest, _fetch)
    assert manifest.counts() == {'pending': 0, 'running': 0, 'done': 2, 'failed': 0}
    assert (tmp_path / 'out' / 'a' / 'copy').read_text() == 'a.mrc'
    assert (tmp_path / 'out' / 'b' / 'name').read_text().strip() == 'b'
    assert not list((tmp_path / 'scratch').rglob('*.mrc'))

# test_failure: non-zero exit marks failed, still deletes the raw file, keeps the log
def test_failure(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    run(_config(tmp_path, 'echo oops; exit 3'), manifest, _fetch)
    assert manifest.counts()['failed'] == 2
    assert not list((tmp_path / 'scratch').rglob('*.mrc'))
    assert 'oops' in (tmp_path / 'out' / 'a' / LOG).read_text()

# test_stop: a pre-set stop leaves everything pending and runs nothing
def test_stop(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    stop = threading.Event()
    stop.set()
    run(_config(tmp_path, 'true'), manifest, _fetch, stop=stop)
    assert manifest.counts()['pending'] == 2

# test_too_many_workers: refuses when workers exceed what fits the budget
def test_too_many_workers(tmp_path: Path) -> None:
    config = _config(tmp_path, 'true')
    config.subdatasets[0].max_bytes = 10**9
    config.budget_gb = 1
    try:
        run(config, _manifest(tmp_path), _fetch)
    except ValueError:
        return
    raise AssertionError('expected ValueError')
