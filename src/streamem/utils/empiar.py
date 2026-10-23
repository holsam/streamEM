'''
streamem: EMPIAR REST API and FTP access
'''

# Import external dependencies
import ftplib, json, re, threading, urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# FTP_HOST: EMPIAR public FTP server
FTP_HOST = 'ftp.ebi.ac.uk'

# API_URL: EMPIAR REST entry endpoint
API_URL = 'https://www.ebi.ac.uk/empiar/api/entry/EMPIAR-{number}/'

# RETRIES: number of additional attempts tried after a transient FTP failure
RETRIES = 5

# BACKOFF: number of seconds before the first retry, doubling each time
BACKOFF = 5.0

# TRANSIENT: errors which count as a transient FTP failure
TRANSIENT = (OSError, EOFError, ftplib.error_temp, ftplib.error_proto)

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

# _fetch_part: fetch part of a file, appending to existing parts if already exists
def _fetch_part(entry: str, directory: str, name: str, part: Path, stop: threading.Event) -> None:
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

# _retry: call a given function, retrying transient errors with an exponential backoff that stop interrupts
def _retry[T](fn: Callable[[], T], stop: threading.Event, *, retries: int, backoff: float) -> T:
    for attempt in range(retries + 1):
        try:
            return fn()
        except InterruptedError:
            raise
        except TRANSIENT:
            if attempt == retries:
                raise
            if stop.wait(backoff * 2**attempt):
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
    return _retry(lambda: _list(entry, directory), threading.Event(), retries=RETRIES, backoff=BACKOFF)

# download: fetch one file over FTP to dest, with resume/retry support, aborting once stop is set
def download(
    entry: str,
    directory: str,
    name: str,
    dest: Path,
    stop: threading.Event,
    *,
    retries: int = RETRIES,
    backoff: float = BACKOFF,
) -> None:
    part = dest.with_name(dest.name + '.part')
    try:
        _retry(lambda: _fetch_part(entry, directory, name, part, stop), stop, retries=retries, backoff=backoff)
        part.rename(dest)
    except InterruptedError:
        # keep part files as next run can resume from it
        raise
    except BaseException:
        part.unlink(missing_ok=True)
        raise
