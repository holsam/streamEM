'''
streamem: tests for the run configuration
'''

# Import external dependencies
import pytest
from pathlib import Path
from pydantic import ValidationError

# Import internal streamem objects
from streamem.utils.config import load_config, write_config

# TestConfigRoundTrip: write then load
class TestConfigRoundTrip:
    # test_roundtrip: every field survives, paths come back as Path
    def test_roundtrip(self, tmp_path: Path, make_config) -> None:
        config = make_config('echo {file}')
        write_config(config, tmp_path / 'c.toml')
        loaded = load_config(tmp_path / 'c.toml')
        assert loaded == config
        assert isinstance(loaded.workdir, Path)
        assert isinstance(loaded.subdatasets[0].outdir, Path)

    # test_margin_default: a config without margin gets 0.8
    def test_margin_default(self, tmp_path: Path) -> None:
        (tmp_path / 'c.toml').write_text(
            'entry = "EMPIAR-1"\nworkdir = "w"\nbudget_gb = 1.0\nworkers = 1\nsubdatasets = []\n'
        )
        assert load_config(tmp_path / 'c.toml').margin == 0.8

# TestConfigValidation: bad values are rejected at load time
class TestConfigValidation:
    # test_bounds: workers, budget and margin limits
    @pytest.mark.parametrize('field, value', [('workers', 0), ('budget_gb', 0), ('margin', 0), ('margin', 1.5)])
    def test_bounds(self, make_config, field: str, value: float) -> None:
        with pytest.raises(ValidationError):
            make_config('true', **{field: value})

    # test_missing_field: an incomplete file names the missing key
    def test_missing_field(self, tmp_path: Path) -> None:
        (tmp_path / 'c.toml').write_text('entry = "EMPIAR-1"\n')
        with pytest.raises(ValidationError, match='workdir'):
            load_config(tmp_path / 'c.toml')
