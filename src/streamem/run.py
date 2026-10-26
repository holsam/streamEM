'''
streamem: run command logic
'''

# Import external dependencies
from functools import partial
from pathlib import Path

# Import internal streamem objects
from streamem.utils import runner
from streamem.utils.config import load_config
from streamem.utils.display import busy, framed, report_counts, say
from streamem.utils.empiar import download, entry_number, list_files, match_pairs
from streamem.utils.manifest import Manifest
from streamem.utils.subset import select_files

# exec_run: process every pending file of a config, resuming from its manifest
def exec_run(config_path: Path, retry_failed: bool = False) -> None:
    with framed():
        config = load_config(config_path)
        number = entry_number(config.entry)
        manifest = Manifest(config_path.with_suffix('.db'))
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
            manifest.retry_failed()
        runner.run(config, manifest, partial(download, number), report=report_counts)
        counts = manifest.counts()
        report_counts(counts)
    raise SystemExit(1 if counts['failed'] else 0)
