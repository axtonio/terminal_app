import ast
import concurrent.futures
import glob
import importlib
import json
import logging
import multiprocessing as mp
import os
import random
import re
import shutil
import string
import subprocess
from collections import UserDict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Literal, Sequence, TypeVar

import tqdm
from natsort import natsorted, ns

from terminal_app.logging.logging import TERMINAL_APP_LOGGER

T = TypeVar("T")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)


def _nvidia_gpu_count() -> int:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--list-gpus"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            count = sum("GPU" in line for line in result.stdout.splitlines())
            if count:
                return count
        logger.warning(
            "nvidia-smi did not run successfully: %s. Returning 0.", result.stderr
        )
    except Exception as error:
        logger.warning(
            "Error getting CUDA count with nvidia-smi: %s. Returning 0.", error
        )
    return 0


def cuda_count() -> int:
    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if visible is not None:
        ids = [value for value in visible.split(",") if value.strip()]
        if ids:
            return len(ids)
    try:
        # PyTorch is optional and expensive; GPU discovery alone may load it.
        torch = importlib.import_module("torch")  # noqa: TID251
        return int(torch.cuda.device_count())
    except Exception as error:
        logger.warning(
            "Error getting CUDA count with torch: %s. Trying nvidia-smi...", error
        )
    return _nvidia_gpu_count()


def list_cuda_devices():

    return [f"cuda:{i}" for i in range(cuda_count())]


def code_is_valid(code: str):
    try:
        ast.parse(code)
        return True
    except Exception:
        return False


class AllParams(UserDict[Any, Any]):

    def __init__(self, mapping=None, /, **kwargs):
        if mapping is not None:
            mapping = {key: value for key, value in mapping.items()}
        else:
            mapping = {}
        if kwargs:
            mapping.update(kwargs)
        super().__init__(mapping)
        self["all_params"] = self

    def __setitem__(self, key: Any, item: Any) -> None:
        if key == "all_params":
            item = self

        return super().__setitem__(key, item)


def chunks(array: list[T], size: int) -> list[list[T]]:
    return [array[x : x + size] for x in range(0, len(array), size)]


def random_day(day1: date, day2: date) -> date:
    total_days = (day2 - day1).days

    randays = random.randrange(total_days)

    return day1 + timedelta(days=int(randays))


def random_string() -> str:
    # choose from all lowercase letter
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for _ in range(random.randrange(1, 10)))


def filter_by_regex(strings: list[str], pattern: str) -> list[str]:
    """Фильтрует строки по регулярному выражению"""
    regex = re.compile(pattern)
    return list(filter(lambda s: regex.match(s), strings))


def is_regex_pattern(s):
    """Проверяет, является ли строка регулярным выражением"""
    if not isinstance(s, str):
        return False

    # Специальные символы regex, которые редко встречаются в обычном тексте
    regex_special_chars = [
        "*",
        "+",
        "?",
        "^",
        "$",
        "[",
        "]",
        "(",
        ")",
        "{",
        "}",
        "|",
        "\\",
    ]

    # Если строка содержит специальные символы regex
    has_special_chars = any(char in s for char in regex_special_chars)

    # Проверяем валидность как regex
    try:
        re.compile(s)
        is_valid_regex = True
    except re.error:
        is_valid_regex = False

    # Считаем это regex если есть спецсимволы И это валидное regex
    return has_special_chars and is_valid_regex


def get_path(
    name: Path,
    x: int = 0,
    object_type: Literal["file", "dir"] = "file",
    create: bool = True,
) -> Path:
    new_path = Path(
        name.parent
        / ((name.stem + ("_" + str(x) if x != 0 else "")).strip() + name.suffix)
    )
    if not new_path.exists():

        if create:
            if object_type == "dir":
                os.mkdir(new_path)
            else:
                with open(new_path, "w"):
                    pass

        return new_path
    else:
        return get_path(name, x + 1, object_type, create)


def fast_copy(
    files: Sequence[Path | str],
    dest_folder: Path | str,
    max_workers: int | None = None,
    replace_if_exists: bool = True,
    relative_func: Callable[[Path | str], str] = lambda x: Path(x).name,
) -> None:
    dest_folder = Path(dest_folder)

    dest_folder.mkdir(exist_ok=True)
    if max_workers is None:
        max_workers = mp.cpu_count()

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                shutil.copy2,
                file,
                (
                    dest_folder / relative_func(file)
                    if replace_if_exists
                    else get_path(dest_folder / relative_func(file))
                ),
            )
            for file in files
        ]

        with tqdm.tqdm(total=len(futures), desc="Copy files") as pbar:
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    TERMINAL_APP_LOGGER.error(f"Copy failed: {e}")
                finally:
                    pbar.update(1)


def _annotation_file(candidate: Path, read_json: bool) -> list[Path]:
    if candidate.suffix.lower() == ".json" and read_json:
        entries = json.loads(candidate.read_text(encoding="utf-8"))
        base = candidate.parent
    else:
        entries = [candidate]
        base = Path.cwd()
    if not isinstance(entries, list):
        raise TypeError(
            f"Annotation file {candidate} must contain a JSON array or newline list"
        )
    resolved = []
    for entry in entries:
        if isinstance(entry, (str, Path)):
            path = Path(entry)
            resolved.append(path if path.is_absolute() else base / path)
    if not resolved:
        raise ValueError(f"No mesh paths could be resolved from {candidate}")
    return resolved


def annotations_to_path_list(
    annotations: Path | str | Sequence[Path | str], read_json: bool = False
) -> list[Path]:
    if not isinstance(annotations, (str, Path)):
        result = []
        for item in annotations:
            result.extend(annotations_to_path_list(item))
        return result
    candidate = Path(annotations)
    if candidate.exists() and not any(
        token in str(annotations) for token in ("*", "?", "[", "]")
    ):
        return _annotation_file(candidate, read_json)
    matches = glob.glob(str(annotations))
    if not matches:
        raise FileNotFoundError(
            f"No meshes found using annotation pattern {annotations!r}"
        )
    return natsorted([Path(match) for match in matches], alg=ns.IGNORECASE)


def recursive_map(data: Any, func: Callable[[Any], Any]) -> Any:
    if isinstance(data, dict):
        return {recursive_map(k, func): recursive_map(v, func) for k, v in data.items()}
    elif isinstance(data, (list, tuple)):
        return [recursive_map(x, func) for x in data]
    return func(data)


def _make_relative(path: Path | str, root: Path) -> str:
    try:
        return (
            Path("{json_path}") / os.path.relpath(Path(path).resolve(), root)
        ).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _resolve_relative_path(path: Path, root: Path) -> str:
    return path.as_posix() if path.is_absolute() else (root / path).resolve().as_posix()


def _restore_relative_string(path: Path, root: Path, original: str) -> str:
    resolved = (root / path).resolve()
    if not path.is_absolute() and resolved.exists():
        return resolved.as_posix()
    return original


def _relative_string(value: str, root: Path, reverse: bool) -> str:
    try:
        path = Path(value)
        if reverse:
            return _restore_relative_string(path, root, value)
        return _make_relative(path, root) if path.exists() else value
    except (OSError, ValueError):
        return value


def _relative_item(value: Any, root: Path, reverse: bool) -> Any:
    if isinstance(value, Path):
        return (
            _resolve_relative_path(value, root)
            if reverse
            else _make_relative(value, root)
        )
    if isinstance(value, str):
        return _relative_string(value, root, reverse)
    return value


def to_relative(data: Any, root: Path | str, reverse: bool = False) -> Any:
    base = Path(root).resolve()
    return recursive_map(data, lambda value: _relative_item(value, base, reverse))


def link_file(link: Path, output_path: Path):
    if output_path.exists() or output_path.is_symlink():
        output_path.unlink()

    os.symlink(link, output_path)
