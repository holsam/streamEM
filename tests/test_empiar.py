'''
streamem: tests for EMPIAR REST and FTP access
'''

# Import external dependencies
import ftplib, pytest, threading, urllib.error
from pathlib import Path

# Import internal streamem objects
from conftest import DATA
from streamem.utils import empiar
from streamem.utils.empiar import RemoteFile, entry_number, fetch_entry, list_files

# TestEntryNumber: both ID spellings normalise
class TestEntryNumber:
    # test_spellings: bare number, prefixed and padded forms all give the number
    def test_spellings(self) -> None:
        assert entry_number('EMPIAR-11830') == entry_number(' 11830 ') == entry_number('empiar-11830') == '11830'

    # test_rejects_junk: anything else is a ValueError naming the input
    @pytest.mark.parametrize('bad', ['abc', '', 'EMPIAR-', 'EMPIAR-12a', '11830/../x'])
    def test_rejects_junk(self, bad: str) -> None:
        with pytest.raises(ValueError, match='invalid EMPIAR entry'):
            entry_number(bad)

# TestFetchEntry: REST response parsing
class TestFetchEntry:
    # test_title_and_sets: title and every image set field are read
    def test_title_and_sets(self, remote) -> None:
        title, sets = fetch_entry('11830')
        assert title == 'Test entry'
        assert [s.directory for s in sets] == ['data/raw', 'data/denoised']
        assert (sets[1].name, sets[1].category, sets[1].data_format, sets[1].count) == (
            'Denoised tomograms', 'reconstructed volumes', 'MRC', 3,
        )

    # test_accepts_prefixed_id: the EMPIAR- prefix is optional
    def test_accepts_prefixed_id(self, remote) -> None:
        assert fetch_entry('EMPIAR-11830')[0] == 'Test entry'

# TestListFiles: FTP LIST parsing
class TestListFiles:
    # test_files_only: the directory line is skipped, names with spaces survive
    def test_files_only(self, remote) -> None:
        files = list_files('11830', 'data/denoised')
        assert sorted(files, key=lambda f: f.name) == [
            RemoteFile('a.mrc', 3000), RemoteFile('b with space.mrc', 2000), RemoteFile('c.mrc', 1000),
        ]

    # test_remote_path: the entry number and directory build the world_availability path
    def test_remote_path(self, remote) -> None:
        list_files('EMPIAR-11830', 'data/denoised')
        assert remote.cwd_path == '/empiar/world_availability/11830/data/denoised'

    # test_empty_directory: no files gives an empty list
    def test_empty_directory(self, fake_ftp) -> None:
        fake_ftp(['drwxr-xr-x    2 ftp      ftp          4096 Feb 28  2025 subdir'])
        assert list_files('1', 'data/x') == []

    # test_bad_entry: validation happens before any connection
    def test_bad_entry(self, remote) -> None:
        with pytest.raises(ValueError):
            list_files('nope', 'data/x')


# TestDownload: retry, resume and verification
class TestDownload:
    # run: download f.mrc into tmp_path with the given scripted modes
    @staticmethod
    def run(tmp_path: Path, stop: threading.Event | None = None, **kwargs: int) -> None:
        empiar.download('1', 'data/s', 'f.mrc', tmp_path / 'f.mrc', stop or threading.Event(), backoff=0, **kwargs)

    # test_resume_after_drop: second attempt asks for the remaining bytes only
    def test_resume_after_drop(self, download_ftp, tmp_path: Path) -> None:
        fake = download_ftp(['drop', 'ok'])
        self.run(tmp_path)
        assert fake.rests == [None, 5]
        assert (tmp_path / 'f.mrc').read_bytes() == DATA
        assert not (tmp_path / 'f.mrc.part').exists()

    # test_truncated_is_retried: a short but clean transfer fails verification and resumes
    def test_truncated_is_retried(self, download_ftp, tmp_path: Path) -> None:
        fake = download_ftp(['short', 'ok'])
        self.run(tmp_path)
        assert fake.rests == [None, 9]
        assert (tmp_path / 'f.mrc').read_bytes() == DATA

    # test_permanent_error_not_retried: error_perm fails at once and leaves no part file
    def test_permanent_error_not_retried(self, download_ftp, tmp_path: Path) -> None:
        fake = download_ftp(['perm'])
        with pytest.raises(ftplib.error_perm):
            self.run(tmp_path)
        assert len(fake.rests) == 1
        assert not (tmp_path / 'f.mrc.part').exists()

    # test_retries_exhausted: gives up after retries, keeps the part file so a rerun can resume
    def test_retries_exhausted(self, download_ftp, tmp_path: Path) -> None:
        download_ftp(['drop'] * 3)
        with pytest.raises(ConnectionResetError):
            self.run(tmp_path, retries=2)
        assert (tmp_path / 'f.mrc.part').exists()
        assert not (tmp_path / 'f.mrc').exists()

    # test_rerun_resumes_kept_part: a fresh download after exhaustion asks only for the remaining bytes
    def test_rerun_resumes_kept_part(self, download_ftp, tmp_path: Path) -> None:
        fake = download_ftp(['drop'] * 3 + ['ok'])
        with pytest.raises(ConnectionResetError):
            self.run(tmp_path, retries=2)
        have = (tmp_path / 'f.mrc.part').stat().st_size
        self.run(tmp_path)
        assert fake.rests[-1] == have
        assert (tmp_path / 'f.mrc').read_bytes() == DATA

    # test_stop_keeps_part: an interrupted download keeps its part file for the next run to resume
    def test_stop_keeps_part(self, download_ftp, tmp_path: Path) -> None:
        download_ftp(['ok'])
        stop = threading.Event()
        stop.set()
        with pytest.raises(InterruptedError):
            self.run(tmp_path, stop)
        assert (tmp_path / 'f.mrc.part').exists()
        assert not (tmp_path / 'f.mrc').exists()

    # test_oversized_part_restarts: a part longer than the remote file is discarded and fetched from the start
    def test_oversized_part_restarts(self, download_ftp, tmp_path: Path) -> None:
        fake = download_ftp(['ok'])
        (tmp_path / 'f.mrc.part').write_bytes(b'x' * 20)
        self.run(tmp_path)
        assert fake.rests == [None]
        assert (tmp_path / 'f.mrc').read_bytes() == DATA

    # test_stop_interrupts_backoff: a set stop turns the first retry into InterruptedError
    def test_stop_interrupts_backoff(self) -> None:
        stop = threading.Event()
        stop.set()
        # fail: always a transient error
        def fail() -> None:
            raise ConnectionResetError
        with pytest.raises(InterruptedError):
            empiar._retry(fail, stop, retries=3, backoff=1000)

    # test_backoff_is_capped: waits double then stay at MAX_BACKOFF
    def test_backoff_is_capped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        waits: list[float] = []
        stop = threading.Event()
        # record: log the requested wait and report no stop
        monkeypatch.setattr(stop, 'wait', lambda timeout: waits.append(timeout) or False)
        # fail: always a transient error
        def fail() -> None:
            raise ConnectionResetError
        with pytest.raises(ConnectionResetError):
            empiar._retry(fail, stop, retries=4, backoff=50)
        assert waits == [50, 100, empiar.MAX_BACKOFF, empiar.MAX_BACKOFF]

    # test_retry_is_logged: each retry names the file and the error
    def test_retry_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level('WARNING', logger='streamem')
        calls = iter([ConnectionResetError('boom'), None])

        # flaky: fail once, then work
        def flaky() -> None:
            if (item := next(calls)) is not None:
                raise item

        empiar._retry(flaky, threading.Event(), retries=1, backoff=0, what='data/f.mrc')
        assert 'data/f.mrc: retry 1 of 1' in caplog.text
        assert 'boom' in caplog.text

# TestMirrorDownload: HTTPS mirror retry, resume and verification
class TestMirrorDownload:
    # run: download f.mrc into tmp_path with the given scripted modes
    @staticmethod
    def run(tmp_path: Path, stop: threading.Event | None = None, **kwargs: int) -> None:
        empiar.download('1', 'data/s', 'f.mrc', tmp_path / 'f.mrc', stop or threading.Event(), mirror=True, backoff=0, **kwargs)

    # test_resume_after_drop: second attempt asks for the remaining bytes only
    def test_resume_after_drop(self, download_http, tmp_path: Path) -> None:
        fake = download_http(['drop', 'ok'])
        self.run(tmp_path)
        assert fake.starts == [0, 5]
        assert (tmp_path / 'f.mrc').read_bytes() == DATA
        assert not (tmp_path / 'f.mrc.part').exists()

    # test_truncated_is_retried: a short but clean transfer fails verification and resumes
    def test_truncated_is_retried(self, download_http, tmp_path: Path) -> None:
        fake = download_http(['short', 'ok'])
        self.run(tmp_path)
        assert fake.starts == [0, 9]
        assert (tmp_path / 'f.mrc').read_bytes() == DATA

    # test_permanent_error_not_retried: a 404 fails at once and leaves no part file
    def test_permanent_error_not_retried(self, download_http, tmp_path: Path) -> None:
        fake = download_http(['perm'])
        with pytest.raises(urllib.error.HTTPError):
            self.run(tmp_path)
        assert len(fake.starts) == 1
        assert not (tmp_path / 'f.mrc.part').exists()

    # test_retries_exhausted: gives up after retries, keeps the part file so a rerun can resume
    def test_retries_exhausted(self, download_http, tmp_path: Path) -> None:
        download_http(['drop'] * 3)
        with pytest.raises(ConnectionResetError):
            self.run(tmp_path, retries=2)
        assert (tmp_path / 'f.mrc.part').exists()
        assert not (tmp_path / 'f.mrc').exists()

    # test_rerun_resumes_kept_part: a fresh download after exhaustion asks only for the remaining bytes
    def test_rerun_resumes_kept_part(self, download_http, tmp_path: Path) -> None:
        fake = download_http(['drop'] * 3 + ['ok'])
        with pytest.raises(ConnectionResetError):
            self.run(tmp_path, retries=2)
        have = (tmp_path / 'f.mrc.part').stat().st_size
        self.run(tmp_path)
        assert fake.starts[-1] == have
        assert (tmp_path / 'f.mrc').read_bytes() == DATA

    # test_stop_keeps_part: an interrupted download keeps its part file for the next run to resume
    def test_stop_keeps_part(self, download_http, tmp_path: Path) -> None:
        download_http(['ok'])
        stop = threading.Event()
        stop.set()
        with pytest.raises(InterruptedError):
            self.run(tmp_path, stop)
        assert (tmp_path / 'f.mrc.part').exists()
        assert not (tmp_path / 'f.mrc').exists()

    # test_oversized_part_restarts: a part longer than the remote file is discarded and fetched from the start
    def test_oversized_part_restarts(self, download_http, tmp_path: Path) -> None:
        fake = download_http(['ok'])
        (tmp_path / 'f.mrc.part').write_bytes(b'x' * 20)
        self.run(tmp_path)
        # first request at 20 gets a 416, then the part is dropped and refetched from 0
        assert fake.starts == [20, 0]
        assert (tmp_path / 'f.mrc').read_bytes() == DATA
