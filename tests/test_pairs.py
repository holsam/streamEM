'''
streamem: tests for paired sub-datasets
'''

# Import external dependencies
import pytest
from collections.abc import Callable
from pathlib import Path
from pydantic import ValidationError

# Import internal streamem objects
from streamem.utils import runner
from streamem.utils.config import Config, SubDataset, footprint
from streamem.utils.empiar import RemoteFile, match_pairs
from streamem.utils.manifest import Manifest

# _sub: a sub-dataset with fixed sizes, directory named after the sub-dataset
def _sub(name: str, *, outdir: Path = Path('out'), cmd: str = 'true', pair_with: str | None = None) -> SubDataset:
    return SubDataset(name=name, directory=f'data/{name}', cmd=cmd, outdir=outdir, n_files=2, mean_bytes=10, max_bytes=10, pair_with=pair_with)

# TestPairs: config rules, stem matching, manifest rows, runner behaviour
class TestPairs:
    # test_config_rejects_bad_pairs: unknown, shared and chained partners are refused
    def test_config_rejects_bad_pairs(self, tmp_path: Path) -> None:
        # build: a config around the given sub-datasets
        def build(*subs: SubDataset) -> Config:
            return Config(entry='EMPIAR-1', workdir=tmp_path, budget_gb=1, workers=1, subdatasets=list(subs))

        with pytest.raises(ValidationError, match='unknown'):
            build(_sub('a', pair_with='zzz'))
        with pytest.raises(ValidationError, match='only one'):
            build(_sub('a', pair_with='c'), _sub('b', pair_with='c'), _sub('c'))
        with pytest.raises(ValidationError, match='both'):
            build(_sub('a', pair_with='b'), _sub('b', pair_with='c'), _sub('c'))

    # test_footprint_counts_both_files: a pair needs room for primary and partner, the partner is not counted alone
    def test_footprint_counts_both_files(self) -> None:
        assert footprint([_sub('a', pair_with='b'), _sub('b')]) == 20
        assert footprint([_sub('a')]) == 10

    # test_match_by_stem: extensions may differ, strays are counted
    def test_match_by_stem(self) -> None:
        first = [RemoteFile('t1.mrc', 4), RemoteFile('t2.mrc', 4), RemoteFile('t3.mrc', 4)]
        second = [RemoteFile('t1.rec', 6), RemoteFile('t3.rec', 6), RemoteFile('t9.rec', 6)]
        pairs, unmatched = match_pairs(first, second)
        assert [(a.name, b.name) for a, b in pairs] == [('t1.mrc', 't1.rec'), ('t3.mrc', 't3.rec')]
        assert unmatched == 2

    # test_manifest_rows_are_pairs: one row per pair, summed size, partner name recoverable
    def test_manifest_rows_are_pairs(self, tmp_path: Path) -> None:
        manifest = Manifest(tmp_path / 'm.db')
        manifest.add_pairs('a', [(RemoteFile('t1.mrc', 4), RemoteFile('t1.rec', 6))])
        assert manifest.summary()['a']['pending'] == (1, 10)
        assert manifest.pair_of('a', 't1.mrc') == 't1.rec'

    # test_runner_fetches_both_and_cleans_up: cmd sees both files, neither survives, row is done
    def test_runner_fetches_both_and_cleans_up(self, tmp_path: Path, fake_fetch: Callable[..., None]) -> None:
        subs = [
            _sub('a', outdir=tmp_path / 'out', cmd='test -f {file} && test -f {pair}', pair_with='b'),
            _sub('b'),
        ]
        config = Config(entry='EMPIAR-1', workdir=tmp_path / 'scratch', budget_gb=1, workers=1, subdatasets=subs)
        (tmp_path / 'scratch').mkdir()
        manifest = Manifest(tmp_path / 'm.db')
        manifest.add_pairs('a', [(RemoteFile('t1.mrc', 4), RemoteFile('t1.rec', 6))])
        runner.run(config, manifest, fake_fetch)
        assert manifest.counts()['done'] == 1
        assert not list((tmp_path / 'scratch').rglob('t1.*'))
