"""Load config values, retaining environment overrides for hidden config files."""

import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal, overload

import requests
from dotenv import load_dotenv

from terminal_app.env.parsing import parse_config_file, parse_env_file
from terminal_app.env.runtime import CONFIG_FILE, CONFIG_NAME
from terminal_app.logging.logging import TERMINAL_APP_LOGGER


class SourceEnv(dict[str, Any]):
    """Configuration mapping with an actionable error for missing keys."""

    def __getitem__(self, key: str) -> Any:
        try:
            return super().__getitem__(key)
        except KeyError as error:
            raise KeyError(
                f"Key '{key}' not found in the configuration environment. "
                f"Configuration directory: {os.environ.get('CONFIG_DIR', 'configs')}"
            ) from error


def _remote_value(key: str, raise_if_exception: bool) -> str:
    remote = source("remote.yaml")["remotes"]
    url = f"http://{remote['HOST']}:{remote['PORT']}/{remote.get('TOKEN', '')}{key}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        value = response.text.strip()
        TERMINAL_APP_LOGGER.info("Remote request | SUCCESS | %s:%s", key, value)
        return value
    except requests.exceptions.RequestException as error:
        TERMINAL_APP_LOGGER.error("Remote request | FAILED | %s:%s", key, error)
        if raise_if_exception:
            raise
        return ""


def _decode_value(value: str) -> Any:
    if value.isdigit():
        return int(value)
    if value.strip().startswith(("[", "{")):
        try:
            return json.loads(value.replace("'", '"'))
        except ValueError:
            return value
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    try:
        return float(value)
    except ValueError:
        return value


def _environment_values(
    keys: Iterable[str], raise_if_exception: bool
) -> dict[str, Any]:
    result = {}
    for key in keys:
        value = os.getenv(key, "")
        if value == "REMOTE":
            value = _remote_value(key, raise_if_exception)
            os.environ[key] = value
        result[key] = _decode_value(value)
    return result


def _resolve_config_path(env_file: str | Path) -> Path:
    if isinstance(env_file, Path):
        return env_file
    path = Path(os.environ.get("MODE_CONFIG_DIR", "configs")).absolute() / env_file
    if not path.exists():
        path = Path(os.environ.get("GLOB_CONFIG_DIR", "configs")).absolute() / env_file
    return path


def _ensure_config(path: Path) -> bool:
    if path.exists():
        return True
    path.parent.mkdir(exist_ok=True)
    path.write_text("{}" if path.suffix.lower() == ".json" else f"# {path.name}\n")
    TERMINAL_APP_LOGGER.warning("Create %s", path)
    return False


def _read_config(path: Path, raise_if_exception: bool) -> tuple[dict[str, Any], bool]:
    suffix = path.suffix.lower()
    if suffix in (".env", ".dotenv"):
        load_dotenv(path)
        return _environment_values(parse_env_file(path), raise_if_exception), False
    if suffix not in (".yml", ".yaml", ".json"):
        raise ValueError(
            f"Unsupported file format '{suffix}'. Must be .env/.dotenv or .yml/.yaml"
        )
    values = parse_config_file(path)
    if not path.name.startswith("."):
        return values, True
    for key, value in values.items():
        os.environ.setdefault(key, str(value))
    return _environment_values(values, raise_if_exception), False


@overload
def source(
    env_files: str | list[str] | Path | list[Path] = CONFIG_FILE,
    *,
    check_only: Literal[False] = False,
    raise_if_exception: bool = False,
) -> SourceEnv: ...


@overload
def source(
    env_files: str | Path = CONFIG_FILE,
    *,
    check_only: Literal[True],
    raise_if_exception: bool = False,
) -> bool: ...


@overload
def source(
    env_files: str | list[str] | Path | list[Path] = CONFIG_FILE,
    *,
    check_only: bool,
    raise_if_exception: bool = False,
) -> SourceEnv | bool: ...


def source(
    env_files: str | list[str] | Path | list[Path] = CONFIG_FILE,
    *,
    check_only: bool = False,
    raise_if_exception: bool = False,
) -> SourceEnv | bool:
    """Read .env, YAML and JSON, with environment overrides for hidden files."""
    assert (
        env_files != CONFIG_NAME
    ), f"The env file cannot be assigned the name  {CONFIG_NAME}"
    if check_only:
        return (
            _resolve_config_path(env_files).exists()
            if isinstance(env_files, (str, Path))
            else SourceEnv()
        )
    paths = [env_files] if isinstance(env_files, (str, Path)) else env_files
    data: dict[str, Any] = {}
    for env_file in paths:
        path = _resolve_config_path(env_file)
        if not _ensure_config(path):
            continue
        values, replace = _read_config(path, raise_if_exception)
        if replace:
            data = values
        else:
            data.update(values)
    return SourceEnv(data)
