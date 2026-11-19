"""Discover project paths without creating directories or loading configuration."""

import os
import sys
from pathlib import Path
from typing import Literal

import __main__

RunMode = Literal["script", "module", "jupyter", "bin"]
CONFIG_NAME = ".terminal_app.yaml"


def _run_mode() -> RunMode:
    if not getattr(__main__, "__file__", None):
        return "jupyter"
    if (
        "-m" in sys.orig_argv
        and len(sys.orig_argv) > 2
        and sys.orig_argv[2] != "ipykernel_launcher"
    ):
        return "module"
    if sys.argv[0].endswith(".py"):
        return "script"
    return "bin"


def _project_paths(mode: RunMode) -> tuple[Path, Path]:
    work = Path.cwd()
    if mode in ("script", "module"):
        work = Path(os.path.dirname(__main__.__file__))
    base = work.parent if mode == "module" else work
    base = Path(os.environ.get("BASE_DIR", base))
    work = Path(os.environ.get("WORK_DIR", work))
    candidate = base
    while not (candidate / CONFIG_NAME).exists() and candidate.parent != candidate:
        candidate = candidate.parent
    if (candidate / CONFIG_NAME).exists():
        base = candidate
    return base, work


RUN_MODE = _run_mode()
BASE_DIR, WORK_DIR = _project_paths(RUN_MODE)
CONFIG_FILE = BASE_DIR / CONFIG_NAME
