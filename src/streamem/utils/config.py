'''
streamem: run configuration schema and TOML IO
'''

# Import external dependencies
import tomli_w, tomllib
from pathlib import Path
from pydantic import BaseModel, Field

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

# Config: all config values needed for run command
class Config(BaseModel):
    entry: str
    workdir: Path
    budget_gb: float = Field(gt=0)
    margin: float = Field(default=0.8, gt=0, le=1)
    workers: int = Field(ge=1)
    subdatasets: list[SubDataset]

# load_config: read config from TOML file
def load_config(path: Path) -> Config:
    return Config.model_validate(tomllib.loads(path.read_text()))

# write_config: write config to TOML file, unset values (None) are left out
def write_config(config: Config, path: Path) -> None:
    path.write_text(tomli_w.dumps(config.model_dump(mode='json', exclude_none=True)))
