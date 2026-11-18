# streamEM

Chunked processing of EMPIAR data. streamEM downloads one file from an EMPIAR entry at a time, executes the given command/script, deletes the raw file, and repeats.

## Installation

streamEM requires Python ≥3.14. For installation/dependency management, `uv` is recommended:

```sh
uv tool install git+https://github.com/holsam/streamem

streamem --help
```

## Workflow

streamEM has three subcommands: `plan`, `run`, `status`.

### 1. `plan`

```bash
streamem plan
```

Interactively steps through a series of questions to plan the streamEM run:
- EMPIAR entry ID (e.g. `EMPIAR-10025` or `10025`).
- Which image set(s) to process. Pick two to pair them by file stem (e.g. movies and gain references, or raw and aligned images).
- Per image set: optional subset (first N alphabetically, or N random with a stored seed), the command to run, and the output directory.
- Scratch directory for downloads, storage limit (GB) and number of workers. Max workers will be capped so the number of concurrent raw files always fits within the storage limit.
- Optionally create a SLURM script (partition, time, memory, extra `--resource=request` lines).

A preview of the plan will be shown, then written to a TOML file (default: `streamem.toml`) and, if requested, an sbatch file (`streamem.sbatch`).

### 2. `run`

```bash
streamem run streamem.toml
streamem run streamem.toml --retry-failed [--only fetch|exec]
```

Lists all files, registers them in a SQLite manifest beside the config (default: `streamem.db`), then begins each loop of: downloading file, running command, deleting raw file(s), recordingg outcome.

`run` is resumable, and re-running the same command after an interruption or crash will skip completed (and failed, unless `--retry-failed` used) files, requeue interrupted files and resume processing. `Ctrl+C` stops the ongoing run and requeues any in-progress files. Paired files that are unmatched are skipped with a note if present. `--only fetch` or `--only exec` limits `--retry-failed` to files which previously failed during download/command stages respectively.

### 3. `status`

```bash
streamem status streamem.toml
streamem status streamem.toml --limit 50
```

Read progress from a streamEM run, showing the counts per image set and status. Failed files will be listed with their errors up to the number given by `--limit` (default: 20).

## Commands

The command is run through the shell, once per file. Placeholders are substituted (shell-quoted) before running, and are exported to environment variables:

Placeholder | Exported environment variable | Value
-- | -- | --
`{file}` | `STREAMEM_FILE` | Path to downloaded file
`{outdir}` | `STREAMEM_OUTDIR` | Per-file output directory (`<outdir>/<stem>/`)
`{name}` | `STREAMEM_NAME` | File stem (name without extension)
`{pair}` | `STREAMEM_PAIR` | Path to paired file (paired runs only)

The output of each command is saved to `<outdir>/<stem>/streamem.log`, with non-zero exits marking the file as failed.

Example:

```toml
cmd = "my_tool --input {file} --output {outdir}/{name}.mrc"
```

## Config

`plan` writes TOML, which can be edited by hand as required:

```toml
entry = "EMPIAR-10025"
workdir = "scratch"
budget_gb = 200.0
margin = 0.8
workers = 4

[[subdatasets]]
name = "Raw movies"
directory = "data/movies"
cmd = "my_tool {file} {outdir}"
outdir = "results/movies"
n_files = 100
mean_bytes = 1000000000
max_bytes = 1200000000
subset = 100          # optional, omit for all files
order = "random"      # alphabetical (default) or random
seed = 12345
pair_with = "Gain"    # optional, name of the partner image set
```
