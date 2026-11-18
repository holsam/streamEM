'''
streamem: worker pool that downloads, processes and deletes one file at a time
'''

# Import external dependencies
import os, shlex, signal, subprocess, threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

# Import internal streamem objects
from streamem.utils.config import Config, SubDataset, footprint
from streamem.utils.manifest import Manifest, Stage, Status
from streamem.plan import _free_bytes, _max_workers

# LOG: per-file command output, written inside that file's outdir
LOG = 'streamem.log'

# Fetch: download (directory, name) to a local path, raising if stop is set mid-transfer
Fetch = Callable[[str, str, Path, threading.Event], None]

# run: drain the manifest with config.workers threads, returns when empty or stopped
def run(
    config: Config,
    manifest: Manifest,
    fetch: Fetch,
    *,
    stop: threading.Event | None = None,
    report: Callable[[dict[str, int]], None] = lambda counts: None,
) -> None:
    stop = stop or threading.Event()
    safe = _max_workers(config.budget_gb, config.margin, _free_bytes(config.workdir), footprint(config.subdatasets))
    if config.workers > safe:
        raise ValueError(f'{config.workers} workers exceed the {safe} that fit the disk budget')
    subs = {s.name: s for s in config.subdatasets}
    with ThreadPoolExecutor(config.workers) as pool:
        futures = [pool.submit(_work, config, subs, manifest, fetch, stop, report) for _ in range(config.workers)]
        try:
            for future in futures:
                future.result()
        except KeyboardInterrupt:
            # workers see the event, abort their file and requeue it, the pool exit waits for them
            stop.set()

# _work: one worker, claim and process files until none are left
def _work(
    config: Config,
    subs: dict[str, SubDataset],
    manifest: Manifest,
    fetch: Fetch,
    stop: threading.Event,
    report: Callable[[dict[str, int]], None],
) -> None:
    while not stop.is_set() and (item := manifest.claim()) is not None:
        sub_name, name = item
        _process(config, subs[sub_name], name, manifest.pair_of(sub_name, name), manifest, fetch, stop)
        report(manifest.counts())

# _process: download one file (and its partner), run the command, delete the raw files, record the outcome
def _process(
    config: Config,
    sub: SubDataset,
    name: str,
    pair: str | None,
    manifest: Manifest,
    fetch: Fetch,
    stop: threading.Event,
) -> None:
    path = config.workdir / Path(sub.directory).name / name
    partner = config.partner(sub)
    pair_path = config.workdir / Path(partner.directory).name / pair if partner is not None and pair else None
    stem = Path(name).stem
    outdir = sub.outdir / stem
    status: Status
    stage: Stage = 'fetch'
    error: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        outdir.mkdir(parents=True, exist_ok=True)
        fetch(sub.directory, name, path, stop)
        if partner is not None and pair_path is not None:
            pair_path.parent.mkdir(parents=True, exist_ok=True)
            fetch(partner.directory, pair, pair_path, stop)
        stage = 'exec'
        code = _exec(_expand(sub.cmd, file=path, outdir=outdir, name=stem, pair=pair_path), path, outdir, stem, pair_path, stop)
        status = 'done' if code == 0 else 'failed'
        error = None if code == 0 else f'exit code {code}, see {outdir / LOG}'
    except Exception as exc:
        status, error = 'failed', repr(exc)
    finally:
        # ensure raw data doesn't outlive processing
        path.unlink(missing_ok=True)
        if pair_path is not None:
            pair_path.unlink(missing_ok=True)
    if stop.is_set() and status == 'failed':
        # killed by the stop request, not a real failure
        status, error = 'pending', None
    manifest.finish(sub.name, name, status, error, stage if status == 'failed' else None)

# _expand: substitute placeholders by plain replace so shell braces survive
def _expand(cmd: str, *, file: Path, outdir: Path, name: str, pair: Path | None = None) -> str:
    out = (
        cmd.replace('{file}', shlex.quote(str(file)))
        .replace('{outdir}', shlex.quote(str(outdir)))
        .replace('{name}', shlex.quote(name))
    )
    return out if pair is None else out.replace('{pair}', shlex.quote(str(pair)))

# _exec: run the command in its own process group, SIGTERM the group when stop is set
def _exec(cmd: str, file: Path, outdir: Path, name: str, pair: Path | None, stop: threading.Event) -> int:
    env = {**os.environ, 'STREAMEM_FILE': str(file), 'STREAMEM_OUTDIR': str(outdir), 'STREAMEM_NAME': name}
    if pair is not None:
        env['STREAMEM_PAIR'] = str(pair)
    with (outdir / LOG).open('ab') as log:
        # one dated header per attempt, a retry appends rather than overwriting the last failure
        log.write(f'--- {datetime.now().isoformat(timespec='seconds')} ---\n'.encode())
        log.flush()
        proc = subprocess.Popen(cmd, shell=True, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        while True:
            try:
                return proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                if stop.is_set():
                    os.killpg(proc.pid, signal.SIGTERM)
                    return proc.wait()
