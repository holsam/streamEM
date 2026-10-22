'''
streamem: EMPIAR REST API and FTP access
'''

# Import external dependencies
import ftplib, json, re, urllib.request
from dataclasses import dataclass

# FTP_HOST: EMPIAR public FTP server
FTP_HOST = 'ftp.ebi.ac.uk'

# API_URL: EMPIAR REST entry endpoint
API_URL = 'https://www.ebi.ac.uk/empiar/api/entry/EMPIAR-{number}/'

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

# list_files: use FTP MLSD listing to retrieve files in an image set directory
def list_files(entry: str, directory: str) -> list[RemoteFile]:
    path = f'/empiar/world_availability/{entry_number(entry)}/{directory}'
    with ftplib.FTP(FTP_HOST, timeout=60) as ftp:
        ftp.login()
        ftp.cwd(path)
        return [RemoteFile(name, int(facts['size'])) for name, facts in ftp.mlsd(facts=['size', 'type']) if facts.get('type') == 'file']
