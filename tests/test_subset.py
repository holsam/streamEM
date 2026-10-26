'''
streamem: tests for subset selection and configuration
'''

# Import external dependencies
import pytest
from pathlib import Path
from pydantic import ValidationError

# Import internal streamem objects
from streamem.utils.config import SubDataset, load_config, write_config
from streamem.utils.empiar import RemoteFile
from streamem.utils.subset import select_files

# FILES: ten unsorted files
FILES = [RemoteFile(f'{n}.mrc', 10) for n in (5, 3, 9, 1, 7, 2, 10, 4, 8, 6)]

# names: file names of a selection
def names(files: list[RemoteFile]) -> list[str]:
    return [f.name for f in files]

# TestSelectFiles: deterministic, bounded selection
class TestSelectFiles:
    # test_all_sorted: no subset returns every file sorted by name
    def test_all_sorted(self) -> None:
        assert names(select_files(FILES, None)) == sorted(f.name for f in FILES)

    # test_subset_larger_than_total: asking for too many returns all
    def test_subset_larger_than_total(self) -> None:
        assert len(select_files(FILES, 99, 'random', 1)) == 10

    # test_alphabetical: first N by name string order
    def test_alphabetical(self) -> None:
        assert names(select_files(FILES, 3)) == ['1.mrc', '10.mrc', '2.mrc']

    # test_random_reproducible: same seed same files, returned sorted
    def test_random_reproducible(self) -> None:
        first = select_files(FILES, 4, 'random', seed=42)
        assert first == select_files(FILES, 4, 'random', seed=42)
        assert len(first) == 4
        assert names(first) == sorted(names(first))

    # test_random_seed_changes_pick: some seed gives a different pick
    def test_random_seed_changes_pick(self) -> None:
        picks = {tuple(names(select_files(FILES, 4, 'random', seed=s))) for s in range(10)}
        assert len(picks) > 1

    # test_input_untouched: the caller's list is not reordered
    def test_input_untouched(self) -> None:
        before = list(FILES)
        select_files(FILES, 3, 'random', 1)
        assert FILES == before

# TestSubsetConfig: new fields survive a TOML round trip and old configs still load
class TestSubsetConfig:
    # make: a sub-dataset with the given subset fields
    @staticmethod
    def make(**kwargs: object) -> SubDataset:
        return SubDataset(name='s', directory='data/s', cmd='true', outdir=Path('out'), n_files=3, mean_bytes=1, max_bytes=1, **kwargs)

    # test_roundtrip: set subset, order and seed come back unchanged
    def test_roundtrip(self, tmp_path: Path, make_config) -> None:
        config = make_config(subdatasets=[self.make(subset=5, order='random', seed=7)])
        write_config(config, tmp_path / 'c.toml')
        sub = load_config(tmp_path / 'c.toml').subdatasets[0]
        assert (sub.subset, sub.order, sub.seed) == (5, 'random', 7)

    # test_none_is_omitted: an unset subset is not written, and loads back as None
    def test_none_is_omitted(self, tmp_path: Path, make_config) -> None:
        config = make_config(subdatasets=[self.make()])
        write_config(config, tmp_path / 'c.toml')
        assert 'subset' not in (tmp_path / 'c.toml').read_text()
        assert load_config(tmp_path / 'c.toml').subdatasets[0].subset is None

    # test_validation: subset must be positive and order must be known
    def test_validation(self) -> None:
        with pytest.raises(ValidationError):
            self.make(subset=0)
        with pytest.raises(ValidationError):
            self.make(order='newest')
