'''
streamem: tests for entry parsing, budget maths and SLURM rendering
'''

# Import external dependencies
import pytest
from pathlib import Path

# Import internal streamem objects
from streamem.plan import GB, _free_bytes, _max_workers, _render_slurm, plan_run
from streamem.utils.config import load_config

# TestMaxWorkers: margin applies to the smaller of budget and free space
class TestMaxWorkers:
    # test_budget_bound: budget smaller than free space decides
    def test_budget_bound(self) -> None:
        assert _max_workers(100, 0.8, 1000 * GB, 2 * GB) == 40

    # test_free_space_bound: free space smaller than budget decides
    def test_free_space_bound(self) -> None:
        assert _max_workers(100, 0.8, 10 * GB, 2 * GB) == 4

    # test_too_small: budget below one file gives zero workers
    def test_too_small(self) -> None:
        assert _max_workers(1, 0.8, 1000 * GB, 2 * GB) == 0

# TestFreeBytes: free space of the nearest existing parent
class TestFreeBytes:
    # test_existing_path: a real directory reports space
    def test_existing_path(self, tmp_path: Path) -> None:
        assert _free_bytes(tmp_path) > 0

    # test_missing_path_uses_parent: a path that does not exist yet falls back to its parent
    def test_missing_path_uses_parent(self, tmp_path: Path) -> None:
        assert abs(_free_bytes(tmp_path / 'a' / 'b') - _free_bytes(tmp_path)) < 10**8

# TestRenderSlurm: optional lines only appear when set
class TestRenderSlurm:
    # test_extras: each extra request becomes its own #SBATCH line
    def test_extras(self) -> None:
        text = _render_slurm(Path('c.toml'), workers=4, partition='', time='01:00:00', mem_gb=8, extra=['gpus=1', 'qos=long'])
        assert '#SBATCH --gpus=1' in text
        assert '#SBATCH --qos=long' in text
        assert '--partition' not in text

    # test_partition_and_resources: partition, cpus, memory and time come through
    def test_partition_and_resources(self) -> None:
        text = _render_slurm(Path('c.toml'), workers=4, partition='gpu', time='02:00:00', mem_gb=8, extra=[])
        assert '#SBATCH --partition=gpu' in text
        assert '#SBATCH --cpus-per-task=4' in text
        assert '#SBATCH --mem=8G' in text
        assert '#SBATCH --time=02:00:00' in text

    # test_run_line_last: the script ends by running the config
    def test_run_line_last(self) -> None:
        text = _render_slurm(Path('c.toml'), workers=1, partition='', time='01:00:00', mem_gb=1, extra=[])
        assert text.splitlines()[-1] == 'streamem run c.toml'

# TestPlanRun: the whole interactive flow with scripted answers against a fake EMPIAR
class TestPlanRun:
    # answers: queue the prompts in the order plan_run asks them
    @staticmethod
    def answers(ask, tmp_path: Path, *, slurm: bool = False, confirm: bool = True) -> None:
        ask.queue(
            'EMPIAR-11830',                                   # entry ID
            lambda kw: [kw['choices'][1].value],              # tick 'Denoised tomograms'
            '',                                               # subset (blank for all)
            'echo {file}',                                    # command
            str(tmp_path / 'out'),                            # output directory
            str(tmp_path / 'scratch'),                        # scratch
            '1',                                              # storage limit GB
            '2',                                              # workers
            str(tmp_path / 'c.toml'),                         # config filename
            slurm,                                            # create SLURM script?
        )
        if slurm:
            ask.queue('gpu', '01:00:00', '8', 'gpus=1', 'bad', '--qos=long', '')   # partition, time, mem, extras
        ask.queue(confirm)                                    # continue?

    # test_writes_config: confirmed run writes a loadable config with the file stats
    def test_writes_config(self, ask, capture, remote, tmp_path: Path) -> None:
        self.answers(ask, tmp_path)
        plan_run()
        config = load_config(tmp_path / 'c.toml')
        assert config.entry == 'EMPIAR-11830'
        assert config.workers == 2
        sub = config.subdatasets[0]
        assert (sub.directory, sub.n_files, sub.mean_bytes, sub.max_bytes) == ('data/denoised', 3, 2000, 3000)
        assert not (tmp_path / 'c.sbatch').exists()
        assert not ask.answers
        text = capture.getvalue()
        assert 'Saved c.toml' in text
        assert 'Preview:' in text

    # test_writes_sbatch: SLURM answers produce a script with accepted extras only
    def test_writes_sbatch(self, ask, capture, remote, tmp_path: Path) -> None:
        self.answers(ask, tmp_path, slurm=True)
        plan_run()
        script = (tmp_path / 'c.sbatch').read_text()
        assert '#SBATCH --partition=gpu' in script
        assert '#SBATCH --gpus=1' in script
        assert '#SBATCH --qos=long' in script
        assert 'bad' not in script
        assert 'Use the form resource=request' in capture.getvalue()

    # test_decline_writes_nothing: answering no at Continue? leaves the directory untouched
    def test_decline_writes_nothing(self, ask, capture, remote, tmp_path: Path) -> None:
        self.answers(ask, tmp_path, confirm=False)
        with pytest.raises(SystemExit) as exc:
            plan_run()
        assert exc.value.code == 0
        assert not (tmp_path / 'c.toml').exists()
        assert 'Nothing written' in capture.getvalue()

    # test_cancel_exits: ticking Cancel stops before any listing or prompt
    def test_cancel_exits(self, ask, capture, remote) -> None:
        ask.queue('11830', lambda kw: [kw['choices'][-1].value])
        with pytest.raises(SystemExit) as exc:
            plan_run()
        assert exc.value.code == 1
        assert 'Cancelled' in capture.getvalue()

    # test_invalid_entry: a bad entry ID fails with a message
    def test_invalid_entry(self, ask, capture, remote) -> None:
        ask.queue('abc')
        with pytest.raises(SystemExit):
            plan_run()
        assert "Invalid EMPIAR entry 'abc'" in capture.getvalue()

    # test_storage_too_small: a limit below one file at the margin exits instead of asking for workers
    def test_storage_too_small(self, ask, capture, remote, tmp_path: Path) -> None:
        ask.queue(
            '11830', lambda kw: [kw['choices'][1].value], '', 'true', str(tmp_path / 'out'),
            str(tmp_path / 'scratch'), '0.000001',
        )
        with pytest.raises(SystemExit):
            plan_run()
        assert 'Storage limit too small' in capture.getvalue()

    # test_subset_flow: a random subset stores count, order and a seed, and stats come from the picked files
    def test_subset_flow(self, ask, capture, remote, tmp_path: Path) -> None:
        ask.queue(
            'EMPIAR-11830', lambda kw: [kw['choices'][1].value], '2', 'random', 'true', str(tmp_path / 'out'),
            str(tmp_path / 'scratch'), '1', '1', str(tmp_path / 'c.toml'), False, True,
        )
        plan_run()
        sub = load_config(tmp_path / 'c.toml').subdatasets[0]
        assert (sub.subset, sub.order, sub.n_files) == (2, 'random', 2)
        assert 0 <= sub.seed < 2**32
        assert 'Using 2 of 3 files (random)' in capture.getvalue()
        assert sub.max_bytes in (2000, 3000)

    # test_alphabetical_subset: first N by name, stats from those files only
    def test_alphabetical_subset(self, ask, capture, remote, tmp_path: Path) -> None:
        ask.queue(
            'EMPIAR-11830', lambda kw: [kw['choices'][1].value], '1', 'alphabetical', 'true', str(tmp_path / 'out'),
            str(tmp_path / 'scratch'), '1', '1', str(tmp_path / 'c.toml'), False, True,
        )
        plan_run()
        sub = load_config(tmp_path / 'c.toml').subdatasets[0]
        assert (sub.subset, sub.seed, sub.n_files, sub.max_bytes) == (1, 0, 1, 3000)   # 'a.mrc' is 3000 bytes
