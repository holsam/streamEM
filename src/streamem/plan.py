'''
streamem: plan command logic and helpers for calculating disk budget & rendering SLURM script
'''

# Import external dependencies
import shutil
from pathlib import Path

# Import internal streamem objects
from streamem.utils.config import Config, SubDataset, write_config
from streamem.utils.display import (
    GB, ask_confirm, ask_float, ask_int, ask_path, ask_text, busy, choose, fail, show_entry, summary, wrote,
)
from streamem.utils.empiar import entry_number, fetch_entry, list_files

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

# plan_run: interactively plan a run by creating config and (optionally) SLURM script
def plan_run():
    entry = ask_text('EMPIAR entry ID:')
    number = entry_number(entry)
    with busy('Querying EMPIAR API...'):
        title, sets = fetch_entry(number)
    show_entry(number, title)
    chosen = choose(sets)
    if not chosen:
        raise SystemExit(1)

    # sizes come from the FTP listing, only fetched for the selected sets
    subs: list[SubDataset] = []
    for s in chosen:
        with busy(f'Listing {s.directory}...'):
            files = list_files(number, s.directory)
        sizes = [f.size for f in files]
        cmd = ask_text(f'Command for {s.name} ({{file}} {{outdir}} {{name}} available):')
        outdir = ask_path(f'Output directory for {s.name}:', f'results/{Path(s.directory).name}')
        subs.append(SubDataset(name=s.name, directory=s.directory, cmd=cmd, outdir=outdir, n_files=len(files), mean_bytes=sum(sizes) // len(sizes), max_bytes=max(sizes)))

    workdir = ask_path('Scratch directory for downloads:', 'scratch')
    budget = ask_float('Disk budget for raw data (GB):', 200)
    margin = 0.8
    biggest = max(s.max_bytes for s in subs)
    safe = _max_workers(budget, margin, _free_bytes(workdir), biggest)
    summary(subs, safe)
    if safe < 1:
        fail('Budget too small for one file at the safety margin')
        raise SystemExit(1)
    workers = ask_int(f'Workers (max safe {safe}):', min(4, safe), maximum=safe)

    config = Config(entry=f'EMPIAR-{number}', workdir=workdir, budget_gb=budget, margin=margin, workers=workers, subdatasets=subs)
    config_path = ask_path('Write config to:', 'streamem.toml')
    write_config(config, config_path)
    wrote(config_path)

    if ask_confirm('Also write a SLURM script?'):
        partition = ask_text('Partition (blank for default):', allow_blank=True)
        time = ask_text('Time limit:', '24:00:00')
        mem = ask_int('Memory (GB):', 64)
        extra: list[str] = []
        while request := ask_text('Additional SBATCH request (blank to continue):', allow_blank=True).strip().removeprefix('--'):
            if '=' in request:
                extra.append(request)
            else:
                fail('Use the form resource=request, e.g. gpus=1')
        slurm_path = config_path.with_suffix('.sbatch')
        slurm_path.write_text(_render_slurm(config_path, workers=workers, partition=partition, time=time, mem_gb=mem, extra=extra))
        wrote(slurm_path)
