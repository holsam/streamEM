'''
streamem: tests for the run command
'''

# Import external dependencies
import pytest
from pathlib import Path
from typer.testing import CliRunner

# Import internal streamem objects
from streamem import run as run_module
from streamem.cli import app
from streamem.utils.config import write_config
from streamem.utils.manifest import Manifest

# runner: invokes the app in-process
runner = CliRunner()

# fake_download: stands in for the FTP download, writes the file name into dest
def fake_download(entry: str, directory: str, name: str, dest: Path, stop: object) -> None:
    dest.write_text(name)

# TestExecRun: the run command against a fake EMPIAR and a stand-in download
class TestExecRun:
    # offline: fake listings (three files) and downloads for every test in the class
    @pytest.fixture(autouse=True)
    def offline(self, remote, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(run_module, 'download', fake_download)

    # write: write a config running cmd and return its path
    @staticmethod
    def write(tmp_path: Path, make_config, cmd: str, **overrides: object) -> Path:
        path = tmp_path / 'c.toml'
        write_config(make_config(cmd, **overrides), path)
        return path

    # counts: manifest counts after a run
    @staticmethod
    def counts(path: Path) -> dict[str, int]:
        return Manifest(path.with_suffix('.db'), recover=False).counts()

    # test_processes_every_file: three files done, outputs written, scratch left empty
    def test_processes_every_file(self, tmp_path: Path, make_config) -> None:
        path = self.write(tmp_path, make_config, 'cp {file} {outdir}/copy')
        result = runner.invoke(app, ['run', str(path)])
        assert result.exit_code == 0
        assert 'done=3' in result.output
        assert self.counts(path)['done'] == 3
        assert (tmp_path / 'out' / 'b with space' / 'copy').read_text() == 'b with space.mrc'
        assert not list((tmp_path / 'scratch').rglob('*.mrc'))

    # test_rerun_does_not_repeat: finished files are not processed again
    def test_rerun_does_not_repeat(self, tmp_path: Path, make_config) -> None:
        path = self.write(tmp_path, make_config, 'echo x >> {outdir}/count')
        runner.invoke(app, ['run', str(path)])
        result = runner.invoke(app, ['run', str(path)])
        assert result.exit_code == 0
        assert (tmp_path / 'out' / 'a' / 'count').read_text() == 'x\n'

    # test_failure_exit_code: any failed file makes the command exit 1
    def test_failure_exit_code(self, tmp_path: Path, make_config) -> None:
        path = self.write(tmp_path, make_config, 'exit 1')
        result = runner.invoke(app, ['run', str(path)])
        assert result.exit_code == 1
        assert 'failed=3' in result.output

    # test_retry_failed: failed files stay failed until --retry-failed requeues them
    def test_retry_failed(self, tmp_path: Path, make_config) -> None:
        path = self.write(tmp_path, make_config, 'exit 1')
        runner.invoke(app, ['run', str(path)])
        self.write(tmp_path, make_config, 'true')
        assert runner.invoke(app, ['run', str(path)]).exit_code == 1
        result = runner.invoke(app, ['run', str(path), '--retry-failed'])
        assert result.exit_code == 0
        assert self.counts(path)['done'] == 3

    # test_subset_applied: only the selected files reach the manifest
    def test_subset_applied(self, tmp_path: Path, make_config) -> None:
        config = make_config('true')
        config.subdatasets[0].subset = 2
        path = tmp_path / 'c.toml'
        write_config(config, path)
        result = runner.invoke(app, ['run', str(path)])
        assert result.exit_code == 0
        assert self.counts(path)['done'] == 2
        assert (tmp_path / 'out' / 'a').exists()
        assert not (tmp_path / 'out' / 'c').exists()

    # test_only_fetch_leaves_exec_failures: --only fetch requeues download failures but not command failures
    def test_only_fetch_leaves_exec_failures(self, tmp_path: Path, make_config) -> None:
        path = self.write(tmp_path, make_config, 'exit 1')
        runner.invoke(app, ['run', str(path)])
        assert self.counts(path)['failed'] == 3
        result = runner.invoke(app, ['run', str(path), '--retry-failed', '--only', 'fetch'])
        assert self.counts(path)['failed'] == 3
        assert result.exit_code == 1
