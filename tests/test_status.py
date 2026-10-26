'''
streamem: tests for the status command
'''

# Import external dependencies
from pathlib import Path
from typer.testing import CliRunner

# Import internal streamem objects
from streamem.cli import app
from streamem.utils.config import write_config
from streamem.utils.empiar import RemoteFile
from streamem.utils.manifest import Manifest

# runner: invokes the app in-process
runner = CliRunner()

# TestCheckStatus: progress table, failure list and read-only behaviour
class TestCheckStatus:
    # setup_run: config plus a manifest with the given (name, status, error) rows, returns the config path
    @staticmethod
    def setup_run(tmp_path: Path, make_config, rows: list[tuple[str, str, str | None]]) -> Path:
        path = tmp_path / 'c.toml'
        write_config(make_config('true'), path)
        manifest = Manifest(path.with_suffix('.db'))
        manifest.add('s', [RemoteFile(name, 1_000_000_000) for name, _, _ in rows])
        for name, status, error in rows:
            manifest.claim()
            manifest.finish('s', name, status, error)
        return path

    # test_no_manifest: exits 1 with a hint before creating anything
    def test_no_manifest(self, tmp_path: Path, make_config) -> None:
        path = tmp_path / 'c.toml'
        write_config(make_config('true'), path)
        result = runner.invoke(app, ['status', str(path)])
        assert result.exit_code == 1
        assert 'No manifest' in result.output
        assert not path.with_suffix('.db').exists()

    # test_table_and_failures: counts, GB done and the failed file with its error
    def test_table_and_failures(self, tmp_path: Path, make_config) -> None:
        path = self.setup_run(tmp_path, make_config, [('a.mrc', 'done', None), ('b.mrc', 'failed', 'boom')])
        result = runner.invoke(app, ['status', str(path)])
        assert result.exit_code == 0
        assert 'sub-dataset' in result.output
        assert 'b.mrc' in result.output
        assert 'boom' in result.output

    # test_no_failures_no_failure_table: a clean run prints no error table
    def test_no_failures_no_failure_table(self, tmp_path: Path, make_config) -> None:
        path = self.setup_run(tmp_path, make_config, [('a.mrc', 'done', None)])
        result = runner.invoke(app, ['status', str(path)])
        assert 'error' not in result.output

    # test_limit: failures beyond --limit are counted, not listed
    def test_limit(self, tmp_path: Path, make_config) -> None:
        rows = [(f'{n}.mrc', 'failed', 'boom') for n in range(3)]
        path = self.setup_run(tmp_path, make_config, rows)
        result = runner.invoke(app, ['status', str(path), '--limit', '1'])
        assert '... and 2 more failed' in result.output

    # test_leaves_running_alone: reading status must not requeue a live run's files
    def test_leaves_running_alone(self, tmp_path: Path, make_config) -> None:
        path = self.setup_run(tmp_path, make_config, [('a.mrc', 'done', None)])
        manifest = Manifest(path.with_suffix('.db'))
        manifest.add('s', [RemoteFile('b.mrc', 1)])
        manifest.claim()
        runner.invoke(app, ['status', str(path)])
        assert Manifest(path.with_suffix('.db'), recover=False).counts()['running'] == 1
