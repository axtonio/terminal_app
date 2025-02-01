from __future__ import annotations

__all__ = ["source", "SourceEnv", "PROJECT_CONFIG"]


import __main__
import os
import sys
import json
import platform
from typing import Literal, Any

from pathlib import Path
from dotenv import load_dotenv

from tabulate import tabulate

# from pytest_is_running import is_running
from pydantic import BaseModel, model_validator, Field


_RUN_MODE: Literal["script", "module", "jupyter", "bin"]

try:
    __main__.__file__
    if "-m" in sys.orig_argv and sys.orig_argv[2] != "ipykernel_launcher":
        _RUN_MODE = "module"
    elif sys.argv[0].endswith(".py"):
        _RUN_MODE = "script"

    else:
        _RUN_MODE = "bin"
except:
    _RUN_MODE = "jupyter"


match _RUN_MODE:
    case "script":
        _BASE_DIR = _WORK_DIR = Path(os.path.dirname(__main__.__file__))
    case "module":
        _WORK_DIR = Path(os.path.dirname(__main__.__file__))
        _BASE_DIR = _WORK_DIR.parent
    case "bin":
        _BASE_DIR = _WORK_DIR = Path(os.getcwd())

        # if is_running():
        # _BASE_DIR = Path(os.getcwd()) / "tests"
    case "jupyter":
        _BASE_DIR = _WORK_DIR = Path(os.getcwd())

if (tmp := os.getenv("BASE_DIR")) is not None:
    _BASE_DIR = Path(tmp)

if (tmp := os.getenv("WORK_DIR")) is not None:
    _WORK_DIR = Path(tmp)

_CONFIG_NAME = ".terminal_app.env"
_TMP_BASE_DIR = _BASE_DIR
CONFIG_FILE = _TMP_BASE_DIR / _CONFIG_NAME

while not CONFIG_FILE.exists() and _TMP_BASE_DIR.parent != _TMP_BASE_DIR:
    _TMP_BASE_DIR = _TMP_BASE_DIR.parent
    CONFIG_FILE = _TMP_BASE_DIR / _CONFIG_NAME


if CONFIG_FILE.exists():
    _BASE_DIR = _TMP_BASE_DIR

CONFIG_FILE = _BASE_DIR / _CONFIG_NAME


class ProjectConfig(BaseModel):
    BASE_DIR: Path = Field(default=_BASE_DIR, init=False, exclude=True)
    WORK_DIR: Path = Field(default=_WORK_DIR, init=False, exclude=True)
    CONFIGS_DIR: Path = Path("configs")
    CONFIG_FOLDERS: list = ["development", "production", "test"]
    SOURCE_FOLDER: str = "development"
    LOGGING_DIR: Path = Path("logging")
    LOGGING_SUFFIX: str = "terminal_app"
    LOGGING_FILE_MODE: Literal["w", "a"] = "w"
    CERTIFICATES_DIR: Path = Path("certificates")
    SSH_DIR: Path = CERTIFICATES_DIR / "ssh"
    DATA_DIR: Path = Path("data")
    MEDIA_DIR: Path = DATA_DIR / "media"
    DOCUMENT_DIR: Path = MEDIA_DIR / "document"
    VIDEO_DIR: Path = MEDIA_DIR / "video"
    PHOTO_DIR: Path = MEDIA_DIR / "photo"

    INIT_FOLDERS: bool = False
    TERMINAL_APP_LOGGER: bool = False
    DESCRIPTION: str = Field(init=False, exclude=True)

    @property
    def OS(self) -> str:
        return platform.system().lower()

    @property
    def RUN_MODE(self) -> str:
        return _RUN_MODE

    @property
    def CONFIG_DIR(self) -> Path:
        return self.CONFIGS_DIR / self.SOURCE_FOLDER

    @model_validator(mode="before")
    @classmethod
    def init_project(cls, data: dict[str, Any]) -> dict[str, Any]:
        if not CONFIG_FILE.exists():
            with open(CONFIG_FILE, "w") as f:
                f.write(f"# {CONFIG_FILE.name}\n")

            print(f"Create {CONFIG_FILE}")

        ProjectConfig.check_env_file(CONFIG_FILE)

        desc = f"# Terminal App\n- OS: {{}}\n- CONFIG: {{}}\n- BASE_DIR: {{}}\n- WORK_DIR: {{}}\n- RUN_MODE: {{}}\n{_show_env_info(CONFIG_FILE)}"

        data = source(CONFIG_FILE)
        data["INIT_FOLDERS"] = data["INIT_FOLDERS"].lower()
        data["TERMINAL_APP_LOGGER"] = data["TERMINAL_APP_LOGGER"].lower()
        data["DESCRIPTION"] = desc

        assert (
            data["SOURCE_FOLDER"] in data["CONFIG_FOLDERS"]
        ), "SOURCE_FOLDER should be located in the CONFIG_FOLDERS"

        return data

    @classmethod
    def check_env_file(cls, env_file_path: Path) -> None:
        keys = _parse_env_file(env_file_path).keys()
        with open(env_file_path, "a") as f:
            for field, info in cls.model_fields.items():
                if field not in keys and not info.exclude:
                    f.write(
                        f"{field}={info.default if os.getenv(field, None) is None else os.getenv(field)}\n"
                    )

    @model_validator(mode="after")
    def check_init_folders(self):
        for name, path in self:
            if isinstance(path, Path):
                if not path.is_absolute():
                    setattr(self, name, self.BASE_DIR / path.as_posix())

        if self.INIT_FOLDERS:
            for name, path in self:
                if isinstance(path, Path):
                    if not path.exists():
                        os.mkdir(path)

                    if name == "CONFIGS_DIR":
                        for sub_path in self.CONFIG_FOLDERS:
                            new_path = path / sub_path
                            if not new_path.exists():
                                os.mkdir(new_path)

        self.DESCRIPTION = self.DESCRIPTION.format(
            self.OS, self.CONFIG_DIR, self.BASE_DIR, self.WORK_DIR, self.RUN_MODE
        )

        another = ""
        for env_file in self.CONFIG_DIR.iterdir():
            another += f"\n# {env_file.stem.replace('_', ' ').strip('.').title()}\n"
            another += _show_env_info(env_file)

        self.DESCRIPTION += another

        return self

    def __str__(self) -> str:
        return self.DESCRIPTION

    def __repr__(self) -> str:
        return self.DESCRIPTION


def _parse_env_file(env_file_path: Path) -> dict[str, Any]:
    data = {}
    with open(env_file_path) as f:
        for line in f.readlines():
            line = line.strip()
            if not line.startswith("#") and line:
                name = line[: line.find("=")].strip().strip('"').strip("'")
                arg = line[line.find("=") + 1 :].strip().strip('"').strip("'")
                data[name] = arg

    return data


def _show_env_info(env_file_path: Path) -> str:
    columns = ["name", "env", "file"]
    rows = []

    for name, file in _parse_env_file(env_file_path).items():
        rows.append((name, os.getenv(name), file))

    return tabulate(rows, headers=columns, tablefmt="psql")


class SourceEnv(dict):

    def __getitem__(self, key: str) -> Any:
        try:
            return super().__getitem__(key)
        except KeyError as ex:
            new_ex = KeyError(
                f"Key '{key}' not found in the configuration environment. Configuration directory: {PROJECT_CONFIG.CONFIG_DIR.as_posix()}"
            )
            raise new_ex from ex


def source(env_files: str | list[str] | Path | list[Path]) -> SourceEnv:
    data: dict[str, str] = {}
    assert (
        env_files != _CONFIG_NAME
    ), f"The env file cannot be assigned the name  {_CONFIG_NAME}"

    def _get_path(env_file: str) -> Path:
        config_path = PROJECT_CONFIG.CONFIG_DIR

        return config_path / env_file

    def _source(env_file_path: Path) -> None:
        assert env_file_path.name.endswith(
            ".env"
        ), "The configuration file must end in .env"

        if not env_file_path.exists():
            with open(env_file_path, "w") as f:
                f.write(f"# {env_file_path.name}\n")

            print(f"Create {env_file_path}")

        load_dotenv(env_file_path)

    def load_variables(env_file_path: Path) -> None:
        keys = _parse_env_file(env_file_path).keys()
        for key in keys:
            variable = os.getenv(key, "")
            if variable.startswith("["):
                try:
                    variable = json.loads(variable.replace("'", '"'))
                except:
                    pass

            data[key] = variable

    if isinstance(env_files, str | Path):
        if isinstance(env_files, Path):
            path = env_files
        else:
            path = _get_path(env_files)
        _source(path)
        load_variables(path)

    else:
        for env_file in env_files:
            if isinstance(env_file, Path):
                path = env_file
            else:
                path = _get_path(env_file)
            _source(path)
            load_variables(path)

    return SourceEnv(data)


PROJECT_CONFIG = ProjectConfig()
