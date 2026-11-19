import json
import logging
import os
import pickle
from pathlib import Path
from typing import Any, Callable

from terminal_app.utils import to_relative

from .types import (
    FilesWithMeta,
    PipesResult,
    StageResult,
    StageItem,
    StageError,
    normalize_items,
)
from .statistics import calculate_stats, find_closest_path

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)


def _json_default(obj: Any) -> str:

    if isinstance(obj, Path):
        return obj.as_posix()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def construct_relative_file(
    file: Path, source_folder: Path | None, dest_folder: Path | None, suffix: str
) -> Path:
    if not source_folder:
        relative_file = file.with_name(file.stem + suffix)
    else:
        relative_file = file.relative_to(source_folder).with_name(file.stem + suffix)
    return dest_folder / relative_file if dest_folder else relative_file


def files_transition(
    all_files: FilesWithMeta,
    filtered_files: FilesWithMeta,
    errors: dict[Path, str],
    construct_relative_file: Callable[[Path], Path],
) -> StageResult:

    def transition(
        files: FilesWithMeta,
    ):
        result: FilesWithMeta = []
        for item in normalize_items(files):
            relative_file = construct_relative_file(item.path)
            result.append(StageItem(item.item_id, relative_file, item.meta))
        return result

    return (
        transition(all_files),
        transition(filtered_files),
        errors,
    )


def save_pickle_callback(
    stages: PipesResult,
    root_folder: Path | None,
    output_path: Path | str,
    mapping: dict[str, str],
):
    filtered_files: list[dict[str, Path]] = [
        {k: Path(m[k]) for k in mapping} for f, m in list(stages.values())[-1][1]
    ]

    result: list[dict[str, str]] = []
    for py_file in filtered_files:
        result.append(
            {
                mapping[k]: (
                    file.relative_to(root_folder).as_posix()
                    if root_folder
                    else file.as_posix()
                )
                for k, file in py_file.items()
            }
        )

    Path(output_path).write_bytes(pickle.dumps(result))
    logger.info(f"Save {output_path}")


def _default_each_file_output_path(file: Path) -> Path:
    return file.with_name(f"{file.stem}_meta.json")


def save_meta_callback(
    stages: PipesResult,
    stage_name: str | None,
    stats_key: str | None,
    output_path: Path | str | None = None,
    filtered_only: bool = False,
    relative: bool = False,
    for_each_file: bool = False,
    replace_if_exists: bool = False,
    update_if_exists: bool = True,
    each_file_output_path: Callable[[Path], Path] | None = None,
    file_key: str | None = None,
):
    if stage_name:
        assert (
            stats_key is not None
        ), "stats_key is required when stage_name is provided"

    stage_index = list(stages.keys()).index(stage_name) if stage_name else -1
    meta: list[Any] = [
        m for _, m in list(stages.values())[stage_index][0 if not filtered_only else 1]  # type: ignore
    ]
    errors = list(stages.values())[stage_index][2]
    if for_each_file:
        for file, file_meta in list(stages.values())[stage_index][  # type: ignore
            0 if not filtered_only else 1
        ]:
            output_json_path = (
                each_file_output_path(file)
                if each_file_output_path
                else _default_each_file_output_path(file)
            )
            if output_json_path.is_symlink():
                continue

            file_meta_for_update = {}
            if output_json_path.exists():
                if not replace_if_exists and not update_if_exists:
                    continue
                if update_if_exists:
                    file_meta_for_update = json.loads(output_json_path.read_text())

            # A leaf owns only its statistics section. Never restore stale
            # sibling sections from its pre-execution metadata snapshot.
            update = (
                {stats_key: file_meta[stats_key]}
                if stats_key and stats_key in file_meta
                else {}
            )
            if stats_key is None:
                update = dict(file_meta)
            else:
                owned_file_key = (
                    file_key or stats_key.removesuffix("_statistics") + "_file"
                )
                if owned_file_key in file_meta:
                    update[owned_file_key] = file_meta[owned_file_key]
            if not update:
                messages = [
                    error.message if isinstance(error, StageError) else str(error)
                    for key, error in errors.items()
                    if (
                        error.path == file
                        if isinstance(error, StageError)
                        else key == file
                    )
                ]
                if messages:
                    error_meta = {"error": "; ".join(messages)}
                    update = {stats_key: error_meta} if stats_key else error_meta
            file_meta_for_update.update(update)
            file_meta = file_meta_for_update

            os.makedirs(output_json_path.parent, exist_ok=True)
            Path(output_json_path).write_text(
                json.dumps(
                    (
                        file_meta
                        if not relative
                        else to_relative(file_meta, Path(output_json_path).parent)
                    ),
                    indent=2,
                    ensure_ascii=False,
                    default=_json_default,
                )
            )
    if output_path:
        Path(output_path).write_text(
            json.dumps(
                (meta if not relative else to_relative(meta, Path(output_path).parent)),
                indent=2,
                ensure_ascii=False,
                default=_json_default,
            )
        )
        logger.info(f"Save {output_path}")


def dataset_stats(
    stages: PipesResult,
    stage_stats: (
        dict[
            str,
            Callable[
                [
                    PipesResult,
                    str,
                    dict[str, Any],
                ],
                None,
            ],
        ]
        | None
    ) = None,
    failed_output: Path | str | None = None,
    stat_output: Path | str | None = None,
    stdout: Callable | None = None,
    relative: bool = False,
    print_stats: bool = True,
):

    stat_dict = {}
    stat_dict["errors"] = {}
    failed_output_data = {}

    if stage_stats:
        for stage_name, stat_func in stage_stats.items():
            stat_func(stages, stage_name, stat_dict)

    for stage_name, (_, _, errors) in stages.items():
        grouped = {}
        for error in errors.values():
            entry = grouped.setdefault(
                error.message, {"count": 0, "example": error.path}
            )
            entry["count"] += 1
        stat_dict["errors"][stage_name] = grouped
        failed_output_data[stage_name] = {
            key: {
                "item_id": error.item_id,
                "path": error.path,
                "stage": error.stage,
                "message": error.message,
            }
            for key, error in errors.items()
        }

    if failed_output:
        Path(failed_output).write_text(
            json.dumps(
                (
                    failed_output_data
                    if not relative
                    else to_relative(
                        failed_output_data,
                        Path(failed_output).parent,
                    )
                ),
                indent=2,
                ensure_ascii=False,
                default=_json_default,
            )
        )
        if stdout:
            stdout(f"Save {failed_output}")

    if stat_output:

        Path(stat_output).write_text(
            json.dumps(
                (
                    stat_dict
                    if not relative
                    else to_relative(stat_dict, Path(stat_output).parent)
                ),
                indent=2,
                ensure_ascii=False,
                default=_json_default,
            )
        )

    if stdout:
        if print_stats:
            stdout(
                json.dumps(
                    stat_dict, indent=2, ensure_ascii=False, default=_json_default
                )
            )
        stdout(f"Save {stat_output}")
    return stat_dict


def stage_stats(
    stages: PipesResult,
    stage_name: str,
    stats: dict[str, Any],
    field_configs: dict[str, dict[str, Any]],
    file_key: str,
    stats_key: str,
):

    all_files = [
        (m[file_key], m[stats_key])
        for f, m in stages[stage_name][0]
        if file_key in m and stats_key in m
    ]
    filtered_files = [
        (m[file_key], m[stats_key])
        for f, m in list(stages.values())[-1][1]
        if file_key in m and stats_key in m
    ]

    stats[stats_key] = {
        f"all_{file_key}": calculate_stats(all_files, field_configs),
        f"filtered_{file_key}": calculate_stats(filtered_files, field_configs),
    }
