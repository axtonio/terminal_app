"""Persist the section owned by a stage without overwriting sibling metadata."""

import json
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable

from terminal_app.utils.utils import recursive_map, to_relative

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


def read_metadata(path: Path) -> dict:
    source_root = path.resolve().parent.as_posix()
    # Expand decoded values so quoted directory names cannot corrupt JSON.
    # Linked metadata keeps references relative to the source file's directory.
    return recursive_map(
        json.loads(path.read_text()),
        lambda value: (
            value.replace("{json_path}", source_root)
            if isinstance(value, str)
            else value
        ),
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
    if not path.exists():
        return {}
    if not settings.replace_if_exists and not settings.update_if_exists:
        return None
    return read_metadata(path) if settings.update_if_exists else {}


def _owned_metadata(meta: dict, settings: MetaFileSettings) -> dict:
    if settings.stats_key is None:
        return dict(meta)
    update = {}
    if settings.stats_key in meta:
        update[settings.stats_key] = meta[settings.stats_key]
    if settings.file_key is not None and settings.file_key in meta:
        update[settings.file_key] = meta[settings.file_key]
    return update


def _matches_item(key, error, file, item_id):
    if isinstance(error, StageError):
        return error.item_id == item_id if item_id is not None else error.path == file
    return key == file


def _error_metadata(
    file: Path, errors: dict, stats_key: str | None, item_id: str | None
) -> dict:
    messages = [
        error.message if isinstance(error, StageError) else str(error)
        for key, error in errors.items()
        if _matches_item(key, error, file, item_id)
    ]
    if not messages:
        return {}
    entry = {"error": "; ".join(messages)}
    return {stats_key: entry} if stats_key else entry


def save_item_metadata(
    file: Path,
    meta: dict,
    errors: dict,
    settings: MetaFileSettings,
    item_id: str | None = None,
) -> None:
    path = settings.output_path(file)
    saved = _existing_metadata(path, settings)
    if saved is None:
        return
    # A leaf owns only its statistics and file keys. Read sibling sections from
    # disk instead of restoring them from the leaf's older metadata snapshot.
    update = _owned_metadata(meta, settings)
    section = update.get(settings.stats_key, {}) if settings.stats_key else update
    if not section.get("error") and not section.get("warning"):
        failure = _error_metadata(file, errors, settings.stats_key, item_id)
        if settings.stats_key and failure:
            update[settings.stats_key] = {**section, **failure[settings.stats_key]}
        else:
            update.update(failure)
    if not update:
        return
    saved.update(update)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_symlink():
        write_json(path, saved, settings.relative)
        return
    # Replace the local link only after its complete replacement is written.
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        replacement = Path(temporary.name)
    try:
        write_json(replacement, saved, settings.relative)
        replacement.replace(path)
    finally:
        replacement.unlink(missing_ok=True)
