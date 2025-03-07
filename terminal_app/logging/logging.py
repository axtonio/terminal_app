from __future__ import annotations

__all__ = [
    "LoggingMeta",
    "RootLogging",
    "DEFAULT_STREAM",
    "register_logger",
    "DEFAULT_FORMATTER",
    "TerminalAppHandler",
    "TERMINAL_APP_LOGGER",
    "getTerminalAppLogger",
]

import os
import io
import sys
import logging
from pathlib import Path
from inspect import getfile
from logging import Logger, FileHandler
from typing import Any, overload, Literal

from terminal_app.env import PROJECT_CONFIG

suffix = PROJECT_CONFIG.LOGGING_SUFFIX

DEFAULT_FORMATTER = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
DEFAULT_STREAM = logging.StreamHandler()
DEFAULT_STREAM.setFormatter(DEFAULT_FORMATTER)


class TerminalAppHandler(FileHandler):

    def __init__(
        self,
        terminal_app_stream: io.TextIOWrapper | None,
        filename: str | os.PathLike[str],
        mode: str = "a",
        encoding: str | None = None,
        delay: bool = False,
        errors: str | None = None,
    ) -> None:
        super().__init__(filename, mode, encoding, delay, errors)
        self.terminal_app_stream: io.TextIOWrapper = terminal_app_stream if terminal_app_stream is not None else sys.stdout  # type: ignore

    def emit(self, record: logging.LogRecord) -> None:
        stream = self.stream
        line = self.get_line(self.baseFilename)
        message = record.msg

        record.msg = line
        self.stream = self.terminal_app_stream
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


class TerminalAppLogger(Logger):

    def _log(self, *args, **kwargs) -> None:
        if PROJECT_CONFIG.TERMINAL_APP_LOGGER:
            return super()._log(*args, **kwargs)


@overload
def register_logger(
    path: Path | str,
    *,
    name: str | None = None,
    library: bool = False,
    level: logging._Level = logging.DEBUG,
    without_handlers: bool = False,
    if_exist: Literal["error", "clear", "return"] = "error",
) -> Logger:
    pass


@overload
def register_logger(
    path: Path | str,
    *,
    name: str | None = None,
    library: bool = False,
    level: logging._Level = logging.DEBUG,
    terminal_app_handler: Literal[True],
    terminal_app_stream: io.TextIOWrapper | None = None,
    without_handlers: bool = False,
    if_exist: Literal["error", "clear", "return"] = "error",
) -> Logger:
    pass


@overload
def register_logger(
    *,
    name: str,
    library: bool = False,
    level: logging._Level = logging.DEBUG,
    without_handlers: bool = False,
    if_exist: Literal["error", "clear", "return"] = "error",
) -> Logger:
    pass


@overload
def register_logger() -> TerminalAppLogger:
    pass


def register_logger(
    path: Path | str | None = None,
    name: str | None = None,
    library: bool = False,
    level: logging._Level = logging.DEBUG,
    terminal_app_handler: bool = False,
    terminal_app_stream: io.TextIOWrapper | None = None,
    without_handlers: bool = False,
    if_exist: Literal["error", "clear", "return"] = "error",
) -> Logger:

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    if path is not None:

        file_path = RootLogging.root_path / path if isinstance(path, str) else path

    name = name if name is not None else file_path.stem if path is not None else None

    if name in logging.Logger.manager.loggerDict.keys() or library:
        TERMINAL_APP_LOGGER.info(f"Change {name} logger")
        logger = logging.getLogger(name)
        for handler in logger.handlers:
            logger.removeHandler(handler)
    else:
        if name is not None:
            naming = f"{suffix}.{name}"
            if naming in logging.Logger.manager.loggerDict.keys():
                if if_exist == "clear":
                    logger = logging.getLogger(naming)
                    for handler in logger.handlers:
                        logger.removeHandler(handler)

                    logging.Logger.manager.loggerDict.pop(naming)
                if if_exist == "return":
                    return logging.getLogger(naming)

            assert (
                naming not in logging.Logger.manager.loggerDict.keys()
            ), "The same name of the loggers"
            logger = logging.getLogger(naming)
        else:
            logger = TerminalAppLogger(suffix, level)

    if not without_handlers:

        if path is not None:
            if not terminal_app_handler:
                file_handler = logging.FileHandler(
                    file_path.as_posix(), mode=PROJECT_CONFIG.LOGGING_FILE_MODE
                )
            else:
                file_handler = TerminalAppHandler(
                    terminal_app_stream,
                    file_path.as_posix(),
                    mode=PROJECT_CONFIG.LOGGING_FILE_MODE,
                )

            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

            if PROJECT_CONFIG.LOGGING_FILE_MODE.lower() != "w":

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


def getTerminalAppLogger(name: str) -> Logger:
    return logging.getLogger(f"{PROJECT_CONFIG.LOGGING_SUFFIX}.{name}")


TERMINAL_APP_LOGGER = register_logger()
TERMINAL_APP_LOGGER.info("\n" + str(PROJECT_CONFIG))
