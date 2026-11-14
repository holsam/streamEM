'''
streamem: run configuration schema and TOML IO
'''

# Import external dependencies
import tomli_w, tomllib
from pathlib import Path
from pydantic import BaseModel, Field, model_validator
from typing import Self

# Import internal streamem objects
from streamem.utils.subset import Order

# SubDataset: an image set for processing & command to run on each image
class SubDataset(BaseModel):
    name: str
    directory: str
    cmd: str
    outdir: Path
    n_files: int
    mean_bytes: int
    max_bytes: int
    subset: int | None = Field(default=None, ge=1)
    order: Order = 'alphabetical'
    seed: int = 0
    # pair_with: name of the sub-dataset whose same-stem file is fetched alongside each file of this one
    pair_with: str | None = None

# footprint: largest raw data one worker holds at once, a pair counting both files
def footprint(subs: list[SubDataset]) -> int:
    by_name = {s.name: s for s in subs}
    partners = {s.pair_with for s in subs if s.pair_with is not None}
    return max(
        s.max_bytes + (by_name[s.pair_with].max_bytes if s.pair_with is not None else 0)
        for s in subs
        if s.name not in partners
    )

# Config: all config values needed for run command
class Config(BaseModel):
    entry: str
    workdir: Path
    budget_gb: float = Field(gt=0)
    margin: float = Field(default=0.8, gt=0, le=1)
    workers: int = Field(ge=1)
    subdatasets: list[SubDataset]

    # primaries: sub-datasets that own manifest rows, i.e. those not consumed as a partner
    def primaries(self) -> list[SubDataset]:
        partners = {s.pair_with for s in self.subdatasets}
        return [s for s in self.subdatasets if s.name not in partners]

    # partner: the sub-dataset paired with sub, if any
    def partner(self, sub: SubDataset) -> SubDataset | None:
        return next((s for s in self.subdatasets if s.name == sub.pair_with), None)

    # _check_pairs: pair_with names must exist, be unique, and not chain
    @model_validator(mode='after')
    def _check_pairs(self) -> Self:
        by_name = {s.name: s for s in self.subdatasets}
        partners = [s.pair_with for s in self.subdatasets if s.pair_with is not None]
        if len(set(partners)) != len(partners):
            raise ValueError('a sub-dataset can be the partner of only one other')
        for name in partners:
            if name not in by_name:
                raise ValueError(f'unknown pair_with {name!r}')
            if by_name[name].pair_with is not None:
                raise ValueError(f'{name!r} cannot be both a partner and paired')
        return self

# load_config: read config from TOML file
def load_config(path: Path) -> Config:
    return Config.model_validate(tomllib.loads(path.read_text()))

# write_config: write config to TOML file, unset values (None) are left out
def write_config(config: Config, path: Path) -> None:
    path.write_text(tomli_w.dumps(config.model_dump(mode='json', exclude_none=True)))
