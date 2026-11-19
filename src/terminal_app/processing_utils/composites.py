import math
from copy import deepcopy
from pathlib import Path
from typing import Callable, Sequence

from .base import Callback, Stage
from .types import BranchResult, FilesWithMeta, StageResult


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
        if transition is not None:
            self.transition = transition

    @property
    def name(self) -> str:
        return self._name

    def __call__(self, filtered_files: FilesWithMeta | None) -> StageResult:
        from .pipeline import run_stages

        return run_stages([self], filtered_files=filtered_files)[self.name]


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
            _equal(a, b) for a, b in zip(left, right)
        )
    return left == right


def metadata_changes(before: dict, after: dict, prefix: tuple = ()) -> dict:
    changes = {}
    for key in before.keys() | after.keys():
        old, new = before.get(key, _MISSING), after.get(key, _MISSING)
        path = prefix + (key,)
        if isinstance(new, dict) and new and (isinstance(old, dict) or old is _MISSING):
            changes.update(metadata_changes({} if old is _MISSING else old, new, path))
        elif old is _MISSING or new is _MISSING or not _equal(old, new):
            changes[path] = new
    return changes


def merge_branch_metadata(original: dict, branches: Sequence[BranchResult]) -> dict:
    changes = {}
    for branch in branches:
        for path, value in metadata_changes(original, branch.item.meta).items():
            for previous, previous_value in changes.items():
                if previous == path:
                    if not _equal(value, previous_value):
                        raise ValueError(
                            f"Conflicting branch metadata at {'.'.join(path)}"
                        )
                elif path[: len(previous)] == previous or previous[: len(path)] == path:
                    raise ValueError(f"Conflicting branch metadata at {'.'.join(path)}")
            changes[path] = value
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
