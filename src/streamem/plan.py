'''
streamem: plan command logic and helpers for calculating disk budget & rendering SLURM script
'''

# Import external dependencies
import random, shutil
from pathlib import Path

# Import internal streamem objects
from streamem.utils.config import Config, SubDataset, write_config
from streamem.utils.display import (
    GB, ask_confirm, ask_float, ask_int, ask_optional_int, ask_path, ask_select, ask_text, busy, choose, fail,
    framed, saved, say, section, show_dataset, show_entry, show_preview,
)
from streamem.utils.empiar import ImageSet, entry_number, fetch_entry, list_files
from streamem.utils.subset import select_files

# PLACEHOLDERS: hint shown beside the command prompt
PLACEHOLDERS = '({file}, {outdir}, {name} placeholders available)'

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

# _ask_entry: prompt for the entry ID (line erased once answered), returns its number
def _ask_entry() -> str:
    entry = ask_text('EMPIAR entry ID:', indent=0, erase=True)
    try:
        return entry_number(entry)
    except ValueError:
        fail(f'Invalid EMPIAR entry {entry!r}')
        raise SystemExit(1)

# _plan_dataset: size table, subset, command and output directory for one chosen image set
def _plan_dataset(number: str, n: int, image_set: ImageSet) -> SubDataset:
    section(f'Dataset {n}:')
    with busy(f'Listing {image_set.directory}...'):
        files = list_files(number, image_set.directory)
    if not files:
        fail(f'No files found in {image_set.directory}')
        raise typer.Exit(1)
    show_dataset(image_set.name, [f.size for f in files])
    subset, order, seed = _ask_subset(len(files))
    picked = select_files(files, subset, order, seed)
    if subset is not None:
        say(f'Using {len(picked)} of {len(files)} files ({order})')
    sizes = [f.size for f in picked]
    cmd = ask_text('Command:', hint=PLACEHOLDERS)
    outdir = ask_path('Output directory:', f'results/{Path(image_set.directory).name}')
    return SubDataset(
        name=image_set.name, directory=image_set.directory, cmd=cmd, outdir=outdir,
        n_files=len(picked), mean_bytes=sum(sizes) // len(sizes), max_bytes=max(sizes),
        subset=subset, order=order, seed=seed,
    )

# _ask_subset: how many files to use and which, blank for all, a random pick gets a fresh stored seed
def _ask_subset(total: int) -> tuple[int | None, str, int]:
    subset = ask_optional_int(f'Number of files to process (blank for all {total}):', maximum=total)
    if subset is None:
        return None, 'alphabetical', 0
    order = ask_select('Which files:', ['alphabetical', 'random'])
    return subset, order, random.randrange(2**32) if order == 'random' else 0

# _plan_processing: scratch, storage limit, workers, config filename and optional SLURM script
def _plan_processing(number: str, subs: list[SubDataset]) -> tuple[Config, Path, str | None]:
    section('Processing configuration:')
    workdir = ask_path('Scratch directory for downloads:', 'scratch')
    budget = ask_float('Storage limit for raw data (GB):', 200)
    margin = 0.8
    safe = _max_workers(budget, margin, _free_bytes(workdir), max(s.max_bytes for s in subs))
    if safe < 1:
        fail('Storage limit too small for one file at the safety margin')
        raise SystemExit(1)
    workers = ask_int(f'Number of workers (safe max: {safe}):', min(4, safe), maximum=safe)
    config_path = ask_path('Filename for configuration:', 'streamem.toml')
    config = Config(entry=f'EMPIAR-{number}', workdir=workdir, budget_gb=budget, margin=margin, workers=workers, subdatasets=subs)
    sbatch = _plan_slurm(config_path, workers) if ask_confirm('Create SLURM script?') else None
    return config, config_path, sbatch

# _plan_slurm: SLURM questions (one level in) and the rendered script
def _plan_slurm(config_path: Path, workers: int) -> str:
    partition = ask_text('Partition (blank for default):', allow_blank=True, indent=2)
    time = ask_text('Time:', '24:00:00', indent=2)
    mem = ask_int('Memory (GB):', 64, indent=2)
    extra: list[str] = []
    while request := ask_text('Additional SBATCH request (blank to continue):', allow_blank=True, indent=2).strip().removeprefix('--'):
        if '=' in request:
            extra.append(request)
        else:
            fail('Use the form resource=request, e.g. gpus=1')
    return _render_slurm(config_path, workers=workers, partition=partition, time=time, mem_gb=mem, extra=extra)

# plan_run: interactively plan a run, writing a config and (optionally) SLURM script once confirmed
def plan_run() -> None:
    with framed(ruled=True):
        number = _ask_entry()
        with busy('Querying EMPIAR API...'):
            title, sets = fetch_entry(number)
        show_entry(number, title)
        chosen = choose(sets)
        if chosen is None:
            say('Cancelled')
            raise SystemExit(1)
        subs = [_plan_dataset(number, n, image_set) for n, image_set in enumerate(chosen, 1)]
        config, config_path, sbatch = _plan_processing(number, subs)
        sbatch_path = config_path.with_suffix('.sbatch') if sbatch is not None else None
        show_preview(config_path.name, config.model_dump(mode='json', exclude_none=True), sbatch)
        if not ask_confirm('Continue?', True):
            say('Nothing written')
            raise SystemExit(0)
        write_config(config, config_path)
        if sbatch_path is not None:
            sbatch_path.write_text(sbatch)
        saved(config_path, sbatch_path)
