'''
streamem: command line interface
'''

# Import external dependencies
import typer
from pathlib import Path
from typing import Annotated

# Import internal streamem objects
from streamem.plan import plan_run
from streamem.run import exec_run
from streamem.status import check_status

# app: typer entry point
app = typer.Typer(
    add_completion=False,
    no_args_is_help=True
)

# plan: interactive dry run that writes a config and optional SLURM script
@app.command()
def plan() -> None:
    '''
    Interactively plan a streamEM run.
    '''
    plan_run()

# run: process all pending files using a config TOML
@app.command('run')
def run(
    config_path: Annotated[
        Path,
        typer.Argument(help='Path to configuration TOML file.'),
    ],
    retry_failed: Annotated[
        bool,
        typer.Option('--retry-failed', help='Requeue files that previously failed.'),
    ] = False,
) -> None:
    '''
    Execute a planned run using a configuration TOML file.
    '''
    exec_run(config_path=config_path, retry_failed=retry_failed)

# status: show progress of a run
@app.command('status')
def status(
    config_path: Annotated[
        Path,
        typer.Argument(help='Path to configuration TOML file.')
    ],
    limit: Annotated[
        int,
        typer.Option('--limit', help='Maximum number of failed files to list.')
    ] = 20,
) -> None:
    '''
    Check the progress of a run from its manifest.
    '''
    check_status(config_path=config_path, limit=limit)
