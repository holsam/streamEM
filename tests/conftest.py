'''
streamem: shared test fixtures
'''

# Import external dependencies
import io, json, pytest
from collections.abc import Callable
from pathlib import Path
from rich.console import Console

# Import internal streamem objects
from streamem.utils import display, empiar
from streamem.utils.config import Config, SubDataset
from streamem.utils.empiar import RemoteFile
from streamem.utils.manifest import Manifest

# FILES: the two files most manifest and runner tests share
FILES = [RemoteFile('a.mrc', 10), RemoteFile('b.mrc', 10)]

# ENTRY_PAYLOAD: REST response for a two image set entry
ENTRY_PAYLOAD = {
    'EMPIAR-11830': {
        'title': 'Test entry',
        'imagesets': [
            {'name': 'Raw tilt series', 'directory': 'data/raw', 'category': 'tilt series', 'data_format': 'EER', 'num_images_or_tilt_series': 3},
            {'name': 'Denoised tomograms', 'directory': 'data/denoised', 'category': 'reconstructed volumes', 'data_format': 'MRC', 'num_images_or_tilt_series': 3},
        ],
    }
}

# LIST_LINES: unix ls -l style FTP listing, one directory (skipped) and three files (one name with spaces)
LIST_LINES = [
    'drwxr-xr-x    2 ftp      ftp          4096 Feb 28  2025 subdir',
    '-rw-r--r--    1 ftp      ftp          1000 Feb 28  2025 c.mrc',
    '-rw-r--r--    1 ftp      ftp          3000 Feb 28  2025 a.mrc',
    '-rw-r--r--    1 ftp      ftp          2000 Feb 28  2025 b with space.mrc',
]

# _Question: mock a questionary question
class _Question:
    def __init__(self, answer: object) -> None:
        self.answer = answer
    def unsafe_ask(self) -> object:
        return self.answer

# Prompts: mock questionary prompt functions
class Prompts:
    def __init__(self) -> None:
        self.answers: list[object] = []
        self.calls: list[tuple[str, str, dict]] = []
    # queue: add answers, consumed one per prompt in call order, a callable answer receives that prompt's kwargs
    def queue(self, *answers: object) -> None:
        self.answers.extend(answers)
    # make: build the replacement for one questionary prompt function
    def make(self, kind: str) -> Callable[..., _Question]:
        def prompt(message: str, *args: object, **kwargs: object) -> _Question:
            self.calls.append((kind, message, kwargs))
            answer = self.answers.pop(0)
            return _Question(answer(kwargs) if callable(answer) else answer)
        return prompt

# FakeFTP: mock ftplib.FTP with scripted behaviour per connection
class FakeFTP:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.cwd_path = ''
    def __call__(self, *args: object, **kwargs: object) -> 'FakeFTP':
        return self
    def __enter__(self) -> 'FakeFTP':
        return self
    def __exit__(self, *args: object) -> bool:
        return False
    def login(self) -> None:
        pass
    def cwd(self, path: str) -> None:
        self.cwd_path = path
    def retrlines(self, cmd: str, callback: Callable[[str], None]) -> None:
        for line in self.lines:
            callback(line)

# ask: replace every questionary prompt with scripted answers
@pytest.fixture
def ask(monkeypatch: pytest.MonkeyPatch) -> Prompts:
    prompts = Prompts()
    for kind in ('text', 'path', 'confirm', 'select', 'checkbox'):
        monkeypatch.setattr(display.questionary, kind, prompts.make(kind))
    return prompts

# capture: replace shared console to write to buffer
@pytest.fixture
def capture(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
    buffer = io.StringIO()
    monkeypatch.setattr(display, 'console', Console(file=buffer, width=100, color_system=None, force_terminal=False))
    return buffer

# fake_ftp: installer to swaps ftplib.FTP for a FakeFTP serving the given LIST lines
@pytest.fixture
def fake_ftp(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[str]], FakeFTP]:
    def install(lines: list[str]) -> FakeFTP:
        fake = FakeFTP(lines)
        monkeypatch.setattr(empiar.ftplib, 'FTP', fake)
        return fake
    return install

# fake_urlopen: installer to make REST call return the given payload
@pytest.fixture
def fake_urlopen(monkeypatch: pytest.MonkeyPatch) -> Callable[[dict], None]:
    def install(payload: dict) -> None:
        monkeypatch.setattr(empiar.urllib.request, 'urlopen', lambda url, timeout=30: io.BytesIO(json.dumps(payload).encode()))
    return install

# remote: fake EMPIAR with ENTRY_PAYLOAD over REST and LIST_LINES over FTP
@pytest.fixture
def remote(fake_urlopen: Callable[[dict], None], fake_ftp: Callable[[list[str]], FakeFTP]) -> FakeFTP:
    fake_urlopen(ENTRY_PAYLOAD)
    return fake_ftp(LIST_LINES)

# make_config: factory for a two-worker config with one sub-dataset running cmd
@pytest.fixture
def make_config(tmp_path: Path) -> Callable[..., Config]:
    def build(cmd: str = 'true', **overrides: object) -> Config:
        sub = SubDataset(name='s', directory='data/s', cmd=cmd, outdir=tmp_path / 'out', n_files=2, mean_bytes=10, max_bytes=10)
        values = {'entry': 'EMPIAR-1', 'workdir': tmp_path / 'scratch', 'budget_gb': 1, 'workers': 2, 'subdatasets': [sub]}
        return Config(**{**values, **overrides})
    return build

# manifest: manifest in tmp_path holding FILES
@pytest.fixture
def manifest(tmp_path: Path) -> Manifest:
    manifest = Manifest(tmp_path / 'm.db')
    manifest.add('s', FILES)
    return manifest

# fake_fetch: download stand-in that writes the file name into dest
@pytest.fixture
def fake_fetch() -> Callable[..., None]:
    def fetch(directory: str, name: str, dest: Path, stop: object) -> None:
        dest.write_text(name)
    return fetch
