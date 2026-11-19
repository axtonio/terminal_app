import multiprocessing as mp
import queue
import time
from copy import deepcopy
from multiprocessing.process import BaseProcess
from multiprocessing.queues import Queue
from pathlib import Path
from typing import Any, Callable

from terminal_app.utils.stdout_utils import kill_all_output

WorkerResult = tuple[str | Path, dict[str, Any], str | None, bool]
WorkerFunction = Callable[[str, dict[str, Any], str], WorkerResult]
WorkerTask = tuple[str, str, dict[str, Any], str]
WorkerPayload = tuple[str, dict[str, Any], str | None, bool]
WorkerReplies = dict[str, WorkerPayload]


def stop_process(process: BaseProcess) -> None:
    if process.is_alive():
        process.terminate()
    process.join(timeout=1)
    if process.is_alive():
        process.kill()
        process.join()


def _call_isolated(result_queue: Queue, function: WorkerFunction, args) -> None:
    incoming_meta = deepcopy(args[1])
    try:
        result_queue.put(function(*args))
    except Exception as exc:
        result_queue.put(
            (Path(args[0]), incoming_meta, f"{type(exc).__name__}: {exc}", False)
        )


def _receive_isolated(
    results: Queue, process: BaseProcess, deadline: float
) -> WorkerResult:
    while time.monotonic() < deadline:
        try:
            return results.get(
                timeout=min(0.1, max(0.001, deadline - time.monotonic()))
            )
        except queue.Empty:
            if not process.is_alive():
                break
    raise TimeoutError("Worker process exited or timed out without a result")


def _isolated(function: WorkerFunction, args, timeout: float) -> WorkerResult:
    context = mp.get_context("fork")
    results = context.Queue()
    process = context.Process(target=_call_isolated, args=(results, function, args))
    process.start()
    try:
        return _receive_isolated(results, process, time.monotonic() + timeout)
    except TimeoutError as exc:
        return Path(args[0]), args[1], str(exc), False
    finally:
        stop_process(process)
        results.close()


def _run_task(
    task: WorkerTask,
    worker_id: int,
    safety: bool,
    filter_one: WorkerFunction,
    error_stdout: Callable[[str], Any],
    process_timeout: float,
):
    item_id, file, meta, device = task
    args = file, meta, device
    incoming_meta = deepcopy(meta)
    try:
        result = (
            _isolated(filter_one, args, process_timeout)
            if safety
            else filter_one(*args)
        )
        output, output_meta, error, passed = result
        return "result", worker_id, item_id, str(output), output_meta, error, passed
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        error_stdout(f"Worker {worker_id} failed: {message}, {file}")
        return "result", worker_id, item_id, file, incoming_meta, message, False


def _worker(
    task_queue: Queue,
    result_queue: Queue,
    worker_id: int,
    logging: bool,
    safety: bool,
    filter_one: WorkerFunction,
    error_stdout: Callable[[str], Any],
    task_timeout: float,
    process_timeout: float,
) -> None:
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
        result_queue.put(("started", worker_id, task[0]))
        result_queue.put(
            _run_task(
                task, worker_id, safety, filter_one, error_stdout, process_timeout
            )
        )
