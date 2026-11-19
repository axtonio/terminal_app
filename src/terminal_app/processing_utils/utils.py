import json
import logging
import pickle
from pathlib import Path
from typing import Any, Callable

from .metadata_io import (
    MetaFileSettings,
    default_meta_path,
    json_default,
    save_item_metadata,
    write_json,
)
from .statistics import calculate_stats
from .statistics import find_closest_path as find_closest_path
from .types import (
    ErrorsDict,
    FilesWithMeta,
    PipesResult,
    StageItem,
    StageResult,
    normalize_items,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)


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
    errors: ErrorsDict,
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
    all_files, filtered, errors = list(stages.values())[stage_index]
    selected = filtered if filtered_only else all_files
    if for_each_file:
        settings = MetaFileSettings(
            stats_key,
            file_key,
            each_file_output_path or default_meta_path,
            replace_if_exists,
            update_if_exists,
            relative,
        )
        for item in selected:
            file, meta = item
            item_id = item.item_id if isinstance(item, StageItem) else None
            save_item_metadata(file, meta, errors, settings, item_id)
    if output_path:
        write_json(output_path, [meta for _, meta in selected], relative)
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

    stat_dict: dict[str, Any] = {"errors": {}}
    failed_output_data = {}
    for stage_name, stat_func in (stage_stats or {}).items():
        stat_func(stages, stage_name, stat_dict)
    for stage_name, (_, _, errors) in stages.items():
        stat_dict["errors"][stage_name] = _error_statistics(errors)
        failed_output_data[stage_name] = {
            key: {
                "item_id": error.item_id,
                "path": error.path,
                "stage": error.stage,
                "message": error.message,
            }
            for key, error in errors.items()
        }
    _save_dataset_outputs(
        failed_output, stat_output, failed_output_data, stat_dict, relative, stdout
    )
    if stdout:
        if print_stats:
            stdout(
                json.dumps(
                    stat_dict, indent=2, ensure_ascii=False, default=json_default
                )
            )
        stdout(f"Save {stat_output}")
    return stat_dict


def _error_statistics(errors: ErrorsDict) -> dict[str, Any]:
    grouped: dict[str, Any] = {}
    for error in errors.values():
        entry = grouped.setdefault(error.message, {"count": 0, "example": error.path})
        entry["count"] += 1
    return grouped


def _save_dataset_outputs(
    failed_output, stat_output, failed_data, statistics, relative, stdout
):
    if failed_output:
        write_json(failed_output, failed_data, relative)
        if stdout:
            stdout(f"Save {failed_output}")
    if stat_output:
        write_json(stat_output, statistics, relative)


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
