import json
import logging
import math
import pickle
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

import numpy as np

from terminal_app.utils import filter_by_regex, is_regex_pattern, to_relative

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


def files_transition(
    all_files: list[tuple[Path, dict[str, Any]]],
    filtered_files: list[tuple[Path, dict[str, Any]]],
    errors: dict[Path, str],
    source_folder: Path,
    dest_folder: Path,
    dest_suffix: str,
):
    def transition(
        files: list[tuple[Path, dict[str, Any]]],
        py_folder: Path,
        stl_folder: Path,
    ):
        result = []
        for file, meta in files:
            result.append(
                (
                    stl_folder / file.relative_to(py_folder).with_suffix(dest_suffix),
                    meta,
                )
            )
        return result

    return (
        transition(all_files, source_folder, dest_folder),
        transition(filtered_files, source_folder, dest_folder),
        errors,
    )


def save_pickle_callback(
    stages: dict[
        str,
        tuple[
            list[tuple[Path, dict[str, Any]]],
            list[tuple[Path, dict[str, Any]]],
            dict[Path, str],
        ],
    ],
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
    stages: dict[
        str,
        tuple[
            list[tuple[Path, dict[str, Any]]],
            list[tuple[Path, dict[str, Any]]],
            dict[Path, str],
        ],
    ],
    output_path: Path | str,
    stage_index: int = -1,
    filtered_only: bool = False,
    relative: bool = False,
):
    meta: list[Any] = [
        m for _, m in list(stages.values())[stage_index][0 if not filtered_only else 1]  # type: ignore
    ]

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
                for f in ff:
                    field_configs[f] = field_configs[field]
                [add_value(f) for f in ff]

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
    stages: dict[
        str,
        tuple[
            list[tuple[Path, dict[str, Any]]],
            list[tuple[Path, dict[str, Any]]],
            dict[Path, str],
        ],
    ],
    stage_stats: (
        dict[
            str,
            Callable[
                [
                    dict[
                        str,
                        tuple[
                            list[tuple[Path, dict[str, Any]]],
                            list[tuple[Path, dict[str, Any]]],
                            dict[Path, str],
                        ],
                    ],
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
):
    failed_files_with_error = list(stages.values())[-1][2]
    if failed_output:

        Path(failed_output).write_text(
            json.dumps(
                (
                    {p.as_posix(): e for p, e in failed_files_with_error.items()}
                    if not relative
                    else to_relative(
                        {p.as_posix(): e for p, e in failed_files_with_error.items()},
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

    stat_dict = {}

    if stage_stats:
        for stage_name, stat_func in stage_stats.items():
            stat_func(stages, stage_name, stat_dict)

    failed_files = list(failed_files_with_error.keys())
    stat_dict["errors"] = {
        k: {
            "count": int(v),
            "example": (failed_files[i] if i < len(failed_files) else "unknown"),
        }
        for k, i, v in zip(
            *np.unique(
                np.array(list(failed_files_with_error.values())),
                return_index=True,
                return_counts=True,
            )
        )
    }

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
        stdout(
            json.dumps(stat_dict, indent=2, ensure_ascii=False, default=_json_default)
        )
        stdout(f"Save {stat_output}")
    return stat_dict


def stage_stats(
    stages: dict[
        str,
        tuple[
            list[tuple[Path, dict[str, Any]]],
            list[tuple[Path, dict[str, Any]]],
            dict[Path, str],
        ],
    ],
    stage_name: str,
    stats: dict[str, Any],
    field_configs: dict[str, dict[str, bool]],
    file_key: str,
    stats_key: str,
):

    py_files_all = [
        (m[file_key], m[stats_key])
        for f, m in stages[stage_name][0]
        if file_key in m and stats_key in m
    ]
    filtered_py_files = [
        (m[file_key], m[stats_key])
        for f, m in list(stages.values())[-1][1]
        if file_key in m and stats_key in m
    ]

    stats[stats_key] = {
        f"all_{file_key}": calculate_stats(py_files_all, field_configs),
        f"filtered_{file_key}": calculate_stats(filtered_py_files, field_configs),
    }
