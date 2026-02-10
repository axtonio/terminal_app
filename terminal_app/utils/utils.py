from __future__ import annotations

import ast
import concurrent.futures
import glob
import json
import multiprocessing as mp
import os
import random
import re
import shutil
import string
from collections import UserDict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Literal, Sequence, TypeVar, overload

import tqdm
from natsort import natsorted, ns

from terminal_app.logging import TERMINAL_APP_LOGGER

T = TypeVar("T")


def cuda_count() -> int:
    vis = os.environ.get("CUDA_VISIBLE_DEVICES")
    if vis is not None:
        ids = [x for x in vis.split(",") if x.strip() != ""]
        if len(ids) > 0:
            return len(ids)
    try:
        import torch  # type: ignore

        return torch.cuda.device_count()
    except Exception:
        return 0


def list_cuda_devices():

    return [f"cuda:{i}" for i in range(cuda_count())]


def code_is_valid(code: str):
    try:
        ast.parse(code)
        return True
    except Exception:
        return False


class AllParams(UserDict):

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

    @overload
    def __getitem__(self, key: Literal["all_params"]) -> AllParams:
        pass

    @overload
    def __getitem__(self, key: Any) -> Any:
        pass

    def __getitem__(self, key: Any) -> Any:
        return super().__getitem__(key)


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

    def copy_file(src: Path | str, dst: Path | str) -> None:
        shutil.copy2(src, dst)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                copy_file,
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


def annotations_to_path_list(
    annotations: Path | str | Sequence[Path | str],
) -> list[Path]:

    def _has_glob_tokens(text: Any) -> bool:
        text = str(text)
        return any(token in text for token in ("*", "?", "[", "]"))

    def _resolve_mesh_path(entry: str, base_dir: Path) -> str:
        path = Path(entry)
        if not path.is_absolute():
            path = base_dir / path
        return path.as_posix()

    if isinstance(annotations, Sequence) and not isinstance(annotations, str):
        result = []
        for item in annotations:
            result.extend(annotations_to_path_list(item))
        return result

    candidate = Path(annotations)
    if candidate.exists() and not _has_glob_tokens(annotations):
        if candidate.suffix.lower() == ".json":
            base_dir = candidate.parent
            annotations = json.loads(candidate.read_text(encoding="utf-8"))
        else:
            base_dir = Path.cwd()
            annotations = [str(annotations)]
        if not isinstance(annotations, list):
            raise TypeError(
                f"Annotation file {candidate} must contain a JSON array or newline list"
            )
        resolved = [
            Path(_resolve_mesh_path(str(item), base_dir))
            for item in annotations
            if isinstance(item, (str, Path))
        ]
        if not resolved:
            raise ValueError(f"No mesh paths could be resolved from {candidate}")
        return resolved

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


def to_relative(data: Any, root: Path | str, reverse: bool = False) -> Any:
    root = Path(root).resolve()

    def _resolve_path(p: Path | str) -> str:
        p_obj = Path(p)
        if p_obj.is_absolute():
            return p_obj.as_posix()
        return (root / p).resolve().as_posix()

    def _make_relative(p: Path | str) -> str:
        try:
            return (
                Path("{json_path}") / os.path.relpath(Path(p).resolve(), root)
            ).as_posix()
        except ValueError:
            return Path(p).as_posix()

    def _process_item(obj: Any) -> Any:
        if isinstance(obj, Path):

            return _resolve_path(obj) if reverse else _make_relative(obj)

        if isinstance(obj, str):
            try:
                if reverse:
                    resolved = (root / obj).resolve()
                    if not Path(obj).is_absolute() and resolved.exists():
                        return resolved.as_posix()
                else:
                    if Path(obj).exists():
                        return _make_relative(obj)
            except Exception:
                return obj

        return obj

    return recursive_map(data, _process_item)
