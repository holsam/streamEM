'''
streamem: command line interface
'''

# Import external dependencies
import typer
from pathlib import Path
from typing import Annotated, cast, Literal

# Import internal streamem objects
from streamem.plan import plan_run
from streamem.run import exec_run
from streamem.status import check_status
from streamem.utils.manifest import Stage

# app: typer entry point
app = typer.Typer(
    add_completion=False,
    no_args_is_help=True
)

# ConfigPath: config file argument, must exist and be a readable file
ConfigPath = Annotated[
    Path,
    typer.Argument(
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        metavar='CONFIG',
        help='Path to configuration TOML file.',
    ),
]

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
    config_path: ConfigPath,
    retry_failed: Annotated[
        bool,
        typer.Option('--retry-failed', help='Requeue files that previously failed.'),
    ] = False,
    only: Annotated[
        Literal['fetch', 'exec'] | None,
        typer.Option('--only', help='With --retry-failed, only requeue files which failed at this stage.'),
    ] = None,
) -> None:
    '''
    Execute a planned run using a configuration TOML file.
    '''
    if only and not retry_failed:
        raise typer.BadParameter('--only needs --retry-failed')
    exec_run(config_path=config_path, retry_failed=retry_failed, only=cast(Stage | None, only))

# status: show progress of a run
@app.command('status')
def status(
    config_path: ConfigPath,
    limit: Annotated[
        int,
        typer.Option('--limit', min=1, metavar='N', help='Maximum number of failed files to list.'),
    ] = 20,
) -> None:
    '''
    Check the progress of a run from its manifest.
    '''
    check_status(config_path=config_path, limit=limit)
