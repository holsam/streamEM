'''
streamem: deterministic selection of a subset of remote files
'''

# Import external dependencies
import random
from typing import Literal

# Import internal streamem objects
from streamem.utils.empiar import RemoteFile

# Order: how a subset is picked from the sorted file names
Order = Literal['alphabetical', 'random']

# select_files: all files by name, or the first/a seeded random sample of subset files, always returned sorted
def select_files(files: list[RemoteFile], subset: int | None, order: Order = 'alphabetical', seed: int = 0) -> list[RemoteFile]:
    ordered = sorted(files, key=lambda f: f.name)
    if subset is None or subset >= len(ordered):
        return ordered
    if order == 'alphabetical':
        return ordered[:subset]
    return sorted(random.Random(seed).sample(ordered, subset), key=lambda f: f.name)
