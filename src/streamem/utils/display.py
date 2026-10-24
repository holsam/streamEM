'''
streamem: terminal display helpers
'''

# Import external dependencies
import questionary, questionary.prompts.common
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from rich.columns import Columns
from rich.console import Console, RenderableType
from rich.markup import escape
from rich.padding import Padding
from rich.syntax import Syntax
from rich.table import Table
from rich.tree import Tree
from typing import get_args

# Import internal streamem objects
from streamem.utils.empiar import ImageSet
from streamem.utils.manifest import Status

# GB: bytes per gigabyte (used for budgets and display)
GB = 1000**3

# INDENT: number of spaces to use per indentation level
INDENT = 2

# STYLE: base style for prompts with dimmed hints and selected checkbox rows in bold green
STYLE = questionary.Style([
    ('qmark', ''),
    ('question', ''),
    ('answer', ''),
    ('pointer', 'bold'),
    ('selected', 'fg:ansigreen bold'),
    ('instruction', 'fg:ansibrightblack'),
])

# _PROMPT: keyword arguments for all questionary prompts
_PROMPT = {'qmark': '', 'style': STYLE}

# CANCEL: row appended to the dataset list, ticking it abandons the plan
CANCEL = 'Cancel'

# questionary.prompts.common.INDICATOR_SELECTED: use a tick to indicate selected checkbox rows
questionary.prompts.common.INDICATOR_SELECTED = '✔'

# console: instantiate shared rich console
console = Console()

# _label: return prompt message at given indentation level
def _label(message: str, indent: int) -> str:
    return ' ' * max(0, INDENT * indent - 1) + message

# _ask_number: text prompt validated as kind within bounds, returning the raw answer
def _ask_number(
    message: str, default: float, kind: Callable[[str], float], minimum: float, maximum: float | None, indent: int
) -> str:
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
    return questionary.text(_label(message, indent), default=str(default), validate=check, **_PROMPT).unsafe_ask()

# _add_branches: recursively add dict keys and list items to a rich tree
def _add_branches(tree: Tree, data: object) -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                _add_branches(tree.add(f'[bold]{escape(str(key))}[/bold]'), value)
            else:
                tree.add(escape(f'{key}: {value}'))
    elif isinstance(data, list):
        for i, item in enumerate(data, 1):
            _add_branches(tree.add(f'#{i}'), item)

# busy: show a spinner during execution
def busy(message: str) -> AbstractContextManager:
    return console.status(message)

# blank: empty line
def blank() -> None:
    console.print()

# rule: full width dashed line
def rule() -> None:
    console.rule(style='dim', characters='-')

# section: blank line then a title, content under it is indented with say or an indented prompt
def section(title: str) -> None:
    blank()
    console.print(title)

# say: print text (markup allowed) or any rich renderable at an indentation level
def say(content: RenderableType, indent: int = 1) -> None:
    console.print(Padding(content, (0, 0, 0, INDENT * indent), expand=False))

# erase_last_line: remove the previous terminal line
def erase_last_line() -> None:
    if console.is_terminal:
        console.file.write('\x1b[1A\x1b[2K\r')
        console.file.flush()

# framed: blank line (and rule when ruled) before and after the wrapped output (including early exit)
@contextmanager
def framed(*, ruled: bool = False) -> Iterator[None]:
    blank()
    if ruled:
        rule()
    try:
        yield
    finally:
        if ruled:
            rule()
        blank()

# show_entry: print a heading for the queried EMPIAR entry
def show_entry(number: str, title: str) -> None:
    console.print(f'[bold]EMPIAR-{number}[/bold]: {title}')

# fail: red error line
def fail(message: str) -> None:
    console.print(f'[red]{message}[/red]')

# ask_text: free text prompt, blank answers rejected unless allow_blank
def ask_text(message: str, default: str = '', *, allow_blank: bool = False, hint: str = '', erase: bool = False, indent: int = 1) -> str:
    validate = None if allow_blank else lambda value: bool(value.strip()) or 'cannot be blank'
    answer = questionary.text(_label(message, indent), default=default, validate=validate, instruction=hint or None, **_PROMPT).unsafe_ask()
    if erase:
        erase_last_line()
    return answer

# ask_path: path prompt with tab completion
def ask_path(message: str, default: str = '', *, indent: int = 1) -> Path:
    return Path(questionary.path(_label(message, indent), default=default, **_PROMPT).unsafe_ask())

# ask_int: integer prompt re-asked until within minimum and maximum
def ask_int(message: str, default: int, *, minimum: int = 1, maximum: int | None = None, indent: int = 1) -> int:
    return int(_ask_number(message, default, int, minimum, maximum, indent))

# ask_float: float prompt re-asked until within minimum and maximum
def ask_float(message: str, default: float, *, minimum: float = 0.1, maximum: float | None = None, indent: int = 1) -> float:
    return float(_ask_number(message, default, float, minimum, maximum, indent))

# ask_confirm: yes/no prompt
def ask_confirm(message: str, default: bool = False, *, indent: int = 1) -> bool:
    return questionary.confirm(_label(message, indent), default=default, **_PROMPT).unsafe_ask()

# choose: tabulate image sets and multi-select them, None when cancelled
def choose(sets: list[ImageSet]) -> list[ImageSet] | None:
    section('Available datasets:')
    table = Table('#', 'name', 'category', 'format', 'count')
    for i, s in enumerate(sets):
        table.add_row(str(i), s.name, s.category, s.data_format, str(s.count))
    say(table)
    titles = {id(s): f'{i}: {s.directory}' for i, s in enumerate(sets)}
    choices = [questionary.Choice(titles[id(s)], value=s) for s in sets]
    choices.append(questionary.Choice(CANCEL, value=None))
    picked = questionary.checkbox(_label('Datasets to process:', 1), choices=choices, validate=lambda selected: bool(selected) or 'Select at least one dataset, or Cancel', **_PROMPT).unsafe_ask()
    if None in picked:
        return None
    # swap questionary's own 'done (n selections)' line for the chosen directories
    erase_last_line()
    say(escape('Datasets to process: [' + ', '.join(titles[id(s)] for s in picked) + ']'))
    return picked

# show_dataset: one dataset's file count and sizes
def show_dataset(name: str, sizes: list[int]) -> None:
    table = Table('dataset', 'files', 'mean GB', 'max GB', 'total TB')
    table.add_row(
        name, str(len(sizes)), f'{sum(sizes) / len(sizes) / GB:.2f}', f'{max(sizes) / GB:.2f}', f'{sum(sizes) / GB / 1000:.2f}'
    )
    say(table)

# show_preview: the config as a tree, next to the SLURM script when there is one
def show_preview(name: str, config: dict, sbatch: str | None) -> None:
    section('Preview:')
    tree = Tree(f'[bold]{escape(name)}[/bold]')
    _add_branches(tree, config)
    shown: list[RenderableType] = [tree]
    if sbatch is not None:
        shown.append(Syntax(sbatch, 'bash', theme='ansi_dark', background_color='default'))
    say(Columns(shown, padding=(0, 4)))

# saved: confirmation of the files written
def saved(config_path: Path, sbatch_path: Path | None = None) -> None:
    extra = f' (& {sbatch_path.name})' if sbatch_path is not None else ''
    say(escape(f'Saved {config_path.name}{extra} to {config_path.resolve().parent}.'))

# report_counts: one-line progress of files per status
def report_counts(counts: dict[str, int]) -> None:
    console.print(' '.join(f'{status}={n}' for status, n in counts.items()))

# show_status: per sub-dataset counts by status and GB done against total
def show_status(summary: dict[str, dict[str, tuple[int, int]]]) -> None:
    table = Table('sub-dataset', *get_args(Status), 'done GB', 'total GB')
    for sub, by_status in summary.items():
        done_gb = by_status['done'][1] / GB
        total_gb = sum(size for _, size in by_status.values()) / GB
        table.add_row(sub, *(str(by_status[s][0]) for s in get_args(Status)), f'{done_gb:.1f}', f'{total_gb:.1f}')
    console.print(table)

# show_failures: first limit failed files with their errors, then a count of the rest
def show_failures(failures: list[tuple[str, str, str | None]], limit: int) -> None:
    if not failures:
        return
    table = Table('sub-dataset', 'file', 'error')
    for sub, name, error in failures[:limit]:
        table.add_row(sub, name, error or '')
    console.print(table)
    if len(failures) > limit:
        console.print(f'... and {len(failures) - limit} more failed')
