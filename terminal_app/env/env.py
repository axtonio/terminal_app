from __future__ import annotations

__all__ = ["source", "SourceEnv", "PROJECT_CONFIG"]

import __main__
import os
import sys
import json
import platform
import requests
from typing import Literal, Any

from pathlib import Path
from dotenv import load_dotenv

from tabulate import tabulate
from omegaconf import OmegaConf
from hydra import initialize_config_dir, compose
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
except Exception:
    _RUN_MODE = "jupyter"

match _RUN_MODE:
    case "script":
        _BASE_DIR = _WORK_DIR = Path(os.path.dirname(__main__.__file__))
    case "module":
        _WORK_DIR = Path(os.path.dirname(__main__.__file__))
        _BASE_DIR = _WORK_DIR.parent
    case "bin":
        _BASE_DIR = _WORK_DIR = Path(os.getcwd())
    case "jupyter":
        _BASE_DIR = _WORK_DIR = Path(os.getcwd())

if (tmp := os.getenv("BASE_DIR")) is not None:
    _BASE_DIR = Path(tmp)

if (tmp := os.getenv("WORK_DIR")) is not None:
    _WORK_DIR = Path(tmp)

_CONFIG_NAME = ".terminal_app.yaml"
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
    TMP_DIR: Path = DATA_DIR / "tmp"
    CACHE_DIR: Path = DATA_DIR / "cache"
    BACKUP_DIR: Path = DATA_DIR / "backup"
    EXAMPLES_DIR: Path = DATA_DIR / "examples"

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

    @property
    def GLOBAL_CONFIG_DIR(self) -> Path:
        return self.CONFIGS_DIR / "global"

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
        keys = _parse_yaml_file(env_file_path).keys()
        with open(env_file_path, "a") as f:
            for field, info in cls.model_fields.items():
                if field not in keys and not info.exclude:
                    value = (
                        info.default
                        if os.getenv(field, None) is None
                        else os.getenv(field)
                    )

                    f.write(
                        f"{field}: {value if not isinstance(value, list) else '\n - ' + '\n - '.join(value)}\n"
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

            self.GLOBAL_CONFIG_DIR.mkdir(exist_ok=True)

        self.DESCRIPTION = self.DESCRIPTION.format(
            self.OS, self.CONFIG_DIR, self.BASE_DIR, self.WORK_DIR, self.RUN_MODE
        )

        another = ""

        if self.GLOBAL_CONFIG_DIR.exists():
            for env_file in self.GLOBAL_CONFIG_DIR.iterdir():
                if env_file.is_dir():
                    continue
                another += f"\n# {env_file.name}\n"
                another += _show_env_info(env_file)

        if self.CONFIG_DIR.exists():
            for env_file in self.CONFIG_DIR.iterdir():
                if env_file.is_dir():
                    continue
                another += f"\n# {env_file.name}\n"
                another += _show_env_info(env_file)

        self.DESCRIPTION += another

        return self

    def __str__(self) -> str:
        return self.DESCRIPTION

    def __repr__(self) -> str:
        return self.DESCRIPTION


def _parse_env_file(env_file_path: Path) -> dict[str, Any]:
    """
    Парсинг ключ=значение из .env-файлов.
    """
    data = {}
    with open(env_file_path) as f:
        for line in f.readlines():
            line = line.strip()
            if not line.startswith("#") and line:
                name = line[: line.find("=")].strip().strip('"').strip("'")
                arg = line[line.find("=") + 1 :].strip().strip('"').strip("'")
                data[name] = arg

    return data


def _parse_yaml_file(yaml_file_path: Path) -> dict[str, Any]:
    with initialize_config_dir(
        config_dir=yaml_file_path.parent.as_posix(),
        job_name="terminal_app",
        version_base=None,
    ):
        cfg_name = yaml_file_path.stem

        conf = compose(config_name=cfg_name)

    conf_dict: dict[str, Any] = OmegaConf.to_container(conf, resolve=True)  # type: ignore
    return conf_dict


def _show_env_info(env_file_path: Path) -> str:
    """
    Вывод таблицы "ключ | текущее значение в окружении | значение в файле"
    """
    columns = ["name", "env", "file"]
    rows = []

    if env_file_path.suffix in (".yml", ".yaml"):
        data: dict[str, Any] = _parse_yaml_file(env_file_path)
    elif env_file_path.suffix == ".json":
        data = json.loads(env_file_path.read_text())
    else:
        data = _parse_env_file(env_file_path)

    if env_file_path.name[0] != ".":
        return json.dumps(data, indent=2, ensure_ascii=False)

    for name, file_val in data.items():
        rows.append((name, os.getenv(name), file_val))

    return tabulate(rows, headers=columns, tablefmt="psql")


class SourceEnv(dict):
    """
    Класс для хранения конфигурации. При попытке получить
    несуществующий ключ, выбрасывает KeyError с осмысленным сообщением.
    """

    def __getitem__(self, key: str) -> Any:
        try:
            return super().__getitem__(key)
        except KeyError as ex:
            new_ex = KeyError(
                f"Key '{key}' not found in the configuration environment. "
                f"Configuration directory: {PROJECT_CONFIG.CONFIG_DIR.as_posix()}"
            )
            raise new_ex from ex


def source(env_files: str | list[str] | Path | list[Path]) -> SourceEnv:
    """
    Универсальная функция для чтения конфигураций из .env и .yaml/.yml.
    - Если файл .env (или .dotenv), то грузим через load_dotenv.
    - Если YAML, то грузим через OmegaConf.load.
      Если имя файла начинается с точки (например, .secret.yaml),
      то все считанные ключи добавляем в переменные окружения.
      Иначе просто складываем их в результирующий словарь.
    """
    data: dict[str, Any] = {}
    assert (
        env_files != _CONFIG_NAME
    ), f"The env file cannot be assigned the name  {_CONFIG_NAME}"

    def load_env_file(env_file_path: Path) -> None:
        if not env_file_path.exists():
            with open(env_file_path, "w") as f:
                f.write(f"# {env_file_path.name}\n")
            print(f"Create {env_file_path}")

        load_dotenv(env_file_path)
        keys = _parse_env_file(env_file_path).keys()
        load_values(keys)

    def load_values(keys):
        for key in keys:
            variable = os.getenv(key, "")
            if variable == "REMOTE":
                remote_conf = source("remote.yaml")["remotes"]
                url = f"http://{remote_conf['HOST']}:{remote_conf['PORT']}/{remote_conf.get('TOKEN', '')}{key}"
                try:
                    response = requests.get(url)
                    response.raise_for_status()  # Проверка на ошибки
                    variable = response.text.strip()
                    print(f"{key} | Полученный ключ: {variable}")
                except requests.exceptions.RequestException as ex:
                    variable = ""
                    print(f"{key} | Ошибка при запросе: {ex}")

                os.environ[key] = variable

            if variable.isdigit():
                variable = int(variable)
            elif variable.strip().startswith("[") or variable.strip().startswith("{"):
                try:
                    variable = json.loads(variable.replace("'", '"'))
                except Exception:
                    pass
            elif variable.lower() not in ("true", "false"):
                try:
                    variable = float(variable)
                except Exception:
                    pass
            data[key] = variable

    def load_yaml_file(yaml_file_path: Path) -> None:
        nonlocal data
        if not yaml_file_path.exists():
            with open(yaml_file_path, "w") as f:
                f.write(f"# {yaml_file_path.name}\n")
            print(f"Create {yaml_file_path}")

        conf_dict = _parse_yaml_file(yaml_file_path)

        if yaml_file_path.name.startswith("."):
            for k, v in conf_dict.items():
                if os.getenv(k) is None:
                    os.environ[k] = str(v)

            load_values(conf_dict.keys())
        else:
            data = conf_dict

    def load_json_file(json_file_path: Path) -> None:
        nonlocal data
        if not json_file_path.exists():
            with open(json_file_path, "w") as f:
                f.write("{}")
            print(f"Create {json_file_path}")

        conf_dict = json.loads(json_file_path.read_text())

        if json_file_path.name.startswith("."):
            for k, v in conf_dict.items():
                if os.getenv(k) is None:
                    os.environ[k] = str(v)

            load_values(conf_dict.keys())
        else:
            data = conf_dict

    def handle_one_file(env_file: str | Path):
        if isinstance(env_file, Path):
            path = env_file
        else:
            path = PROJECT_CONFIG.CONFIG_DIR / env_file
            if not path.exists():
                path = PROJECT_CONFIG.GLOBAL_CONFIG_DIR / env_file

        suffix = path.suffix.lower()
        if suffix in (".env", ".dotenv"):
            load_env_file(path)
        elif suffix in (".yml", ".yaml"):
            load_yaml_file(path)
        elif suffix == ".json":
            load_json_file(path)
        else:
            raise ValueError(
                f"Unsupported file format '{suffix}'. Must be .env/.dotenv or .yml/.yaml"
            )

    if isinstance(env_files, (str, Path)):
        handle_one_file(env_files)
    else:
        for env_file in env_files:
            handle_one_file(env_file)

    return SourceEnv(data)


PROJECT_CONFIG = ProjectConfig()

if PROJECT_CONFIG.GLOBAL_CONFIG_DIR.exists():
    for env_file in PROJECT_CONFIG.GLOBAL_CONFIG_DIR.iterdir():
        if env_file.is_dir():
            continue
        try:
            source(env_file)
        except Exception as ex:
            print(ex)
            pass

if PROJECT_CONFIG.CONFIG_DIR.exists():
    for env_file in PROJECT_CONFIG.CONFIG_DIR.iterdir():
        if env_file.is_dir():
            continue
        try:
            source(env_file)
        except Exception:
            pass
