'''
streamem: shared test fixtures
'''

# Import external dependencies
import ftplib, io, json, pytest, urllib.error
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

# DATA: contents of the fake remote file served by FakeFTP downloads
DATA = b'0123456789'

# FakeFTP: mock ftplib.FTP serving LIST lines and a downloadable file, with scripted behaviour per connection
class FakeFTP:
    # modes are consumed one per retrbinary call: ok, drop (half then reset), short (all but one byte), perm
    def __init__(self, lines: list[str] | None = None, modes: list[str] | None = None) -> None:
        self.lines = lines or []
        self.modes = modes or []
        self.cwd_path = ''
        self.rests: list[int | None] = []
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
    def size(self, name: str) -> int:
        return len(DATA)
    def retrbinary(self, cmd: str, callback: Callable[[bytes], None], blocksize: int = 8192, rest: int | None = None) -> None:
        self.rests.append(rest)
        mode = self.modes.pop(0)
        if mode == 'perm':
            raise ftplib.error_perm('550 no such file')
        chunk = DATA[rest or 0 :]
        if mode == 'drop':
            callback(chunk[: len(chunk) // 2])
            raise ConnectionResetError
        callback(chunk[:-1] if mode == 'short' else chunk)

# FakeHTTP: mock urlopen serving DATA with Range support, scripted behaviour per request
class FakeHTTP:
    # modes are consumed one per request: ok, drop (half then reset), short (all but one byte), perm (404), norange (200 with full body)
    def __init__(self, modes: list[str]) -> None:
        self.modes = modes
        self.starts: list[int] = []
    def __call__(self, request: object, timeout: float = 30) -> '_Response':
        start = int(request.get_header('Range', 'bytes=0-')[6:-1])
        self.starts.append(start)
        if start > len(DATA):
            raise urllib.error.HTTPError(request.full_url, 416, 'range', {}, None)
        mode = self.modes.pop(0)
        if mode == 'perm':
            raise urllib.error.HTTPError(request.full_url, 404, 'not found', {}, None)
        if mode == 'norange':
            start = 0
        body = DATA[start:]
        return _Response(body, 206 if start else 200, drop=mode == 'drop', short=mode == 'short')

# _Response: context-manager response yielding body, optionally failing midway or ending a byte early
class _Response:
    def __init__(self, body: bytes, status: int, *, drop: bool, short: bool) -> None:
        self.status = status
        self.headers = {'Content-Length': str(len(body))}
        self.body = body[:-1] if short else body
        self.drop = drop
        self.sent = False
    def __enter__(self) -> '_Response':
        return self
    def __exit__(self, *args: object) -> bool:
        return False
    def read(self, size: int) -> bytes:
        if self.sent:
            if self.drop:
                raise ConnectionResetError
            return b''
        self.sent = True
        return self.body[: len(self.body) // 2] if self.drop else self.body

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

# download_http: installer to swap urlopen for a FakeHTTP scripted with the given download modes
@pytest.fixture
def download_http(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[str]], FakeHTTP]:
    def install(modes: list[str]) -> FakeHTTP:
        fake = FakeHTTP(modes)
        monkeypatch.setattr(empiar.urllib.request, 'urlopen', fake)
        return fake
    return install

# download_ftp: installer to swap ftplib.FTP for a FakeFTP scripted with the given download modes
@pytest.fixture
def download_ftp(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[str]], FakeFTP]:
    def install(modes: list[str]) -> FakeFTP:
        fake = FakeFTP(modes=modes)
        monkeypatch.setattr(empiar.ftplib, 'FTP', fake)
        return fake
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
