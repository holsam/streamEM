'''
streamem: run command logic
'''

# Import external dependencies
import logging
from functools import partial
from pathlib import Path

# Import internal streamem objects
from streamem.utils import runner
from streamem.utils.config import load_config
from streamem.utils.display import busy, framed, report_counts, say
from streamem.utils.empiar import download, entry_number, list_files, match_pairs
from streamem.utils.manifest import Manifest
from streamem.utils.subset import select_files

# LOG_FORMAT: one line per event, with the worker thread that produced it
LOG_FORMAT = '%(asctime)s %(levelname)s [%(threadName)s] %(message)s'

# log: module logger
log = logging.getLogger(__name__)

# _open_log: append streamem loggers' output to path, returns the handler so the caller can detach it
def _open_log(path: Path) -> logging.Handler:
    handler = logging.FileHandler(path)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger = logging.getLogger('streamem')
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return handler

# exec_run: process every pending file of a config, resuming from its manifest
def exec_run(config_path: Path, retry_failed: bool = False, only: Stage | None = None, *, mirror: bool = False) -> None:
    with framed():
        config = load_config(config_path)
        number = entry_number(config.entry)
        manifest = Manifest(config_path.with_suffix('.db'))
        handler = _open_log(config_path.with_suffix('.log'))
        try:
            log.info('run %s retry_failed=%s only=%s mirror=%s', config_path.name, retry_failed, only, mirror)
            notes: list[str] = []
            with busy('Listing files...'):
                for sub in config.primaries():
                    files = select_files(list_files(number, sub.directory), sub.subset, sub.order, sub.seed)
                    partner = config.partner(sub)
                    if partner is None:
                        manifest.add(sub.name, files)
                        continue
                    pairs, unmatched = match_pairs(files, list_files(number, partner.directory))
                    manifest.add_pairs(sub.name, pairs)
                    if unmatched:
                        notes.append(f'{unmatched} files in {sub.name} or {partner.name} have no same-stem partner and are skipped')
            for note in notes:
                say(note)
            if retry_failed:
                manifest.retry_failed(only)
            log.info('begin %s', manifest.counts())
            runner.run(config, manifest, partial(download, number, mirror=mirror), report=report_counts)
            counts = manifest.counts()
            log.info('end %s', counts)
            report_counts(counts)
        finally:
            logging.getLogger('streamem').removeHandler(handler)
            handler.close()
    raise SystemExit(1 if counts['failed'] else 0)
