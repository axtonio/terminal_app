import json
import logging
import math
import os
import pickle
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

import numpy as np

from terminal_app.utils import filter_by_regex, is_regex_pattern, to_relative

from .types import FilesWithMeta, PipesResult, StageResult

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
        for file, meta in files:
            relative_file = construct_relative_file(file)
            result.append(
                (
                    relative_file,
                    meta,
                )
            )
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

            if not file_meta:
                if file in errors:
                    if stage_name:
                        assert stats_key is not None
                        if stats_key not in file_meta:
                            file_meta[stats_key] = {}
                        file_meta[stats_key]["error"] = errors[file]
                    else:
                        file_meta["error"] = errors[file]

            file_meta_for_update.update(file_meta)
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


def find_closest_path(values, target_value, paths):
    if not values or not paths:
        return None

    differences = [abs(value - target_value) for value in values]
    closest_idx = np.argmin(differences)
    return paths[closest_idx]


def calculate_stats(
    data_list: list[tuple[str, Any]], field_configs: dict[str, dict[str, bool]]
):
    if not data_list:
        return None

    values_dict: dict[str, list[tuple[str, float | bool]]] = defaultdict(lambda: [])

    field_configs = field_configs.copy()
    field_configs_copy = field_configs.copy()
    for path, data in data_list:
        data_dict: dict[str, Any] = data.dict() if hasattr(data, "dict") else data
        for field in field_configs_copy.keys():

            def add_value(field: str):
                value = data_dict.get(field)
                if value is not None and not math.isnan(value):
                    values_dict[field].append((path, value))

            if not is_regex_pattern(field):
                add_value(field)
            else:
                ff = filter_by_regex(list(data_dict.keys()), field)
                for f in [_f for _f in ff if _f not in field_configs_copy.keys()]:
                    field_configs[f] = field_configs[field]
                    add_value(f)

    count = len(data_list)
    result = {"count": count, "examples": {}}

    # Вычисляем статистики для каждого поля
    for field, items in values_dict.items():
        config = field_configs[field]
        values = [v for _, v in items]
        paths = [p for p, _ in items]
        store_examples = config.get("store_examples", False)

        if not values:
            continue

        min_idx = np.argmin(values)
        max_idx = np.argmax(values)
        if field.startswith("is_"):
            result[f"{field}_count"] = int(sum(values))
            result[f"{field}_ratio"] = float(sum(values) / count)

            if store_examples:

                if min_idx == max_idx and values[max_idx] == 0.0:
                    continue
                result["examples"][field] = (
                    paths[max_idx] if paths[max_idx] else "unknown"
                )
        else:
            mean_val = float(np.mean(values))
            median_val = float(np.median(values))
            min_val = float(np.min(values))
            max_val = float(np.max(values))
            std_val = float(np.std(values))

            quantile_25 = float(np.quantile(values, 0.25))
            quantile_75 = float(np.quantile(values, 0.75))
            quantile_90 = float(np.quantile(values, 0.90))

            if mean_val == median_val == min_val == max_val == std_val == 0.0:
                continue

            result[f"{field}_mean"] = mean_val
            result[f"{field}_median"] = median_val
            result[f"{field}_min"] = min_val
            result[f"{field}_max"] = max_val
            result[f"{field}_std"] = std_val

            result[f"{field}_quantile_25"] = quantile_25
            result[f"{field}_quantile_75"] = quantile_75
            result[f"{field}_quantile_90"] = quantile_90

            if store_examples:

                if min_idx == max_idx:
                    continue
                result["examples"][f"min_{field}"] = (
                    paths[min_idx] if paths[min_idx] else "unknown"
                )
                result["examples"][f"max_{field}"] = (
                    paths[max_idx] if paths[max_idx] else "unknown"
                )
                result["examples"][f"mean_{field}"] = find_closest_path(
                    values, mean_val, paths
                )
                result["examples"][f"median_{field}"] = find_closest_path(
                    values, median_val, paths
                )

                result["examples"][f"quantile_25_{field}"] = find_closest_path(
                    values, quantile_25, paths
                )
                result["examples"][f"quantile_75_{field}"] = find_closest_path(
                    values, quantile_75, paths
                )
                result["examples"][f"quantile_90_{field}"] = find_closest_path(
                    values, quantile_90, paths
                )

    return result


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
        failed_files = list(errors.keys())
        stat_dict["errors"][stage_name] = {
            k: {
                "count": int(v),
                "example": (failed_files[i] if i < len(failed_files) else "unknown"),
            }
            for k, i, v in zip(
                *np.unique(
                    np.array(list(errors.values())),
                    return_index=True,
                    return_counts=True,
                )
            )
        }

        # Convert Path to string for JSON serialization, _json_default not support keys
        failed_output_data[stage_name] = {p.as_posix(): e for p, e in errors.items()}

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
    field_configs: dict[str, dict[str, bool]],
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
