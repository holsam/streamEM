'''
streamem: tests for download retry, resume and verification
'''

# Import external dependencies
import ftplib, pytest, threading
from pathlib import Path

# Import internal streamem objects
from streamem.utils import empiar

# DATA: a fake remote file
DATA = b'0123456789'

# _FakeFTP: mock ftplib.FTP with scripted behaviour per connection
class _FakeFTP:
    # __init__: modes are consumed in order: ok, drop (half then reset), short (all but one byte), perm
    def __init__(self, modes: list[str]) -> None:
        self.modes = modes
        self.rests: list[int | None] = []
    # __call__: acts as the FTP(...) constructor
    def __call__(self, *args: object, **kwargs: object) -> '_FakeFTP':
        return self
    def __enter__(self) -> '_FakeFTP':
        return self
    def __exit__(self, *args: object) -> bool:
        return False
    def login(self) -> None:
        pass
    def cwd(self, path: str) -> None:
        pass
    def size(self, name: str) -> int:
        return len(DATA)
    def retrbinary(self, cmd: str, callback, blocksize: int = 8192, rest: int | None = None) -> None:
        self.rests.append(rest)
        mode = self.modes.pop(0)
        if mode == 'perm':
            raise ftplib.error_perm('550 no such file')
        chunk = DATA[rest or 0 :]
        if mode == 'drop':
            callback(chunk[: len(chunk) // 2])
            raise ConnectionResetError
        callback(chunk[:-1] if mode == 'short' else chunk)

# _run: download with the given scripted modes, returns the fake for inspection
def _run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, modes: list[str], **kwargs: int) -> _FakeFTP:
    fake = _FakeFTP(modes)
    monkeypatch.setattr(empiar.ftplib, 'FTP', fake)
    empiar.download('1', 'data/s', 'f.mrc', tmp_path / 'f.mrc', threading.Event(), backoff=0, **kwargs)
    return fake

# test_resume_after_drop: second attempt asks for the remaining bytes only
def test_resume_after_drop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = _run(monkeypatch, tmp_path, ['drop', 'ok'])
    assert fake.rests == [None, 5]
    assert (tmp_path / 'f.mrc').read_bytes() == DATA
    assert not (tmp_path / 'f.mrc.part').exists()

# test_truncated_is_retried: a short but clean transfer fails verification and resumes
def test_truncated_is_retried(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = _run(monkeypatch, tmp_path, ['short', 'ok'])
    assert fake.rests == [None, 9]
    assert (tmp_path / 'f.mrc').read_bytes() == DATA

# test_permanent_error_not_retried: error_perm fails at once and leaves no part file
def test_permanent_error_not_retried(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = _FakeFTP(['perm'])
    monkeypatch.setattr(empiar.ftplib, 'FTP', fake)
    with pytest.raises(ftplib.error_perm):
        empiar.download('1', 'data/s', 'f.mrc', tmp_path / 'f.mrc', threading.Event(), backoff=0)
    assert len(fake.rests) == 1
    assert not (tmp_path / 'f.mrc.part').exists()

# test_retries_exhausted: gives up after retries, deletes the part file
def test_retries_exhausted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(empiar.ftplib, 'FTP', _FakeFTP(['drop'] * 3))
    with pytest.raises(ConnectionResetError):
        empiar.download('1', 'data/s', 'f.mrc', tmp_path / 'f.mrc', threading.Event(), retries=2, backoff=0)
    assert not (tmp_path / 'f.mrc.part').exists()

# test_stop_interrupts_backoff: a set stop turns the first retry into InterruptedError
def test_stop_interrupts_backoff() -> None:
    stop = threading.Event()
    stop.set()
    # fail: always a transient error
    def fail() -> None:
        raise ConnectionResetError
    with pytest.raises(InterruptedError):
        empiar._retry(fail, stop, retries=3, backoff=1000)
