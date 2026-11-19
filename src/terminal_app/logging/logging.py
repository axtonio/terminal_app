import io
import logging
import os
import sys
from copy import copy
from inspect import getfile
from logging import FileHandler, Logger
from pathlib import Path
from typing import Any, Callable, Literal, TextIO, cast, overload

DEFAULT_FORMATTER = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
DEFAULT_STREAM = logging.StreamHandler()
DEFAULT_STREAM.setFormatter(DEFAULT_FORMATTER)


def _suffix() -> str:
    return os.environ.get("LOGGING_SUFFIX", "terminal_app")


class TerminalAppHandler(FileHandler):
    def __init__(
        self,
        terminal_app_stream: TextIO | None,
        filename: str | os.PathLike[str],
        mode: str = "a",
        encoding: str | None = None,
        delay: bool = False,
        errors: str | None = None,
    ) -> None:
        super().__init__(filename, mode, encoding, delay, errors)
        self.terminal_app_stream = (
            terminal_app_stream if terminal_app_stream is not None else sys.stdout
        )

    def emit(self, record: logging.LogRecord) -> None:
        stream = self.stream
        reference = copy(record)
        reference.msg = self.get_line(self.baseFilename)
        reference.args = ()
        try:
            self.stream = cast(io.TextIOWrapper, self.terminal_app_stream)
            super().emit(reference)
        finally:
            self.stream = stream
        super().emit(record)

    @staticmethod
    def get_line(logger: Logger | str | Path) -> str:
        path: str | Path | None = logger if not isinstance(logger, Logger) else None
        if isinstance(logger, Logger):
            for handler in logger.handlers:
                if isinstance(handler, FileHandler):
                    path = handler.baseFilename
        if path is None:
            return ""
        try:
            with open(path, "rb") as source:
                return f"{path}, line {len(source.readlines()) + 1}"
        except OSError:
            return ""


class TerminalAppLogger(Logger):
    def _log(
        self,
        level,
        msg,
        args,
        exc_info=None,
        extra=None,
        stack_info=False,
        stacklevel=1,
    ) -> None:
        value = os.environ.get("TERMINAL_APP_LOGGER", "0").lower()
        if value in ("y", "yes", "t", "true", "on", "1"):
            super()._log(level, msg, args, exc_info, extra, stack_info, stacklevel)
        elif value not in ("n", "no", "f", "false", "off", "0"):
            raise ValueError(f"invalid truth value {value!r}")


def _clear_handlers(logger: Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)


def _select_logger(
    name: str | None, library: bool, level: int | str, if_exist: str
) -> tuple[Logger, bool]:
    if name in logging.Logger.manager.loggerDict or library:
        TERMINAL_APP_LOGGER.info("Change %s logger", name)
        logger = logging.getLogger(name)
        _clear_handlers(logger)
        return logger, False
    if name is None:
        return TerminalAppLogger(_suffix(), level), False
    naming = f"{_suffix()}.{name}"
    if naming in logging.Logger.manager.loggerDict:
        if if_exist == "return":
            return logging.getLogger(naming), True
        if if_exist == "clear":
            _clear_handlers(logging.getLogger(naming))
            logging.Logger.manager.loggerDict.pop(naming)
    assert (
        naming not in logging.Logger.manager.loggerDict
    ), "The same name of the loggers"
    return logging.getLogger(naming), False


def _startup_count(lines: list[str]) -> int:
    for line in reversed(lines):
        if line.startswith("STARTUP"):
            try:
                return int(line[-2]) + 1
            except ValueError:
                continue
    return 1


def _file_handler(
    path: Path, terminal_app_handler: bool, stream: TextIO | None
) -> FileHandler:
    mode = os.environ.get("LOGGING_FILE_MODE", "w")
    handler = (
        TerminalAppHandler(stream, path, mode=mode)
        if terminal_app_handler
        else FileHandler(path, mode=mode)
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(DEFAULT_FORMATTER)
    if mode.lower() != "w":
        with path.open(f"{mode}+") as destination:
            destination.seek(0)
            count = _startup_count(destination.readlines())
            destination.write(f"STARTUP {count}\n")
    return handler


@overload
def register_logger() -> TerminalAppLogger: ...


@overload
def register_logger(
    path: Path | str | None = None,
    name: str | None = None,
    library: bool = False,
    level: int | str = logging.DEBUG,
    terminal_app_handler: bool = False,
    terminal_app_stream: TextIO | None = None,
    without_handlers: bool = False,
    if_exist: Literal["error", "clear", "return"] = "error",
) -> Logger: ...


def register_logger(
    path: Path | str | None = None,
    name: str | None = None,
    library: bool = False,
    level: int | str = logging.DEBUG,
    terminal_app_handler: bool = False,
    terminal_app_stream: TextIO | None = None,
    without_handlers: bool = False,
    if_exist: Literal["error", "clear", "return"] = "error",
) -> Logger:
    file_path = RootLogging.root_path / path if isinstance(path, str) else path
    if name is None and file_path is not None:
        name = file_path.stem
    logger, existing = _select_logger(name, library, level, if_exist)
    if existing:
        return logger
    if not without_handlers:
        handler = (
            _file_handler(file_path, terminal_app_handler, terminal_app_stream)
            if file_path is not None
            else DEFAULT_STREAM
        )
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


class LoggingMeta(type):
    __root_path__: Callable[[], Path] = lambda: Path(
        os.environ.get("LOGGING_DIR", "logging")
    )
    logger: Logger
    root_logger: Logger

    @property
    def root_path(cls) -> Path:
        root = LoggingMeta.__root_path__()
        if not root.is_dir():
            root.mkdir()
        return root

    def __new__(
        mcls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]
    ) -> "LoggingMeta":
        cls = cast("LoggingMeta", super().__new__(mcls, name, bases, namespace))
        if "RootLogging" in [base.__name__ for base in bases] and os.getenv(
            f"{name}_LOGGING"
        ):
            cls.root_logger = register_logger(cls.root_path / f"{name}.log")
        if namespace.get("LOGGING") is True:
            file = Path(getfile(cls))
            cls.logger = register_logger(file.parent / (file.stem + ".log"), name=name)
        return cls


class RootLogging(metaclass=LoggingMeta):
    LOGGING = False


def getTerminalAppLogger(name: str) -> Logger:
    return logging.getLogger(f"{_suffix()}.{name}")


TERMINAL_APP_LOGGER = register_logger()
