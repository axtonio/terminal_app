import time
from copy import deepcopy
from typing import Any, Callable, Sequence

from .base import Callback, Stage
from .composites import ParallelStages, SequenceStages, merge_branch_metadata
from .types import (
    BranchResult,
    FilesWithMeta,
    PipesResult,
    StageError,
    StageResult,
    add_error,
    normalize_items,
)


def _stdout(value):
    return None


def _stage_paths(stages: Sequence[Stage], prefix: str = "") -> dict[str, Stage]:
    paths = {}
    names = set()
    for stage in stages:
        if not stage.name or "/" in stage.name or stage.name in names:
            raise ValueError(f"Invalid or duplicate stage name: {stage.name!r}")
        names.add(stage.name)
        path = f"{prefix}/{stage.name}" if prefix else stage.name
        paths[path] = stage
        if isinstance(stage, SequenceStages):
            paths.update(_stage_paths(stage.stages, path))
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
    result = {}
    for errors in groups:
        for key, error in errors.items():
            candidate = key
            suffix = 1
            while candidate in result and result[candidate] != error:
                suffix += 1
                candidate = f"{key}:{suffix}"
            result[candidate] = error
    return result


def _normalize_result(result, source, path):
    all_files, filtered, raw_errors = result
    all_files = normalize_items(all_files, source)
    by_id = {item.item_id: item for item in all_files}
    filtered = normalize_items(filtered, all_files)
    errors = {}
    for key, error in raw_errors.items():
        if isinstance(error, StageError):
            if error.stage:
                errors[key] = error
            else:
                add_error(errors, by_id[error.item_id], path, error.message)
        else:
            matches = [item for item in all_files if item.path == key]
            if not matches:
                raise ValueError(f"Error references an unknown item: {key}")
            for item in matches:
                add_error(errors, item, path, str(error))
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
    if any(item.item_id not in by_id for item in filtered):
        raise ValueError(f"Stage {path} passed an item absent from all_files")
    return all_files, [by_id[item.item_id] for item in filtered], errors


def _sequence(node, incoming, path, results, stdout):
    accumulated = {item.item_id: deepcopy(item) for item in incoming or []}
    current = incoming
    errors = {}
    for child in node.stages:
        result = _execute(child, current, f"{path}/{child.name}", results, stdout)
        all_files, current, child_errors = result
        for item in all_files:
            accumulated[item.item_id] = deepcopy(item)
        errors.update(child_errors)
    return list(accumulated.values()), current or [], errors


def _parallel(node, incoming, path, results, stdout):
    if incoming is None:
        raise ValueError("ParallelStages requires an explicit input selection")
    branches = []
    errors = {}
    for child in node.stages:
        child_path = f"{path}/{child.name}"
        result = _execute(child, deepcopy(incoming), child_path, results, stdout)
        all_files, passed, child_errors = result
        branches.append(
            (
                child_path,
                {item.item_id: item for item in all_files},
                {item.item_id for item in passed},
                child_errors,
            )
        )
        errors.update(child_errors)
    all_files, passed_files = [], []
    for original in incoming:
        branch_results = [
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
        merged = deepcopy(original)
        try:
            merged.meta = merge_branch_metadata(original.meta, branch_results)
            passed = bool(
                node.pass_condition([branch.passed for branch in branch_results])
            )
            if passed:
                output = node.output_path_selector(branch_results)
                if output is None:
                    raise ValueError("Output path selector returned no path")
                merged.path = type(original.path)(output)
                passed_files.append(merged)
        except Exception as exc:
            add_error(errors, merged, path, str(exc))
        all_files.append(merged)
    return all_files, passed_files, errors


def _execute(stage, incoming, path, results, stdout):
    stdout(f"Do {path} stage")
    start = time.monotonic()
    transition_errors = {}
    if incoming is not None:
        transitioned = stage.transition(deepcopy(incoming), deepcopy(incoming), {})
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
    if len({id(stage) for stage in paths.values()}) != len(paths):
        raise ValueError("Each stage instance must belong to exactly one tree position")
    if use_meta is not None:
        _validate_policy(use_meta, paths)
    previous = {}
    for path, stage in paths.items():
        policy = use_meta
        config = getattr(stage, "config", None)
        if policy is None and config is not None:
            policy = config.processing.use_meta
            _validate_policy(policy, paths)
        previous[path] = stage._use_meta
        stage._use_meta = cache_enabled(policy, path) if policy is not None else None
    results = {}
    current = normalize_items(filtered_files) if filtered_files is not None else None
    try:
        for stage in stages:
            _, current, _ = _execute(stage, current, stage.name, results, stdout)
        for callback in callbacks or []:
            callback(results, None)
    finally:
        for path, stage in paths.items():
            stage._use_meta = previous[path]
    return results
