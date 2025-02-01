from __future__ import annotations

__all__ = [
    "register_logger",
    "LoggingMeta",
    "RootLogging",
    "TerminalAppHandler",
    "DEFAULT_FORMATTER",
    "DEFAULT_STREAM",
]

import os
import sys
import logging
from typing import Any, overload
from logging import Logger, FileHandler
from pathlib import Path
from inspect import getfile

from terminal_app.env import PROJECT_CONFIG

suffix = PROJECT_CONFIG.LOGGING_SUFFIX

DEFAULT_FORMATTER = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
DEFAULT_STREAM = logging.StreamHandler()
DEFAULT_STREAM.setFormatter(DEFAULT_FORMATTER)


class TerminalAppHandler(FileHandler):

    def emit(self, record: logging.LogRecord) -> None:
        stream = self.stream
        line = self.get_line(self.baseFilename)
        message = record.msg

        record.msg = line
        self.stream = sys.stdout  # type: ignore
        super().emit(record)

        self.stream = stream
        record.msg = message
        super().emit(record)
        return None

    def close(self) -> None:

        return super().close()

    @staticmethod
    def get_line(logger: Logger | str | Path) -> str:
        if isinstance(logger, Logger):
            for handler in logger.handlers:
                if isinstance(handler, FileHandler):
                    logging_path = handler.baseFilename
        else:
            logging_path = logger

        try:
            with open(logging_path, "r") as f:
                return f"{logging_path}, line {len(f.readlines()) + 1}"

        except:

            return ""


@overload
def register_logger(
    path: Path | str,
    *,
    name: str | None = None,
    library: bool = False,
    level: logging._Level = logging.DEBUG,
    terminal_app_handler: bool = False,
    without_handlers: bool = False,
    remove: bool = False,
) -> Logger:
    pass


@overload
def register_logger(
    *,
    name: str,
    library: bool = False,
    level: logging._Level = logging.DEBUG,
    without_handlers: bool = False,
    remove: bool = False,
) -> Logger:
    pass


def register_logger(
    path: Path | str | None = None,
    name: str | None = None,
    library: bool = False,
    level: logging._Level = logging.DEBUG,
    terminal_app_handler: bool = False,
    without_handlers: bool = False,
    remove: bool = False,
) -> Logger:

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    if path is not None:

        file_path = RootLogging.root_path / path if isinstance(path, str) else path

    name = name if name is not None else file_path.stem if path is not None else None

    if name in logging.Logger.manager.loggerDict.keys() or library:
        print(f"Change {name} logger")
        logger = logging.getLogger(name)
        for handler in logger.handlers:
            logger.removeHandler(handler)
    else:
        if name is not None:
            naming = f"{suffix}.{name}"
            if remove:
                if naming in logging.Logger.manager.loggerDict.keys():
                    logger = logging.getLogger(name)
                    for handler in logger.handlers:
                        logger.removeHandler(handler)

                    logging.Logger.manager.loggerDict.pop(naming)

            assert (
                naming not in logging.Logger.manager.loggerDict.keys()
            ), "The same name of the loggers"
            logger = logging.getLogger(naming)
        else:
            logger = logging.getLogger(suffix)

    if not without_handlers:

        if path is not None:
            if not terminal_app_handler:
                file_handler = logging.FileHandler(
                    file_path.as_posix(), mode=PROJECT_CONFIG.LOGGING_FILE_MODE
                )
            else:
                file_handler = TerminalAppHandler(
                    file_path.as_posix(), mode=PROJECT_CONFIG.LOGGING_FILE_MODE
                )

            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

            with open(file_path, f"{PROJECT_CONFIG.LOGGING_FILE_MODE}+") as f:
                f.seek(0)
                lines = f.readlines()
                lines.reverse()

                count = 1
                message = "STARTUP {}\n"
                for line in lines:
                    if line.startswith("STARTUP"):
                        try:
                            count = int(line[-2]) + 1
                            break
                        except Exception as ex:
                            print(ex)
                            continue

                f.write(message.format(count))

        else:
            logger.addHandler(DEFAULT_STREAM)

    logger.setLevel(level)

    return logger


class LoggingMeta(type):
    __root_path__: Path = PROJECT_CONFIG.LOGGING_DIR
    logger: Logger
    root_logger: Logger

    @property
    def root_path(cls) -> Path:
        create_folder = False
        create_folder = not LoggingMeta.__root_path__.exists()
        create_folder = not LoggingMeta.__root_path__.is_dir()
        if create_folder:
            os.mkdir(LoggingMeta.__root_path__)

        return LoggingMeta.__root_path__

    def __new__(
        mcls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]
    ) -> type:
        cls = super().__new__(mcls, name, bases, namespace)

        if "RootLogging" in [base.__name__ for base in bases]:
            if os.getenv(f"{name}_LOGGING"):

                cls.root_logger = register_logger(cls.root_path / f"{name}.log")

        if namespace.get("LOGGING", None) is True:
            file = Path(getfile(cls))
            cls.logger = register_logger(file.parent / (file.stem + ".log"), name=name)

        return cls


class RootLogging(metaclass=LoggingMeta):
    LOGGING = False
