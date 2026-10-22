'''
streamem: terminal display helpers
'''

# Import external dependencies
import questionary
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from rich.console import Console
from rich.table import Table

# Import internal streamem objects
from streamem.plan import GB
from streamem.utils.config import SubDataset
from streamem.utils.empiar import ImageSet

# console: instantiate shared rich console
console = Console()

# busy: show a spinner during execution
def busy(message: str) -> AbstractContextManager:
    return console.status(message)

# show_entry: print a heading for the queried EMPIAR entry
def show_entry(number: str, title: str) -> None:
    console.print(f'[bold]EMPIAR-{number}[/bold]: {title}')

# fail: red error line
def fail(message: str) -> None:
    console.print(f'[red]{message}[/red]')

# wrote: confirmation that a file was written
def wrote(path: Path) -> None:
    console.print(f'wrote {path}')

# ask_text: free text prompt, blank answers rejected unless allow_blank
def ask_text(message: str, default: str = '', *, allow_blank: bool = False) -> str:
    validate = None if allow_blank else lambda value: bool(value.strip()) or 'cannot be blank'
    return questionary.text(message, default=default, validate=validate).unsafe_ask()

# ask_path: path prompt with tab completion
def ask_path(message: str, default: str = '') -> Path:
    return Path(questionary.path(message, default=default).unsafe_ask())

# ask_int: integer prompt re-asked until within minimum and maximum
def ask_int(message: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    return int(_ask_number(message, default, int, minimum, maximum))

# ask_float: float prompt re-asked until within minimum and maximum
def ask_float(message: str, default: float, *, minimum: float = 0.1, maximum: float | None = None) -> float:
    return float(_ask_number(message, default, float, minimum, maximum))

# ask_confirm: yes/no prompt
def ask_confirm(message: str, default: bool = False) -> bool:
    return questionary.confirm(message, default=default).unsafe_ask()

# choose: multi-select image sets from a table
def choose(sets: list[ImageSet]) -> list[ImageSet]:
    table = Table('#', 'name', 'category', 'format', 'count')
    for i, s in enumerate(sets):
        table.add_row(str(i), s.name, s.category, s.data_format, str(s.count))
    console.print(table)
    picked = questionary.checkbox(
        'sub-datasets to process:', choices=[questionary.Choice(f'{i}: {s.directory}', value=s) for i, s in enumerate(sets)]
    ).unsafe_ask()
    return picked or []

# summary: per sub-dataset sizes and the planned limits
def summary(subs: list[SubDataset], safe: int) -> None:
    table = Table('sub-dataset', 'files', 'mean GB', 'max GB', 'total TB')
    for s in subs:
        table.add_row(s.name, str(s.n_files), f'{s.mean_bytes / GB:.2f}', f'{s.max_bytes / GB:.2f}', f'{s.n_files * s.mean_bytes / GB / 1000:.2f}')
    console.print(table)
    console.print(f'max safe concurrent files: [bold]{safe}[/bold]')

# _ask_number: text prompt validated as kind within bounds, returns the raw answer
def _ask_number(message: str, default: float, kind: Callable[[str], float], minimum: float, maximum: float | None) -> str:
    # check: questionary validator, True or an error message
    def check(value: str) -> bool | str:
        try:
            number = kind(value)
        except ValueError:
            return f'enter a number ({kind.__name__})'
        if number < minimum:
            return f'must be at least {minimum}'
        if maximum is not None and number > maximum:
            return f'must be at most {maximum}'
        return True
    return questionary.text(message, default=str(default), validate=check).unsafe_ask()
