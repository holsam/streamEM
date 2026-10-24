'''
streamem: terminal display helpers
'''

# Import external dependencies
import questionary, questionary.prompts.common
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from rich.console import Console, RenderableType
from rich.padding import Padding
from rich.table import Table
from typing import get_args

# Import internal streamem objects
from streamem.utils.config import SubDataset
from streamem.utils.empiar import ImageSet
from streamem.utils.manifest import Status

# GB: bytes per gigabyte (used for budgets and display)
GB = 1024**3

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

# wrote: confirmation that a file was written
def wrote(path: Path) -> None:
    console.print(f'wrote {path}')

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
