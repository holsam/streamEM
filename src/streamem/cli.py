'''
streamem: command line interface
'''

# Import external dependencies
import typer

# Import internal streamem objects
from streamem.plan import plan_run

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
