"""Persist the section owned by a stage without overwriting sibling metadata."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from terminal_app.utils.utils import to_relative

from .types import StageError


def json_default(obj: Any) -> str:
    if isinstance(obj, Path):
        return obj.as_posix()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def write_json(path: Path | str, data: Any, relative: bool) -> None:
    path = Path(path)
    payload = to_relative(data, path.parent) if relative else data
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=json_default)
    )


def default_meta_path(file: Path) -> Path:
    return file.with_name(f"{file.stem}_meta.json")


@dataclass(frozen=True)
class MetaFileSettings:
    stats_key: str | None
    file_key: str | None
    output_path: Callable[[Path], Path]
    replace_if_exists: bool
    update_if_exists: bool
    relative: bool


def _existing_metadata(path: Path, settings: MetaFileSettings) -> dict | None:
    if path.is_symlink():
        return None
    if not path.exists():
        return {}
    if not settings.replace_if_exists and not settings.update_if_exists:
        return None
    return json.loads(path.read_text()) if settings.update_if_exists else {}


def _owned_metadata(meta: dict, settings: MetaFileSettings) -> dict:
    if settings.stats_key is None:
        return dict(meta)
    update = {}
    if settings.stats_key in meta:
        update[settings.stats_key] = meta[settings.stats_key]
    file_key = (
        settings.file_key or settings.stats_key.removesuffix("_statistics") + "_file"
    )
    if file_key in meta:
        update[file_key] = meta[file_key]
    return update


def _matches_file(key, error, file):
    return error.path == file if isinstance(error, StageError) else key == file


def _error_metadata(file: Path, errors: dict, stats_key: str | None) -> dict:
    messages = [
        error.message if isinstance(error, StageError) else str(error)
        for key, error in errors.items()
        if _matches_file(key, error, file)
    ]
    if not messages:
        return {}
    entry = {"error": "; ".join(messages)}
    return {stats_key: entry} if stats_key else entry


def save_item_metadata(
    file: Path, meta: dict, errors: dict, settings: MetaFileSettings
) -> None:
    path = settings.output_path(file)
    saved = _existing_metadata(path, settings)
    if saved is None:
        return
    # A leaf owns only its statistics and file keys. Read sibling sections from
    # disk instead of restoring them from the leaf's older metadata snapshot.
    update = _owned_metadata(meta, settings) or _error_metadata(
        file, errors, settings.stats_key
    )
    saved.update(update)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, saved, settings.relative)
