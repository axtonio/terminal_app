import math
from copy import deepcopy
from typing import Any, Sequence

from .types import BranchResult

# A missing key differs from an explicit None: branch merges must distinguish
# deleting a metadata field from setting that field to None.
_MISSING = object()


def _equal(left, right):
    if (
        isinstance(left, float)
        and isinstance(right, float)
        and math.isnan(left)
        and math.isnan(right)
    ):
        return True
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _equal(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(
            _equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def _metadata_changes(before: dict, after: dict, prefix: tuple = ()) -> dict:
    changes = {}
    for key in before.keys() | after.keys():
        old, new = before.get(key, _MISSING), after.get(key, _MISSING)
        path = prefix + (key,)
        changes.update(_field_changes(old, new, path))
    return changes


def _field_changes(old: Any, new: Any, path: tuple) -> dict:
    if isinstance(new, dict) and new and (isinstance(old, dict) or old is _MISSING):
        return _metadata_changes(old if isinstance(old, dict) else {}, new, path)
    if old is _MISSING or new is _MISSING or not _equal(old, new):
        return {path: new}
    return {}


def _check_conflict(changes: dict, path: tuple, value: Any) -> None:
    for previous, previous_value in changes.items():
        if previous == path:
            conflict = not _equal(value, previous_value)
        else:
            conflict = (
                path[: len(previous)] == previous or previous[: len(path)] == path
            )
        if conflict:
            raise ValueError(f"Conflicting branch metadata at {'.'.join(path)}")


def _apply_changes(original: dict, changes: dict) -> dict:
    result = deepcopy(original)
    for path, value in changes.items():
        target = result
        for key in path[:-1]:
            target = target.setdefault(key, {})
        if value is _MISSING:
            target.pop(path[-1], None)
        else:
            target[path[-1]] = deepcopy(value)
    return result


def merge_branch_metadata(original: dict, branches: Sequence[BranchResult]) -> dict:
    changes: dict[tuple, Any] = {}
    for branch in branches:
        for path, value in _metadata_changes(original, branch.item.meta).items():
            _check_conflict(changes, path, value)
            changes[path] = value
    return _apply_changes(original, changes)
