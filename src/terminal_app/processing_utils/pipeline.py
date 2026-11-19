import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Sequence

from .base import Callback, Stage
from .branch_metadata import merge_branch_metadata
from .types import (
    BranchResult,
    ErrorsDict,
    FilesWithMeta,
    PipesResult,
    StageError,
    StageResult,
    add_error,
    normalize_items,
)


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
        return run_stages([self], filtered_files=filtered_files)[self.name]

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


def _stdout(value):
    return None


def _validate_stage_names(stages: Sequence[Stage]) -> None:
    names = [stage.name for stage in stages]
    if len(set(names)) != len(names) or any(not name or "/" in name for name in names):
        raise ValueError(f"Invalid or duplicate stage names: {names!r}")


def _stage_paths(stages: Sequence[Stage]) -> dict[str, Stage]:
    _validate_stage_names(stages)
    paths: dict[str, Stage] = {}
    seen = set()
    pending = [("", stage) for stage in reversed(stages)]
    while pending:
        prefix, stage = pending.pop()
        if id(stage) in seen:
            raise ValueError(
                "Each stage instance must belong to exactly one tree position"
            )
        seen.add(id(stage))
        path = prefix + stage.name
        paths[path] = stage
        if isinstance(stage, SequenceStages):
            _validate_stage_names(stage.stages)
            pending.extend((f"{path}/", child) for child in reversed(stage.stages))
    return paths


def cache_enabled(policy: bool | Sequence[str], path: str) -> bool:
    if isinstance(policy, bool):
        return policy
    return any(
        path == selected or path.startswith(selected + "/") for selected in policy
    )


def _validate_policy(policy, paths):
    if isinstance(policy, bool):
        return
    if isinstance(policy, str) or not isinstance(policy, (list, tuple)):
        raise TypeError("use_meta must be a bool or list of stage paths")
    unknown = [path for path in policy if path not in paths]
    if unknown:
        raise ValueError(f"Unknown use_meta stage paths: {unknown}")


def _merge_errors(*groups):
    result: ErrorsDict = {}
    for errors in groups:
        for key, error in errors.items():
            candidate = key
            suffix = 1
            while candidate in result and result[candidate] != error:
                suffix += 1
                candidate = f"{key}:{suffix}"
            result[candidate] = error
    return result


def _add_stage_error(errors, key, error: StageError, by_id, path):
    if error.item_id not in by_id:
        raise ValueError(f"Error references an unknown item: {error.item_id}")
    if error.stage:
        return _merge_errors(errors, {key: error})
    add_error(errors, by_id[error.item_id], path, error.message)
    return errors


def _normalize_errors(raw_errors, all_files, path) -> ErrorsDict:
    by_id = {item.item_id: item for item in all_files}
    errors: ErrorsDict = {}
    for key, error in raw_errors.items():
        if isinstance(error, StageError):
            errors = _add_stage_error(errors, key, error, by_id, path)
        else:
            matches = [item for item in all_files if item.path == key]
            if not matches:
                raise ValueError(f"Error references an unknown item: {key}")
            for item in matches:
                add_error(errors, item, path, str(error))
    return errors


def _restore_missing(all_files, source, path, errors):
    by_id = {item.item_id: item for item in all_files}
    for item in source or []:
        if item.item_id not in by_id:
            missing = deepcopy(item)
            all_files.append(missing)
            by_id[item.item_id] = missing
            add_error(errors, missing, path, "Stage returned no result for this item")
    if source is not None:
        expected = {item.item_id for item in source}
        if set(by_id) != expected:
            raise ValueError(f"Stage {path} changed item identities")
    return by_id


def _normalize_result(result, source, path) -> StageResult:
    all_files, filtered, raw_errors = result
    all_files = normalize_items(all_files, source)
    filtered = normalize_items(filtered, all_files)
    declared = {item.item_id for item in all_files}
    if any(item.item_id not in declared for item in filtered):
        raise ValueError(f"Stage {path} passed an item absent from all_files")
    missing_errors: ErrorsDict = {}
    by_id = _restore_missing(all_files, source, path, missing_errors)
    errors = _merge_errors(
        _normalize_errors(raw_errors, all_files, path), missing_errors
    )
    return all_files, [by_id[item.item_id] for item in filtered], errors


def _sequence(node, incoming, path, results, stdout):
    accumulated = {item.item_id: deepcopy(item) for item in incoming or []}
    current = incoming
    errors: ErrorsDict = {}
    for child in node.stages:
        result = _execute(child, current, f"{path}/{child.name}", results, stdout)
        all_files, current, child_errors = result
        for item in all_files:
            accumulated[item.item_id] = deepcopy(item)
        errors = _merge_errors(errors, child_errors)
    passed = [accumulated[item.item_id] for item in current or []]
    return list(accumulated.values()), passed, errors


def _branch_results(original, branches):
    return [
        BranchResult(
            name,
            items[original.item_id],
            original.item_id in passed,
            {
                key: error
                for key, error in branch_errors.items()
                if error.item_id == original.item_id
            },
        )
        for name, items, passed, branch_errors in branches
    ]


def _merge_item(node, original, branches, path, errors):
    branch_results = _branch_results(original, branches)
    merged = deepcopy(original)
    try:
        merged.meta = merge_branch_metadata(original.meta, branch_results)
        passed = bool(node.pass_condition([branch.passed for branch in branch_results]))
        if passed:
            output = node.output_path_selector(branch_results)
            if output is None:
                raise ValueError("Output path selector returned no path")
            merged.path = type(original.path)(output)
        return merged, passed
    except Exception as exc:
        add_error(errors, merged, path, str(exc))
        return merged, False


def _parallel(node, incoming, path, results, stdout):
    if incoming is None:
        raise ValueError("ParallelStages requires an explicit input selection")
    branches = []
    errors: ErrorsDict = {}
    for child in node.stages:
        child_path = f"{path}/{child.name}"
        result = _execute(child, incoming, child_path, results, stdout)
        all_files, passed, child_errors = result
        branches.append(
            (
                child_path,
                {item.item_id: item for item in all_files},
                {item.item_id for item in passed},
                child_errors,
            )
        )
        errors = _merge_errors(errors, child_errors)
    all_files, passed_files = [], []
    for original in incoming:
        merged, passed = _merge_item(node, original, branches, path, errors)
        all_files.append(merged)
        if passed:
            passed_files.append(merged)
    return all_files, passed_files, errors


def _execute(stage, incoming, path, results, stdout):
    stdout(f"Do {path} stage")
    start = time.monotonic()
    transition_errors: ErrorsDict = {}
    if incoming is not None:
        working = deepcopy(incoming)
        transitioned = stage.transition(working, list(working), {})
        transitioned_all, incoming, transition_errors = _normalize_result(
            transitioned, incoming, path
        )
    else:
        transitioned_all = None
    if isinstance(stage, ParallelStages):
        result = _parallel(stage, incoming, path, results, stdout)
    elif isinstance(stage, SequenceStages):
        result = _sequence(stage, incoming, path, results, stdout)
    else:
        result = _normalize_result(stage(deepcopy(incoming)), incoming, path)
    all_files, filtered, errors = result
    errors = _merge_errors(transition_errors, errors)
    if transitioned_all is not None:
        updated = {item.item_id: item for item in all_files}
        all_files = [updated.get(item.item_id, item) for item in transitioned_all]
    result = all_files, filtered, errors
    results[path] = result
    stdout(f"{path} stage duration: {time.monotonic() - start}s")
    for callback in stage.callbacks:
        callback(results, path)
    return result


def _configure_cache(paths, use_meta):
    if use_meta is not None:
        _validate_policy(use_meta, paths)
    policies = {}
    for path, stage in paths.items():
        policy = use_meta
        config = getattr(stage, "config", None)
        if policy is None and config is not None:
            policy = config.processing.use_meta
            _validate_policy(policy, paths)
        policies[path] = cache_enabled(policy, path) if policy is not None else None
    previous = {path: stage._use_meta for path, stage in paths.items()}
    for path, stage in paths.items():
        stage._use_meta = policies[path]
    return previous


def run_stages(
    stages: Sequence[Stage],
    callbacks: Sequence[Callback] | None = None,
    stdout: Callable[[Any], Any] = _stdout,
    filtered_files: FilesWithMeta | None = None,
    use_meta: bool | Sequence[str] | None = None,
) -> PipesResult:
    """Execute named nodes, recording leaves and composites by full stage path.

    ``transition`` belongs to the incoming edge. ``use_meta`` selects complete
    subtrees; ``[]`` recalculates everything and ``['cad']`` enables all of cad.
    Leaf callbacks run even when a leaf restores cached metadata.
    """
    paths = _stage_paths(stages)
    previous = _configure_cache(paths, use_meta)
    results: PipesResult = {}
    try:
        current = (
            normalize_items(filtered_files) if filtered_files is not None else None
        )
        for stage in stages:
            _, current, _ = _execute(stage, current, stage.name, results, stdout)
        for callback in callbacks or []:
            callback(results, None)
    finally:
        for path, stage in paths.items():
            stage._use_meta = previous[path]
    return results
