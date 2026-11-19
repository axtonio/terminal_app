import math
from typing import Any

import numpy as np

from terminal_app.utils import filter_by_regex, is_regex_pattern

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
    result = {}
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
    result = {name: {"value": None, "example": None} for name in STATISTICS}
    if not values:
        return result
    calculated = {
        "mean": np.mean(values),
        "median": np.median(values),
        "min": min(values),
        "max": max(values),
        "std": np.std(values),
        "quantile_25": np.quantile(values, 0.25),
        "quantile_75": np.quantile(values, 0.75),
        "quantile_90": np.quantile(values, 0.90),
    }
    for name, value in calculated.items():
        result[name]["value"] = float(value) if math.isfinite(value) else None
        if store_examples and name != "std" and result[name]["value"] is not None:
            result[name]["example"] = find_closest_path(values, float(value), paths)
    return result


def _ratio(items, group_count, config):
    if any(value not in (False, True, 0, 1) for _, value in items):
        raise ValueError("Ratio fields must contain booleans or 0/1 values")
    positive = [(path, value) for path, value in items if bool(value)]
    negative = [(path, value) for path, value in items if not bool(value)]
    denominator = config.get("denominator", "group")
    if denominator not in ("group", "observed"):
        raise ValueError("Ratio denominator must be 'group' or 'observed'")
    count = group_count if denominator == "group" else len(items)
    examples = config.get("store_examples", False)
    return {
        "count": len(positive),
        "ratio": len(positive) / count if count and items else None,
        "positive_example": (positive[0][0] or None) if examples and positive else None,
        "negative_example": (negative[0][0] or None) if examples and negative else None,
    }


def calculate_stats(
    data_list: list[tuple[str, Any]], field_configs: dict[str, dict[str, Any]]
):
    """Describe one selection. Group predicates and overall metrics live elsewhere.

    Each field declares ``kind='statistics'`` or ``kind='ratio'``. Legacy
    configurations without a kind retain the old ``is_`` convention. Ratio
    denominators default to the complete group, including missing observations;
    use ``denominator='observed'`` explicitly for another domain policy. Missing
    observations are never selected as negative examples.
    """
    data = [
        (path, row.dict() if hasattr(row, "dict") else row) for path, row in data_list
    ]
    result = {"statistics": {}, "ratios": {}, "summary": {"count": len(data)}}
    for field, config in _field_configs(data, field_configs).items():
        kind = config.get("kind", "ratio" if field.startswith("is_") else "statistics")
        if kind not in ("statistics", "ratio"):
            raise ValueError(f"Unknown field kind for {field}: {kind}")
        items = []
        for path, row in data:
            value = row.get(field)
            if value is not None and math.isfinite(value):
                items.append((path, value))
        if kind == "ratio":
            result["ratios"][field] = _ratio(items, len(data), config)
        else:
            result["statistics"][field] = _numeric(
                items, config.get("store_examples", False)
            )
    return result
