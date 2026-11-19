# Terminal App

`terminal_app` is a Python utility package for terminal-oriented automation.
It groups helpers for:

- configuration loading from `.env`, `.yaml`, `.yml`, and `.json` files;
- logging to files and terminal streams;
- request helpers for SSH, cURL conversion, and browser/proxy automation;
- processing pipelines;
- formatting, path, and general-purpose utility functions.

## Installation

Activate the project environment and install the package in editable mode:

```bash
# locally
pip install -e .
# remote
pip install "terminal_app @ git+https://github.com/axtonio/terminal_app.git"
```

If you need optional integrations, install the relevant extras:

```bash
# locally
pip install -e ".[request_utils]"
pip install -e ".[google_sheets]"

# remote
pip install "terminal_app[request_utils] @ git+https://github.com/axtonio/terminal_app.git"
pip install "terminal_app[google_sheets] @ git+https://github.com/axtonio/terminal_app.git"
```

## Python Usage

```python
from terminal_app.env import source
from terminal_app.logging import register_logger
from terminal_app.utils import AllParams

config = source("configs/dev/.terminal.env")
logger = register_logger("logs/app.log", name="app")
params = AllParams({"a": 1, "b": 2})

logger.info("Loaded %s keys", len(config))
print(params["all_params"] is params)
```

## Main Modules

- `terminal_app.env` for project configuration and `.env` / YAML / JSON loading.
- `terminal_app.logging` for file-backed loggers and terminal-aware handlers.
- `terminal_app.request_utils` for SSH, browser, and cURL helpers.
- `terminal_app.processing_utils` for staged file processing pipelines.
- `terminal_app.utils` for small reusable helpers and formatting utilities.

## Development

Use Python 3.11 and an isolated development environment. Install the optional
integrations too: quality checks inspect all production modules, including the
browser, SSH and Google Sheets helpers.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,request_utils,google_sheets]"
make format PYTHON=python
make quality PYTHON=python
python -m pytest -q
```

The repository vendors the shared Templates Python quality profile in
`.quality/`; its release is recorded in `.quality/VERSION`. `make format` sorts
imports and formats production code. `make quality` checks formatting, imports,
types, complexity, module size, architecture and unused code without changing
source files. The profile covers `src`; tests also provide references for the
unused-code analysis.

Analyzers and their pinned dependencies are installed automatically in a separate
`.quality-venv`. Keep the application's environment active when running either
Make target. Review formatting changes before committing. To run the same
quality check automatically before commits:

```bash
.quality-venv/bin/pre-commit install
```

GitHub Actions runs `make quality PYTHON=python` and the test suite on pull
requests and pushes to `main`, using Python 3.11. These tests run locally without
service credentials, browser sessions or calls to external integrations.

## Composable processing

`SequenceStages` passes successful items to its next child. `ParallelStages`
passes a separate metadata snapshot of the same input to every child and merges
only the fields each branch changed. Branch execution is currently sequential.
Conflicting edits reject the affected item with an explicit error.

```python
from pathlib import Path
from terminal_app.processing_utils.core import ParallelStages, SequenceStages, run_stages
from terminal_app.processing_utils.types import StageItem

pipeline = SequenceStages("evaluation", [
    prepare_stage,
    ParallelStages("metrics", [distance_stage, overlap_stage], pass_condition=any),
])
results = run_stages(
    [pipeline],
    filtered_files=[StageItem("attempt-1", Path("sample.py"), {})],
    use_meta=["evaluation/prepare"],
)
all_items, successful_items, errors = results["evaluation"]
```

Each result has `(all_files, filtered_files, errors)`. `all_files` retains each
input attempt once, including rejected attempts. `StageItem.item_id` survives
path changes; path/meta pair unpacking remains available for existing readers.
Producers that change paths must return `StageItem` with the original identity.
Errors are keyed events with `StageError(item_id, path, stage, message)` values.
A leaf holds its own errors; composites aggregate their direct children's errors.
Final statistics should consume the target composite once rather than concatenate
its descendant snapshots.

Result keys and callback stage names are full paths such as
`evaluation/metrics/distance`. Callbacks run after their node completes, including
cache hits. **Transitions now transform a node's input before it executes**;
move transitions previously attached to the preceding stage onto their target.
The parallel `pass_condition` receives success booleans in declaration order.
Its separate `output_path_selector` receives ordered `BranchResult` objects;
the default uses the first successful branch's path. All metadata and errors
remain available regardless of which path is chosen.

`use_meta=[]` disables cache everywhere; a list of paths enables the named nodes
and their descendants. Unknown paths fail before execution. Boolean policies
remain available for older callers. Cache selection is resolved by `run_stages`,
not by the truthiness of the list. A leaf saves only its own statistics section
and associated file field, preserving newer sibling sections already on disk.
Saving a new section through a metadata symlink creates a local file and leaves
the source unchanged. Cached paths are resolved relative to the source metadata.
Callbacks with nothing to save leave existing links untouched.

Worker exceptions, task timeouts and missing replies become item errors in both
safety modes. `process_timeout` also limits a non-isolated task; a dead worker's
outstanding items remain in `all_files` with their incoming metadata.
Timeout cleanup stops library-managed workers. Worker functions remain responsible
for external subprocesses they launch.

## Structured statistics

`calculate_stats` describes one selection; callers own grouping predicates and
any overall metrics. Its result contains `statistics`, `ratios`, and `summary`.

```python
from terminal_app.processing_utils.statistics import calculate_stats

result = calculate_stats(
    [("sample.stl", {"distance": 0.0, "invalid": False})],
    {
        "distance": {"kind": "statistics", "store_examples": True},
        "invalid": {"kind": "ratio", "store_examples": True},
    },
)
```

Numeric summaries contain `{value, example}` for mean, median, min, max, standard
deviation and 25/75/90 percentiles. Representative examples are the nearest real
observation; standard deviation has no example. Zero values remain visible.
Ratio fields contain positive `count`, `ratio`, `positive_example` and
`negative_example`. Missing flags never become negative examples. The
ratio denominator is the full selection. `summary.count` is the selection size.
Empty selections and missing measurements use `null` values/examples rather than NaN.

Existing field patterns and `store_examples` remain supported. Callers should
specify `kind`; configurations without it retain the legacy `is_` convention.
The former flat statistics keys and separate examples map are no longer emitted.
