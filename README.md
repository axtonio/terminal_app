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

## Tests

Run the test suite from the project environment:

```bash
conda activate cadpac_tripo
pytest
```
