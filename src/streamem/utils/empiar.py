'''
streamem: EMPIAR REST API, FTP listing and HTTPS mirror download
'''

# Import external dependencies
import ftplib, json, logging, re, threading, urllib.error, urllib.parse, urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# FTP_HOST: EMPIAR public FTP server
FTP_HOST = 'ftp.ebi.ac.uk'

# MIRROR_URL: PDBj HTTPS mirror of an EMPIAR file, optional alternative to EBI FTP
MIRROR_URL = 'https://ftp.empiar.pdbj.org/archive/{number}/{directory}/{name}'

# API_URL: EMPIAR REST entry endpoint
API_URL = 'https://www.ebi.ac.uk/empiar/api/entry/EMPIAR-{number}/'

# RETRIES: number of additional attempts tried after a transient FTP failure
RETRIES = 8

# BACKOFF: number of seconds before the first retry, doubling each time
BACKOFF = 5.0

# MAX_BACKOFF: longest wait in seconds between two retries
MAX_BACKOFF = 120.0

# TRANSIENT: errors which count as a transient FTP failure
TRANSIENT = (OSError, EOFError, ftplib.error_temp, ftplib.error_proto)

# log: module logger
log = logging.getLogger(__name__)

# ImageSet: an image set from EMPIAR (i.e. a sub-dataset of entry)
@dataclass(frozen=True)
class ImageSet:
    name: str
    directory: str
    category: str
    data_format: str
    count: int

# RemoteFile: a file on EMPIAR FTP server
@dataclass(frozen=True)
class RemoteFile:
    name: str
    size: int

# _list: list a directory from EMPIAR
def _list(entry: str, directory: str) -> list[RemoteFile]:
    path = f'/empiar/world_availability/{entry_number(entry)}/{directory}'
    lines: list[str] = []
    with ftplib.FTP(FTP_HOST, timeout=60) as ftp:
        ftp.login()
        ftp.cwd(path)
        ftp.retrlines('LIST', lines.append)
    # unix ls -l format: perms links owner group size month day time/year name, names may hold spaces
    rows = [line.split(maxsplit=8) for line in lines if line.startswith('-')]
    return [RemoteFile(row[8], int(row[4])) for row in rows]

# _fetch_ftp: fetch part of a file, appending to existing parts if already exists
def _fetch_ftp(entry: str, directory: str, name: str, part: Path, stop: threading.Event) -> None:
    with ftplib.FTP(FTP_HOST, timeout=60) as ftp:
        ftp.login()
        ftp.cwd(f'/empiar/world_availability/{entry_number(entry)}/{directory}')
        total = ftp.size(name)
        if total is None:
            raise ftplib.error_proto(f'no size for {name!r}')
        have = part.stat().st_size if part.exists() else 0
        if have > total:
            # a longer part cannot belong to this file, start again
            part.unlink()
            have = 0
        if have < total:
            with part.open('ab') as out:
                # write: stream one block to disk
                def write(block: bytes) -> None:
                    if stop.is_set():
                        raise InterruptedError
                    out.write(block)
                ftp.retrbinary(f'RETR {name}', write, blocksize=1 << 20, rest=have or None)
    if part.stat().st_size != total:
        raise EOFError(f'{name!r} truncated at {part.stat().st_size} of {total} bytes')

# _fetch_http: fetch part of a file over HTTPS, appending to an existing part with a Range request
def _fetch_http(entry: str, directory: str, name: str, part: Path, stop: threading.Event) -> None:
    url = MIRROR_URL.format(number=entry_number(entry), directory=directory, name=urllib.parse.quote(name))
    have = part.stat().st_size if part.exists() else 0
    request = urllib.request.Request(url, headers={'Range': f'bytes={have}-'} if have else {})
    try:
        response = urllib.request.urlopen(request, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code != 416 or not have:
            raise
        # part is not a prefix of this file (or already complete), start again
        part.unlink()
        return _fetch_http(entry, directory, name, part, stop)
    with response:
        if have and response.status != 206:
            # server ignored the range, take the whole body
            have = 0
        total = have + int(response.headers['Content-Length'])
        with part.open('ab' if have else 'wb') as out:
            while block := response.read(1 << 20):
                if stop.is_set():
                    raise InterruptedError
                out.write(block)
    if part.stat().st_size != total:
        raise EOFError(f'{name!r} truncated at {part.stat().st_size} of {total} bytes')

# _retry: call a given function, retrying transient errors with an exponential backoff that stop interrupts
def _retry[T](fn: Callable[[], T], stop: threading.Event, *, retries: int, backoff: float, what: str = '') -> T:
    for attempt in range(retries + 1):
        try:
            return fn()
        except InterruptedError:
            raise
        except TRANSIENT as exc:
            # a 4xx other than 429 will not change on retry
            if isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500 and exc.code != 429:
                raise
            if attempt == retries:
                raise
            wait = min(backoff * 2**attempt, MAX_BACKOFF)
            log.warning('%s: retry %d of %d in %.0fs after %r', what, attempt + 1, retries, wait, exc)
            if stop.wait(wait):
                raise InterruptedError from None
    raise AssertionError('unreachable')

# entry_number: parses entered entry numbers (as either '<number>' or 'EMPIAR-<number>'), returning <number>
def entry_number(entry: str) -> str:
    match = re.fullmatch(r'(?:EMPIAR-)?(\d+)', entry.strip(), re.IGNORECASE)
    if match is None:
        raise ValueError(f'invalid EMPIAR entry {entry!r}')
    return match.group(1)

# fetch_entry: uses REST API to retrieve title and image sets of an entry
def fetch_entry(entry: str) -> tuple[str, list[ImageSet]]:
    number = entry_number(entry)
    with urllib.request.urlopen(API_URL.format(number=number), timeout=30) as response:
        data = json.load(response)[f'EMPIAR-{number}']
    sets = [ImageSet(s['name'], s['directory'], s['category'], s['data_format'], s['num_images_or_tilt_series']) for s in data['imagesets']]
    return data['title'], sets

# list_files: files in an image set directory, sizes parsed from an FTP LIST, with retry support
def list_files(entry: str, directory: str) -> list[RemoteFile]:
    return _retry(lambda: _list(entry, directory), threading.Event(), retries=RETRIES, backoff=BACKOFF, what=f'list {directory}')

# match_pairs: files of two sets that share a stem, plus the number of files left without a partner
def match_pairs(first: list[RemoteFile], second: list[RemoteFile]) -> tuple[list[tuple[RemoteFile, RemoteFile]], int]:
    by_stem = {Path(f.name).stem: f for f in second}
    pairs = [(f, by_stem[Path(f.name).stem]) for f in first if Path(f.name).stem in by_stem]
    return pairs, len(first) + len(second) - 2 * len(pairs)

# download: fetch one file to dest, from EBI FTP or (with mirror) the PDBj HTTPS mirror, with resume/retry support, falling back to the other source after half the retries or a permanent error, aborting once stop is set
def download(
    entry: str,
    directory: str,
    name: str,
    dest: Path,
    stop: threading.Event,
    *,
    mirror: bool = False,
    retries: int = RETRIES,
    backoff: float = BACKOFF,
) -> None:
    part = dest.with_name(dest.name + '.part')
    first, second = (_fetch_http, _fetch_ftp) if mirror else (_fetch_ftp, _fetch_http)
    # first half of the attempts use the chosen source, the rest fall back to the other
    split = max(1, (retries + 1) // 2)
    what = f'{directory}/{name}'
    try:
        try:
            _retry(lambda: first(entry, directory, name, part, stop), stop, retries=split - 1, backoff=backoff, what=what)
        except InterruptedError:
            raise
        except Exception as exc:
            # exhausted transient retries or a permanent error: either way try the other source
            log.warning('%s: falling back to %s after %r', what, second.__name__, exc)
            _retry(lambda: second(entry, directory, name, part, stop), stop, retries=max(0, retries - split), backoff=backoff, what=what)
        part.rename(dest)
    except TRANSIENT:
        # keep part files as next run can resume from it
        raise
    except BaseException:
        part.unlink(missing_ok=True)
        raise
