'''
streamem: tests for entry parsing, budget maths and SLURM rendering
'''

# Import external dependencies
import pytest
from pathlib import Path

# Import internal streamem objects
from streamem.utils.empiar import entry_number
from streamem.plan import GB, _max_workers, _render_slurm

# test_entry_number: both ID spellings normalise, junk is rejected
def test_entry_number() -> None:
    assert entry_number('EMPIAR-11830') == entry_number(' 11830 ') == '11830'
    with pytest.raises(ValueError):
        entry_number('abc')

# test_max_workers: margin applies to the smaller of budget and free space
def test_max_workers() -> None:
    assert _max_workers(100, 0.8, 1000 * GB, 2 * GB) == 40
    assert _max_workers(100, 0.8, 10 * GB, 2 * GB) == 4
    assert _max_workers(1, 0.8, 1000 * GB, 2 * GB) == 0

# test_render_slurm: optional lines only appear when set
def test_render_slurm() -> None:
    text = _render_slurm(Path('c.toml'), workers=4, partition='', time='01:00:00', mem_gb=8, extra=['gpus=1', 'qos=long'])
    assert '#SBATCH --gpus=1' in text
    assert '#SBATCH --qos=long' in text
    assert '--partition' not in text
    assert 'streamem run c.toml' in text
