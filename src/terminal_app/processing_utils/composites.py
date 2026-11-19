import math
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Sequence

import terminal_app.processing_utils.pipeline as pipeline

from .base import Callback, Stage
from .types import BranchResult, ErrorsDict, FilesWithMeta, StageResult


def first_successful_path(branches: Sequence[BranchResult]) -> Path:
    for branch in branches:
        if branch.passed:
            return branch.item.path
    raise ValueError("No successful branch provides an output path")


class SequenceStages(Stage):
    def __init__(
        self,
        name: str,
        stages: Sequence[Stage],
        callbacks: Sequence[Callback] | None = None,
        transition: Callable[..., StageResult] | None = None,
    ):
        if not stages:
            raise ValueError("A composite must contain at least one stage")
        self._name = name
        self.stages = tuple(stages)
        self.callbacks = list(callbacks or [])
        self._transition = transition

    @property
    def name(self) -> str:
        return self._name

    def __call__(self, filtered_files: FilesWithMeta | None) -> StageResult:
        return pipeline.run_stages([self], filtered_files=filtered_files)[self.name]

    def transition(
        self,
        all_files: FilesWithMeta,
        filtered_files: FilesWithMeta,
        errors: ErrorsDict,
    ) -> StageResult:
        if self._transition is not None:
            return self._transition(all_files, filtered_files, errors)
        return super().transition(all_files, filtered_files, errors)


class ParallelStages(SequenceStages):
    """Independent branches, evaluated in declaration order.

    Each branch receives a private metadata snapshot. Execution is intentionally
    sequential; this is a composition primitive, not a concurrency guarantee.
    """

    def __init__(
        self,
        name: str,
        stages: Sequence[Stage],
        callbacks: Sequence[Callback] | None = None,
        transition: Callable[..., StageResult] | None = None,
        pass_condition: Callable[[Sequence[bool]], bool] = all,
        output_path_selector: Callable[
            [Sequence[BranchResult]], Path
        ] = first_successful_path,
    ):
        super().__init__(name, stages, callbacks, transition)
        self.pass_condition = pass_condition
        self.output_path_selector = output_path_selector


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


def metadata_changes(before: dict, after: dict, prefix: tuple = ()) -> dict:
    changes = {}
    for key in before.keys() | after.keys():
        old, new = before.get(key, _MISSING), after.get(key, _MISSING)
        path = prefix + (key,)
        changes.update(_field_changes(old, new, path))
    return changes


def _field_changes(old: Any, new: Any, path: tuple) -> dict:
    if isinstance(new, dict) and new and (isinstance(old, dict) or old is _MISSING):
        return metadata_changes(old if isinstance(old, dict) else {}, new, path)
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
        for path, value in metadata_changes(original, branch.item.meta).items():
            _check_conflict(changes, path, value)
            changes[path] = value
    return _apply_changes(original, changes)
