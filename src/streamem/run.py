'''
streamem: run command logic
'''

# Import external dependencies
from functools import partial
from pathlib import Path

# Import internal streamem objects
from streamem.utils import runner
from streamem.utils.config import load_config
from streamem.utils.display import busy, framed, report_counts
from streamem.utils.empiar import download, entry_number, list_files
from streamem.utils.manifest import Manifest

# exec_run: process every pending file of a config, resuming from its manifest
def exec_run(config_path: Path, retry_failed: bool = False) -> None:
    with framed():
        config = load_config(config_path)
        number = entry_number(config.entry)
        manifest = Manifest(config_path.with_suffix('.db'))
        with busy('Listing files...'):
            for sub in config.subdatasets:
                manifest.add(sub.name, list_files(number, sub.directory))
        if retry_failed:
            manifest.retry_failed()
        runner.run(config, manifest, partial(download, number), report=report_counts)
        counts = manifest.counts()
        report_counts(counts)
    raise SystemExit(1 if counts['failed'] else 0)
