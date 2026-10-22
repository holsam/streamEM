'''
streamem: helpers for calculating disk budget & rendering SLURM script
'''

# Import external dependencies
import shutil
from pathlib import Path

# Import internal streamem objects
from streamem.utils.display import GB

# max_workers: most concurrent files that fit in the usable budget, at least 0
def _max_workers(budget_gb: float, margin: float, free_bytes: int, max_file_bytes: int) -> int:
    usable = min(budget_gb * GB, free_bytes) * margin
    return int(usable // max_file_bytes)

# free_bytes: free space on the filesystem holding path (nearest existing parent)
def _free_bytes(path: Path) -> int:
    path = path.expanduser().resolve()
    while not path.exists():
        path = path.parent
    return shutil.disk_usage(path).free

# render_slurm: single-node job script that runs the config with its worker threads
def _render_slurm(config_path: Path, *, workers: int, partition: str, time: str, mem_gb: int, extra: list[str]) -> str:
    lines = [
        '#!/bin/bash',
        '#SBATCH --job-name=streamem',
        '#SBATCH --nodes=1',
        '#SBATCH --ntasks=1',
        f'#SBATCH --cpus-per-task={workers}',
        f'#SBATCH --mem={mem_gb}G',
        f'#SBATCH --time={time}',
    ]
    if partition:
        lines.append(f'#SBATCH --partition={partition}')
    lines += [f'#SBATCH --{request}' for request in extra]
    lines += ['', f'streamem run {config_path}', '']
    return '\n'.join(lines)
