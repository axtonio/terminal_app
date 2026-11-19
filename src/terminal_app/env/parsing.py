"""Read configuration files and display their effective environment values."""

import json
import os
from pathlib import Path
from typing import Any

from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf
from tabulate import tabulate

from terminal_app.logging.logging import TERMINAL_APP_LOGGER


def parse_env_file(env_file_path: Path) -> dict[str, Any]:
    try:
        result = {}
        for raw_line in env_file_path.read_text().splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#"):
                name = line[: line.find("=")].strip().strip('"').strip("'")
                argument = line[line.find("=") + 1 :].strip().strip('"').strip("'")
                result[name] = argument
        return result
    except Exception:
        TERMINAL_APP_LOGGER.error("Error parsing %s", env_file_path)
        return {}


def parse_yaml_file(yaml_file_path: Path) -> dict[str, Any]:
    try:
        with initialize_config_dir(
            config_dir=yaml_file_path.parent.as_posix(),
            job_name="terminal_app",
            version_base=None,
        ):
            config = compose(config_name=yaml_file_path.stem)
        result = OmegaConf.to_container(config, resolve=True)
        if not isinstance(result, dict):
            raise TypeError("The configuration must contain a mapping")
        return {str(key): value for key, value in result.items()}
    except Exception:
        TERMINAL_APP_LOGGER.error("Error parsing %s", yaml_file_path)
        return {}


def parse_json_file(json_file_path: Path) -> dict[str, Any]:
    try:
        result = json.loads(json_file_path.read_text())
        if not isinstance(result, dict):
            raise TypeError("The configuration must contain a mapping")
        return result
    except Exception:
        TERMINAL_APP_LOGGER.error("Error parsing %s", json_file_path)
        return {}


def parse_config_file(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in (".yml", ".yaml"):
        return parse_yaml_file(path)
    if path.suffix.lower() == ".json":
        return parse_json_file(path)
    return parse_env_file(path)


def show_env_info(env_file_path: Path) -> str:
    data = parse_config_file(env_file_path)
    if not env_file_path.name.startswith("."):
        return json.dumps(data, indent=2, ensure_ascii=False)
    rows = [(name, os.getenv(name), value) for name, value in data.items()]
    return tabulate(rows, headers=["name", "env", "file"], tablefmt="psql")
