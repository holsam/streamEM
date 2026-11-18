'''
streamem: tests for the worker pool
'''

# Import external dependencies
import pytest
import threading
from pathlib import Path

# Import internal streamem objects
from streamem.utils.empiar import RemoteFile
from streamem.utils.manifest import Manifest
from streamem.utils.runner import LOG, run

# TestRunner: download, command, cleanup and stop behaviour
class TestRunner:
    # test_success: command sees expanded placeholders and env, raw files are deleted
    def test_success(self, tmp_path: Path, make_config, manifest: Manifest, fake_fetch) -> None:
        run(make_config('cp {file} {outdir}/copy && echo $STREAMEM_NAME > {outdir}/name'), manifest, fake_fetch)
        assert manifest.counts() == {'pending': 0, 'running': 0, 'done': 2, 'failed': 0}
        assert (tmp_path / 'out' / 'a' / 'copy').read_text() == 'a.mrc'
        assert (tmp_path / 'out' / 'b' / 'name').read_text().strip() == 'b'
        assert not list((tmp_path / 'scratch').rglob('*.mrc'))

    # test_names_with_spaces: placeholders are shell quoted
    def test_names_with_spaces(self, tmp_path: Path, make_config, fake_fetch) -> None:
        manifest = Manifest(tmp_path / 'm.db')
        manifest.add('s', [RemoteFile('x y.mrc', 10)])
        run(make_config('cp {file} {outdir}/copy'), manifest, fake_fetch)
        assert manifest.counts()['done'] == 1
        assert (tmp_path / 'out' / 'x y' / 'copy').read_text() == 'x y.mrc'

    # test_braces_survive: shell braces that are not placeholders are left alone
    def test_braces_survive(self, tmp_path: Path, make_config, manifest: Manifest, fake_fetch) -> None:
        run(make_config('echo ${HOME:+set} > {outdir}/env'), manifest, fake_fetch)
        assert (tmp_path / 'out' / 'a' / 'env').read_text().strip() in ('set', '')
        assert manifest.counts()['done'] == 2

    # test_failure: non-zero exit marks failed, still deletes the raw file, keeps the log
    def test_failure(self, tmp_path: Path, make_config, manifest: Manifest, fake_fetch) -> None:
        run(make_config('echo oops; exit 3'), manifest, fake_fetch)
        assert manifest.counts()['failed'] == 2
        assert not list((tmp_path / 'scratch').rglob('*.mrc'))
        assert 'oops' in (tmp_path / 'out' / 'a' / LOG).read_text()
        assert 'exit code 3' in manifest.failures()[0][2]

    # test_fetch_error: a download that raises marks the file failed with the error
    def test_fetch_error(self, tmp_path: Path, make_config, manifest: Manifest) -> None:
        # broken: download stand-in that always errors
        def broken(directory: str, name: str, dest: Path, stop: threading.Event) -> None:
            raise OSError('network down')

        run(make_config('true'), manifest, broken)
        assert manifest.counts()['failed'] == 2
        assert 'network down' in manifest.failures()[0][2]

    # test_stop_before_start: a pre-set stop leaves everything pending and runs nothing
    def test_stop_before_start(self, make_config, manifest: Manifest, fake_fetch) -> None:
        stop = threading.Event()
        stop.set()
        run(make_config('true'), manifest, fake_fetch, stop=stop)
        assert manifest.counts()['pending'] == 2

    # test_stop_during_fetch: an interrupted download requeues the file instead of failing it
    def test_stop_during_fetch(self, make_config, manifest: Manifest) -> None:
        stop = threading.Event()

        # interrupted: sets stop and aborts like a download seeing it mid-transfer
        def interrupted(directory: str, name: str, dest: Path, stop_event: threading.Event) -> None:
            stop.set()
            raise InterruptedError

        run(make_config('true'), manifest, interrupted, stop=stop)
        assert manifest.counts()['pending'] == 2
        assert manifest.counts()['failed'] == 0

    # test_stop_kills_command: stop terminates a running command and requeues its file
    def test_stop_kills_command(self, make_config, manifest: Manifest, fake_fetch) -> None:
        stop = threading.Event()
        threading.Timer(0.5, stop.set).start()
        run(make_config('sleep 30', workers=1), manifest, fake_fetch, stop=stop)
        assert manifest.counts() == {'pending': 2, 'running': 0, 'done': 0, 'failed': 0}

    # test_report: progress callback sees the final counts
    def test_report(self, make_config, manifest: Manifest, fake_fetch) -> None:
        seen: list[dict[str, int]] = []
        run(make_config('true'), manifest, fake_fetch, report=seen.append)
        assert len(seen) == 2
        # workers report concurrently, so only the largest count is order independent
        assert max(counts['done'] for counts in seen) == 2

    # test_too_many_workers: refuses when workers exceed what fits the budget
    def test_too_many_workers(self, make_config, manifest: Manifest, fake_fetch) -> None:
        config = make_config('true')
        config.subdatasets[0].max_bytes = 10**9
        with pytest.raises(ValueError):
            run(config, manifest, fake_fetch)

    # test_failure_stage: a failed command is stage exec, a failed download is stage fetch
    def test_failure_stage(self, make_config, manifest: Manifest, fake_fetch) -> None:
        run(make_config('exit 1'), manifest, fake_fetch)
        assert {f[3] for f in manifest.failures()} == {'exec'}
        manifest.retry_failed()

        # broken: download stand-in that always errors
        def broken(directory: str, name: str, dest: Path, stop: threading.Event) -> None:
            raise OSError('network down')

        run(make_config('true'), manifest, broken)
        assert {f[3] for f in manifest.failures()} == {'fetch'}
