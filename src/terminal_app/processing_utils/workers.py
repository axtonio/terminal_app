import multiprocessing as mp
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from terminal_app.utils.utils import annotations_to_path_list, list_cuda_devices

from .types import (
    ErrorsDict,
    FilesWithMeta,
    StageItem,
    StageResult,
    add_error,
    normalize_items,
)
from .worker_runtime import WorkerFunction, WorkerReplies
from .worker_runtime import _worker as _worker
from .worker_supervision import run_workers


def _stdout(value):
    return None


def _validate_options(
    safety: bool,
    device: str,
    max_workers: int | None,
    process_timeout: float,
    task_timeout: float,
) -> None:
    if safety and device == "cuda":
        raise ValueError("Safety mode works only on CPU")
    if process_timeout <= 0 or task_timeout <= 0:
        raise ValueError("Worker timeouts must be positive")
    if max_workers is not None and max_workers < 1:
        raise ValueError("max_workers must be positive")


def _select_inputs(filtered_files, override_files, annotations, read_json):
    if override_files is not None:
        filtered_files = (
            override_files() if callable(override_files) else override_files
        )
    if filtered_files is not None:
        return normalize_items(filtered_files)
    if annotations is None:
        raise ValueError("There are no matching files")
    return normalize_items(
        [
            (path, {})
            for path in annotations_to_path_list(annotations, read_json=read_json)
        ]
    )


def _prepare_inputs(inputs: FilesWithMeta, prepare_item) -> FilesWithMeta:
    if prepare_item is None:
        return inputs
    prepared = []
    for item in inputs:
        changed = prepare_item(deepcopy(item))
        if not isinstance(changed, StageItem) or changed.item_id != item.item_id:
            raise ValueError("prepare_item must preserve its StageItem.item_id")
        prepared.append(changed)
    return prepared


def _collect_results(inputs: FilesWithMeta, replies: WorkerReplies) -> StageResult:
    all_files: FilesWithMeta = []
    passed_files: FilesWithMeta = []
    errors: ErrorsDict = {}
    for source in inputs:
        error: str | None
        payload = replies.get(source.item_id)
        if payload is None:
            item = deepcopy(source)
            error, passed = (
                "Worker exited or timed out without returning this item",
                False,
            )
        else:
            output, meta, error, passed = payload
            item = StageItem(source.item_id, Path(output), meta)
        all_files.append(item)
        if error:
            add_error(errors, item, "", str(error))
        if passed:
            passed_files.append(item)
    return all_files, passed_files, errors


def process_files(
    filtered_files,
    filter_one: WorkerFunction,
    desc: str,
    max_workers: int | None = None,
    annotations=None,
    override_files=None,
    safety: bool = False,
    logging: bool = True,
    start_method=None,
    device: str = "cpu",
    read_json: bool = False,
    error_stdout: Callable[[str], Any] = _stdout,
    info_stdout: Callable[[str], Any] = _stdout,
    postprocessing_func=None,
    task_timeout: int = 300,
    process_timeout: int = 120,
    prepare_item=None,
):
    """Process every input with a result or an item error.

    Timeouts stop the direct worker or isolated task process. Subprocesses
    launched by the supplied function remain that function's responsibility.
    """
    _validate_options(safety, device, max_workers, process_timeout, task_timeout)
    inputs = _prepare_inputs(
        _select_inputs(filtered_files, override_files, annotations, read_json),
        prepare_item,
    )
    if not inputs:
        result: StageResult = [], [], {}
        return postprocessing_func(*result) if postprocessing_func else result
    devices = ["cpu"] if device == "cpu" else list_cuda_devices()
    if not devices:
        raise RuntimeError("No CUDA devices found or visible")
    limit = mp.cpu_count() if device == "cpu" else len(devices)
    worker_count = min(max_workers or mp.cpu_count(), limit, len(inputs))
    info_stdout(f"Starting processing with {worker_count} workers")
    context = mp.get_context(start_method) if start_method else mp.get_context()
    replies = run_workers(
        context,
        inputs,
        devices,
        worker_count,
        filter_one,
        desc,
        logging,
        safety,
        error_stdout,
        task_timeout,
        process_timeout,
    )
    result = _collect_results(inputs, replies)
    return postprocessing_func(*result) if postprocessing_func else result
