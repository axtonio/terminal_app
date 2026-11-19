"""Project configuration and initialization of its environment and directories."""

import os
import platform
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from terminal_app.env.parsing import parse_yaml_file, show_env_info
from terminal_app.env.runtime import BASE_DIR, CONFIG_FILE, RUN_MODE, WORK_DIR
from terminal_app.env.source import SourceEnv as SourceEnv
from terminal_app.env.source import source
from terminal_app.logging.logging import TERMINAL_APP_LOGGER


def _append_missing_fields(path: Path, fields: dict[str, Any]) -> None:
    existing = parse_yaml_file(path)
    additions = []
    for name, info in fields.items():
        if name in existing or info.exclude:
            continue
        value = os.environ.get(name, info.default)
        formatted = (
            "\n - " + "\n - ".join(map(str, value))
            if isinstance(value, list)
            else value
        )
        additions.append(f"{name}: {formatted}\n")
    if not additions:
        return
    previous = path.read_text()
    separator = "\n" if previous and not previous.endswith("\n") else ""
    with path.open("a") as output:
        output.write(separator + "".join(additions))


def _export_paths(config: "ProjectConfig") -> None:
    for name, value in config:
        os.environ[name] = str(value)
        if isinstance(value, Path) and not value.is_absolute():
            absolute = config.BASE_DIR / value.as_posix()
            setattr(config, name, absolute)
            os.environ[name] = absolute.as_posix()
    if config.model_extra:
        _export_extra_paths(config.BASE_DIR, config.model_extra)


def _export_extra_paths(base: Path, values: dict[str, Any]) -> None:
    try:
        for name, value in values.items():
            path = Path(value)
            if not path.is_absolute():
                os.environ[name] = (base / path).as_posix()
    except (TypeError, ValueError):
        # Extra configuration values need not be filesystem paths.
        return


def _configuration_description(config: "ProjectConfig") -> str:
    description = config.CONFIG_DESC.format(
        config.OS,
        config.GLOB_CONFIG_DIR,
        config.MODE_CONFIG_DIR,
        config.BASE_DIR,
        config.WORK_DIR,
        config.RUN_MODE,
    )
    for directory in (config.GLOB_CONFIG_DIR, config.MODE_CONFIG_DIR):
        if directory.exists():
            description += _directory_description(directory)
    return description


def _directory_description(directory: Path) -> str:
    return "".join(
        f"\n# {path.name}\n{show_env_info(path)}"
        for path in directory.iterdir()
        if not path.is_dir()
    )


class ProjectConfig(BaseModel):
    BASE_DIR: Path = Field(default=BASE_DIR, init=False, exclude=True)
    WORK_DIR: Path = Field(default=WORK_DIR, init=False, exclude=True)
    GLOB_CONFIG_DIR: Path = Path("configs")
    MODE_CONFIG_DIR: Path = Path("configs/dev")

    LOGGING_DIR: Path = Path("logging")
    LOGGING_SUFFIX: str = "terminal_app"
    LOGGING_FILE_MODE: Literal["w", "a"] = "w"
    TERMINAL_APP_LOGGER: bool = False

    INIT_FOLDERS: bool = False
    CONFIG_DESC: str = Field(init=False, exclude=True)
    PROJECT_DESC: Callable[["ProjectConfig"], str] = Field(
        default=lambda config: config.CONFIG_DESC, exclude=True
    )
    model_config = ConfigDict(extra="allow")

    @property
    def OS(self) -> str:
        return platform.system().lower()

    @property
    def RUN_MODE(self) -> str:
        return RUN_MODE

    @model_validator(mode="before")
    @classmethod
    def init_project(cls, data: dict[str, Any]) -> dict[str, Any]:
        cls.check_env_file(CONFIG_FILE)
        for key, value in data.items():
            if not callable(value):
                os.environ[key] = str(value)
        description = (
            "# Terminal App\n- OS: {}\n- GLOB_CONFIG_DIR: {}\n- MODE_CONFIG_DIR: {}\n"
            "- BASE_DIR: {}\n- WORK_DIR: {}\n- RUN_MODE: {}\n"
            + show_env_info(CONFIG_FILE)
        )
        values = source(CONFIG_FILE)
        values.update(data)
        values["CONFIG_DESC"] = description
        return values

    @classmethod
    def check_env_file(cls, env_file_path: Path) -> None:
        if not env_file_path.exists():
            env_file_path.write_text(f"# {env_file_path.name}\n")
            TERMINAL_APP_LOGGER.info("Create %s", env_file_path)
        _append_missing_fields(env_file_path, cls.model_fields)

    @model_validator(mode="after")
    def check_init_folders(self) -> "ProjectConfig":
        _export_paths(self)
        if self.INIT_FOLDERS:
            for _, path in self:
                if isinstance(path, Path) and not path.exists():
                    path.mkdir()
            self.GLOB_CONFIG_DIR.mkdir(exist_ok=True)
        # Pydantic stores this declared model field per instance, not on the class.
        self.CONFIG_DESC = _configuration_description(self)  # noqa: WPS601
        TERMINAL_APP_LOGGER.info("\n%s", self.PROJECT_DESC(self))
        return self

    def __str__(self) -> str:
        return self.PROJECT_DESC(self)

    def __repr__(self) -> str:
        return self.PROJECT_DESC(self)
