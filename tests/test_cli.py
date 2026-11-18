'''
streamem: tests for CLI argument validation
'''

# Import external dependencies
from pathlib import Path
from typer.testing import CliRunner

# Import internal streamem objects
from streamem.cli import app

# runner: invokes the app in-process
runner = CliRunner()

# TestConfigArgument: run and status reject bad config paths before any logic runs
class TestConfigArgument:
    # test_missing_file: nonexistent config exits 2
    def test_missing_file(self, tmp_path: Path) -> None:
        for command in ('run', 'status'):
            result = runner.invoke(app, [command, str(tmp_path / 'nope.toml')])
            assert result.exit_code == 2

    # test_directory_rejected: a directory is not a config file
    def test_directory_rejected(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ['run', str(tmp_path)])
        assert result.exit_code == 2

    # test_help_metavars: help text names CONFIG and N, not typer's internal names
    def test_help_metavars(self) -> None:
        assert 'CONFIG' in runner.invoke(app, ['run', '--help']).output
        status_help = runner.invoke(app, ['status', '--help']).output
        assert 'CONFIG' in status_help
        assert 'INTEGER' not in status_help

# TestLimitOption: --limit must be at least 1
class TestLimitOption:
    # test_zero_rejected: zero exits 2 before status logic runs
    def test_zero_rejected(self, tmp_path: Path) -> None:
        config = tmp_path / 'c.toml'
        config.write_text('')
        result = runner.invoke(app, ['status', str(config), '--limit', '0'])
        assert result.exit_code == 2

# TestOnlyOption: --only is only valid with --retry-failed
class TestOnlyOption:
    # test_needs_retry_failed: --only alone exits 2
    def test_needs_retry_failed(self, tmp_path: Path) -> None:
        config = tmp_path / 'c.toml'
        config.write_text('')
        assert runner.invoke(app, ['run', str(config), '--only', 'fetch']).exit_code == 2

    # test_rejects_unknown_stage: only fetch and exec are accepted
    def test_rejects_unknown_stage(self, tmp_path: Path) -> None:
        config = tmp_path / 'c.toml'
        config.write_text('')
        assert runner.invoke(app, ['run', str(config), '--retry-failed', '--only', 'nope']).exit_code == 2
