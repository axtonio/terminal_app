import multiprocessing as mp
import queue
import time
from copy import deepcopy
from pathlib import Path

from tqdm import tqdm

from terminal_app.utils import (
    annotations_to_path_list,
    kill_all_output,
    list_cuda_devices,
)

from .types import StageItem, add_error, normalize_items


def _stdout(value):
    return None


def _call_isolated(result_queue, function, args):
    incoming_meta = deepcopy(args[1])
    try:
        result_queue.put(function(*args))
    except Exception as exc:
        result_queue.put(
            (Path(args[0]), incoming_meta, f"{type(exc).__name__}: {exc}", False)
        )


def _isolated(function, args, timeout):
    context = mp.get_context("fork")
    results = context.Queue()
    process = context.Process(target=_call_isolated, args=(results, function, args))
    process.start()
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                return results.get(
                    timeout=min(0.1, max(0.001, deadline - time.monotonic()))
                )
            except queue.Empty:
                if not process.is_alive():
                    break
        return (
            Path(args[0]),
            args[1],
            "Worker process exited or timed out without a result",
            False,
        )
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join()
        results.close()


def _worker(
    task_queue,
    result_queue,
    worker_id,
    logging,
    safety,
    filter_one,
    error_stdout,
    task_timeout,
    process_timeout,
):
    if not logging:
        kill_all_output()
    while True:
        # An Empty raised by a task is a task failure, not the end of this queue.
        try:
            task = task_queue.get(timeout=task_timeout)
        except queue.Empty:
            return
        if task is None:
            return
        item_id, file, meta, device = task
        args = file, meta, device
        incoming_meta = deepcopy(meta)
        result_queue.put(("started", worker_id, item_id))
        try:
            result = (
                _isolated(filter_one, args, process_timeout)
                if safety
                else filter_one(*args)
            )
            output, output_meta, error, passed = result
            result_queue.put(
                ("result", worker_id, item_id, str(output), output_meta, error, passed)
            )
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            error_stdout(f"Worker {worker_id} failed: {message}, {file}")
            result_queue.put(
                ("result", worker_id, item_id, file, incoming_meta, message, False)
            )


def process_files(
    filtered_files,
    filter_one,
    desc: str,
    max_workers: int | None = None,
    annotations=None,
    override_files=None,
    safety: bool = False,
    logging: bool = True,
    start_method=None,
    device: str = "cpu",
    read_json: bool = False,
    error_stdout=_stdout,
    info_stdout=_stdout,
    postprocessing_func=None,
    task_timeout: int = 300,
    process_timeout: int = 120,
):
    if safety and device == "cuda":
        raise ValueError("Safety mode works only on CPU")
    if process_timeout <= 0 or task_timeout <= 0:
        raise ValueError("Worker timeouts must be positive")
    if max_workers is not None and max_workers < 1:
        raise ValueError("max_workers must be positive")
    if override_files is not None:
        filtered_files = (
            override_files() if callable(override_files) else override_files
        )
    if filtered_files is None:
        if annotations is None:
            raise ValueError("There are no matching files")
        filtered_files = [
            (path, {})
            for path in annotations_to_path_list(annotations, read_json=read_json)
        ]
    inputs = normalize_items(filtered_files)
    if not inputs:
        result = [], [], {}
        return postprocessing_func(*result) if postprocessing_func else result
    devices = ["cpu"] if device == "cpu" else list_cuda_devices()
    if not devices:
        raise RuntimeError("No CUDA devices found or visible")
    limit = mp.cpu_count() if device == "cpu" else len(devices)
    worker_count = min(max_workers or mp.cpu_count(), limit, len(inputs))
    info_stdout(f"Starting processing with {worker_count} workers")
    context = mp.get_context(start_method) if start_method else mp.get_context()
    tasks, messages = context.Queue(), context.Queue()
    for index, item in enumerate(inputs):
        tasks.put(
            (
                item.item_id,
                str(item.path),
                deepcopy(item.meta),
                devices[index % len(devices)],
            )
        )
    for _ in range(worker_count):
        tasks.put(None)
    processes = []
    replies, active = {}, {}
    try:
        for worker_id in range(worker_count):
            process = context.Process(
                target=_worker,
                args=(
                    tasks,
                    messages,
                    worker_id,
                    logging,
                    safety,
                    filter_one,
                    error_stdout,
                    task_timeout,
                    process_timeout,
                ),
            )
            process.start()
            processes.append(process)
        with tqdm(total=len(inputs), desc=desc) as progress:
            idle_since = time.monotonic()
            while len(replies) < len(inputs):
                try:
                    event = messages.get(timeout=0.1)
                    idle_since = time.monotonic()
                    kind, worker_id, item_id, *payload = event
                    if kind == "started":
                        active[worker_id] = item_id, time.monotonic()
                    elif item_id not in replies:
                        replies[item_id] = payload
                        active.pop(worker_id, None)
                        progress.update(1)
                except queue.Empty:
                    if all(not process.is_alive() for process in processes):
                        break
                now = time.monotonic()
                for worker_id, (_, started) in list(active.items()):
                    # Isolated workers enforce their own timeout first; parent
                    # watchdog also covers a dead/hung outer worker in either mode.
                    allowance = process_timeout + (2 if safety else 0)
                    if now - started > allowance and processes[worker_id].is_alive():
                        processes[worker_id].kill()
                        processes[worker_id].join()
                        active.pop(worker_id, None)
                if not active and now - idle_since > process_timeout + task_timeout:
                    break
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join()
        tasks.cancel_join_thread()
        tasks.close()
        messages.close()
    all_files, passed_files, errors = [], [], {}
    for source in inputs:
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
    result = all_files, passed_files, errors
    return postprocessing_func(*result) if postprocessing_func else result
