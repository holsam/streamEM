'''
streamem: tests for display helpers and prompt wrappers
'''

# Import external dependencies
import io, pytest, questionary.prompts.common
from pathlib import Path
from rich.console import Console

# Import internal streamem objects
from streamem.utils import display
from streamem.utils.empiar import ImageSet

# TestPrompts: ask_* functions drop the qmark, apply the plain style and indent by level
class TestPrompts:
    # test_plain_style: no qmark, shared style, one-space-short indent because questionary adds one
    def test_plain_style(self, ask) -> None:
        ask.queue('x')
        display.ask_text('Name:')
        kind, message, kwargs = ask.calls[0]
        assert kwargs['qmark'] == ''
        assert kwargs['style'] is display.STYLE
        assert message == ' Name:'

    # test_indent_levels: level 0 none, level 2 eight spaces less one
    def test_indent_levels(self, ask) -> None:
        ask.queue('x', 'x')
        display.ask_text('Name:', indent=0)
        display.ask_text('Name:', indent=2)
        assert ask.calls[0][1] == 'Name:'
        assert ask.calls[1][1] == '   Name:'

    # test_blank_validation: blank rejected unless allowed
    def test_blank_validation(self, ask) -> None:
        ask.queue('x', 'x')
        display.ask_text('A:')
        display.ask_text('B:', allow_blank=True)
        assert ask.calls[0][2]['validate']('  ') == 'cannot be blank'
        assert ask.calls[0][2]['validate']('ok') is True
        assert ask.calls[1][2]['validate'] is None

    # test_hint: hint becomes the dimmed instruction text, empty hint is None
    def test_hint(self, ask) -> None:
        ask.queue('x', 'x')
        display.ask_text('A:', hint='(help)')
        display.ask_text('B:')
        assert ask.calls[0][2]['instruction'] == '(help)'
        assert ask.calls[1][2]['instruction'] is None

    # test_int_bounds: validator reports range and parse errors, answer comes back as int
    def test_int_bounds(self, ask) -> None:
        ask.queue('3')
        assert display.ask_int('Workers:', 2, maximum=4) == 3
        check = ask.calls[0][2]['validate']
        assert check('0') == 'must be at least 1'
        assert check('9') == 'must be at most 4'
        assert check('x') == 'enter a number (int)'
        assert check('3') is True

    # test_float: answer comes back as float
    def test_float(self, ask) -> None:
        ask.queue('2.5')
        assert display.ask_float('Budget:', 200) == 2.5

    # test_confirm_and_path: passthrough with the shared style
    def test_confirm_and_path(self, ask) -> None:
        ask.queue(True, 'out/dir')
        assert display.ask_confirm('Go?') is True
        assert str(display.ask_path('Where:')) == 'out/dir'
        assert all(call[2]['qmark'] == '' for call in ask.calls)

    # test_erase_only_when_asked: erase=True triggers erase_last_line, default does not
    def test_erase_only_when_asked(self, ask, monkeypatch: pytest.MonkeyPatch) -> None:
        erased: list[int] = []
        monkeypatch.setattr(display, 'erase_last_line', lambda: erased.append(1))
        ask.queue('x', 'x')
        display.ask_text('A:')
        display.ask_text('B:', erase=True)
        assert erased == [1]

    # test_optional_int_blank: blank answers return None, numbers return int, blank passes validation
    def test_optional_int_blank(self, ask) -> None:
        ask.queue('', '4')
        assert display.ask_optional_int('How many?', maximum=10) is None
        assert display.ask_optional_int('How many?', maximum=10) == 4
        check = ask.calls[0][2]['validate']
        assert check('') is True
        assert check('11') == 'must be at most 10'
        assert ask.calls[0][2]['default'] == ''

    # test_select: options pass through as choices
    def test_select(self, ask) -> None:
        ask.queue('random')
        assert display.ask_select('Which?', ['alphabetical', 'random']) == 'random'
        assert ask.calls[0][2]['choices'] == ['alphabetical', 'random']

# TestStyle: module-level questionary tweaks
class TestStyle:
    # test_tick_indicator: selected checkbox rows use a tick
    def test_tick_indicator(self) -> None:
        assert questionary.prompts.common.INDICATOR_SELECTED == '✔'

# TestHelpers: rule, blank, say, erase and framed output
class TestHelpers:
    # test_rule: a full width dashed line
    def test_rule(self, capture: io.StringIO) -> None:
        display.rule()
        assert set(capture.getvalue().strip()) == {'-'}

    # test_section: blank line then the title
    def test_section(self, capture: io.StringIO) -> None:
        display.section('Title:')
        assert capture.getvalue() == '\nTitle:\n'

    # test_say_indent: four spaces per level
    def test_say_indent(self, capture: io.StringIO) -> None:
        display.say('one')
        display.say('two', indent=2)
        lines = capture.getvalue().splitlines()
        assert lines[0].startswith('  one')
        assert lines[1].startswith('    two')

    # test_erase_not_terminal: nothing written to a pipe
    def test_erase_not_terminal(self, capture: io.StringIO) -> None:
        display.erase_last_line()
        assert capture.getvalue() == ''

    # test_erase_terminal: cursor-up and erase-line on a real terminal
    def test_erase_terminal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        buffer = io.StringIO()
        monkeypatch.setattr(display, 'console', Console(file=buffer, force_terminal=True))
        display.erase_last_line()
        assert buffer.getvalue() == '\x1b[1A\x1b[2K\r'

    # test_framed: blank lines around, rules when ruled
    def test_framed(self, capture: io.StringIO) -> None:
        with display.framed():
            display.say('x', indent=0)
        assert capture.getvalue() == '\nx\n\n'
        capture.seek(0)
        capture.truncate()
        with display.framed(ruled=True):
            pass
        lines = capture.getvalue().splitlines()
        assert lines[0] == '' and lines[3] == ''
        assert set(lines[1]) == set(lines[2]) == {'-'}

    # test_framed_closes_on_exception: closing blank line still printed on early exit
    def test_framed_closes_on_exception(self, capture: io.StringIO) -> None:
        with pytest.raises(RuntimeError):
            with display.framed():
                raise RuntimeError
        assert capture.getvalue() == '\n\n'

    # test_duration: seconds render as hours, minutes or seconds
    def test_duration(self) -> None:
        assert display._duration(7) == '7s'
        assert display._duration(250) == '4m10s'
        assert display._duration(5000) == '1h23m'

# TestChoose: dataset multi-select
class TestChoose:
    # sets: two image sets for the checkbox
    sets = [
        ImageSet('Raw', 'data/raw', 'tilt series', 'EER', 3),
        ImageSet('Denoised', 'data/denoised', 'reconstructed volumes', 'MRC', 3),
    ]

    # test_returns_picked_and_echoes: picked sets come back, the chosen directories are printed
    def test_returns_picked_and_echoes(self, ask, capture: io.StringIO) -> None:
        ask.queue(lambda kw: [kw['choices'][1].value])
        assert display.choose(self.sets) == [self.sets[1]]
        assert 'Datasets to process: [1: data/denoised]' in capture.getvalue()
        assert 'Available datasets:' in capture.getvalue()

    # test_cancel_row: ticking the last row returns None
    def test_cancel_row(self, ask, capture: io.StringIO) -> None:
        ask.queue(lambda kw: [kw['choices'][-1].value])
        assert display.choose(self.sets) is None
        assert ask.calls[0][2]['choices'][-1].title == display.CANCEL

    # test_cancel_with_others: cancel wins even when datasets are ticked too
    def test_cancel_with_others(self, ask, capture: io.StringIO) -> None:
        ask.queue(lambda kw: [kw['choices'][0].value, kw['choices'][-1].value])
        assert display.choose(self.sets) is None

    # test_none_selected_message: the validator keeps the prompt open with a message
    def test_none_selected_message(self, ask, capture: io.StringIO) -> None:
        ask.queue(lambda kw: [kw['choices'][0].value])
        display.choose(self.sets)
        validate = ask.calls[0][2]['validate']
        assert validate([]) == 'Select at least one dataset, or Cancel'
        assert validate([self.sets[0]]) is True

# TestShow: table, tree and confirmation output
class TestShow:
    # test_show_dataset: files, mean, max and total are derived from the sizes
    def test_show_dataset(self, capture: io.StringIO) -> None:
        gb = display.GB
        display.show_dataset('Denoised', [2 * gb, 2 * gb])
        text = capture.getvalue()
        assert 'Denoised' in text
        assert '2.00' in text
        assert '0.00' in text   # total TB for 4 GB

    # test_show_preview_tree: nested config keys and list items appear, markup characters survive
    def test_show_preview_tree(self, capture: io.StringIO) -> None:
        config = {'workers': 2, 'subdatasets': [{'name': 'a', 'cmd': 'echo [x] {file}'}]}
        display.show_preview('c.toml', config, None)
        text = capture.getvalue()
        assert 'Preview:' in text
        assert 'c.toml' in text
        assert 'workers: 2' in text
        assert '#1' in text
        assert 'cmd: echo [x] {file}' in text
        assert '#SBATCH' not in text

    # test_show_preview_sbatch: the script is shown beside the tree when present
    def test_show_preview_sbatch(self, capture: io.StringIO) -> None:
        display.show_preview('c.toml', {'workers': 1}, '#!/bin/bash\n#SBATCH --mem=8G\n')
        assert '#SBATCH --mem=8G' in capture.getvalue()

    # test_saved: names both files and the directory
    def test_saved(self, capture: io.StringIO, tmp_path: Path) -> None:
        display.saved(tmp_path / 'c.toml', tmp_path / 'c.sbatch')
        text = ' '.join(capture.getvalue().split())
        assert 'Saved c.toml (& c.sbatch) to' in text
        display.saved(tmp_path / 'c.toml')
        assert '(&' not in capture.getvalue().splitlines()[-1]

    # test_show_status_eta: files left times mean seconds divided by workers
    def test_show_status_eta(self) -> None:
        summary = {'s': {'pending': (4, 4), 'running': (0, 0), 'done': (1, 1), 'failed': (0, 0)}}
        with display.console.capture() as captured:
            display.show_status(summary, {'s': (90.0, 1)}, workers=2)
        assert '3m00s' in captured.get()