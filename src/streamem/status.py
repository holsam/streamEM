'''
streamem: status command logic
'''

# Import external dependencies
import typer
from pathlib import Path

# Import internal streamem objects
from streamem.utils.config import load_config
from streamem.utils.display import fail, framed, show_failures, show_status
from streamem.utils.manifest import Manifest

# check_status: show progress of a config's manifest
def check_status(config_path: Path, limit: int = 20) -> None:
    with framed():
        db = config_path.with_suffix('.db')
        if not db.exists():
            fail(f'No manifest at {db}, run `streamem run` first')
            raise typer.Exit(1)
        manifest = Manifest(db, recover=False)
        workers = load_config(config_path).workers
        show_status(manifest.summary(), manifest.timings(), workers)
        show_failures(manifest.failures(), limit)
