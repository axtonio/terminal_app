import math
from typing import Any

import numpy as np

from terminal_app.utils.utils import filter_by_regex, is_regex_pattern

STATISTICS = (
    "mean",
    "median",
    "min",
    "max",
    "std",
    "quantile_25",
    "quantile_75",
    "quantile_90",
)


def find_closest_path(values, target_value, paths):
    if not values or not paths:
        return None
    index = min(range(len(values)), key=lambda i: abs(values[i] - target_value))
    return paths[index] or None


def _field_configs(data, field_configs):
    result: dict[str, dict[str, Any]] = {}
    fields = set().union(*(row.keys() for _, row in data)) if data else set()
    for field, config in field_configs.items():
        if is_regex_pattern(field):
            for matched in sorted(filter_by_regex(list(fields), field)):
                result.setdefault(matched, config)
        else:
            result[field] = config
    return result


def _numeric(items, store_examples):
    values = [float(value) for _, value in items]
    paths = [path for path, _ in items]
    result: dict[str, dict[str, Any]] = {
        name: {"value": None, "example": None} for name in STATISTICS
    }
    if not values:
        return result
    calculated = {
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "min": min(values),
        "max": max(values),
        "std": float(np.std(values)),
        "quantile_25": float(np.quantile(values, 0.25)),
        "quantile_75": float(np.quantile(values, 0.75)),
        "quantile_90": float(np.quantile(values, 0.90)),
    }
    for name, value in calculated.items():
        result[name]["value"] = float(value) if math.isfinite(value) else None
        if store_examples and name != "std" and result[name]["value"] is not None:
            result[name]["example"] = find_closest_path(values, float(value), paths)
    return result


def _first_example(items, enabled):
    return (items[0][0] or None) if enabled and items else None


def _ratio(items, group_count, config):
    if any(value not in (False, True, 0, 1) for _, value in items):
        raise ValueError("Ratio fields must contain booleans or 0/1 values")
    positive = [(path, value) for path, value in items if bool(value)]
    negative = [(path, value) for path, value in items if not bool(value)]
    examples = config.get("store_examples", False)
    return {
        "count": len(positive),
        "ratio": len(positive) / group_count if group_count and items else None,
        "positive_example": _first_example(positive, examples),
        "negative_example": _first_example(negative, examples),
    }


def _observed_items(data, field):
    items = []
    for path, row in data:
        value = row.get(field)
        if value is not None and math.isfinite(value):
            items.append((path, value))
    return items


def _field_kind(field, config):
    kind = config.get("kind", "ratio" if field.startswith("is_") else "statistics")
    if kind not in ("statistics", "ratio"):
        raise ValueError(f"Unknown field kind for {field}: {kind}")
    return kind


def calculate_stats(
    data_list: list[tuple[str, Any]], field_configs: dict[str, dict[str, Any]]
):
    """Describe one selection. Group predicates and overall metrics live elsewhere.

    Each field declares ``kind='statistics'`` or ``kind='ratio'``. Legacy
    configurations without a kind retain the old ``is_`` convention. Ratio
    denominators use the complete group, including missing observations. Missing
    observations are never selected as negative examples.
    """
    data = [
        (path, row.dict() if hasattr(row, "dict") else row) for path, row in data_list
    ]
    result = {"statistics": {}, "ratios": {}, "summary": {"count": len(data)}}
    for field, config in _field_configs(data, field_configs).items():
        kind = _field_kind(field, config)
        items = _observed_items(data, field)
        if kind == "ratio":
            result["ratios"][field] = _ratio(items, len(data), config)
        else:
            result["statistics"][field] = _numeric(
                items, config.get("store_examples", False)
            )
    return result
