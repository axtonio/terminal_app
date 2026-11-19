import queue
import time
from copy import deepcopy
from dataclasses import dataclass, field
from multiprocessing.context import BaseContext
from multiprocessing.process import BaseProcess
from multiprocessing.queues import Queue
from typing import Any, Callable

from tqdm import tqdm

from .types import FilesWithMeta
from .worker_runtime import WorkerFunction, WorkerReplies, _worker, stop_process


@dataclass
class WorkerMonitor:
    replies: WorkerReplies = field(default_factory=dict)
    active: dict[int, tuple[str, float]] = field(default_factory=dict)
    idle_since: float = field(default_factory=time.monotonic)

    def record(self, event, progress) -> None:
        self.idle_since = time.monotonic()
        kind, worker_id, item_id, *payload = event
        if kind == "started":
            self.active[worker_id] = item_id, time.monotonic()
        elif item_id not in self.replies:
            output, meta, error, passed = payload
            self.replies[item_id] = output, meta, error, passed
            self.active.pop(worker_id, None)
            progress.update(1)

    def expire(self, processes: list[BaseProcess], allowance: float) -> None:
        now = time.monotonic()
        for worker_id, (_, started) in list(self.active.items()):
            process = processes[worker_id]
            if now - started > allowance and process.is_alive():
                process.kill()
                process.join()
                self.active.pop(worker_id, None)

    def is_idle(self, timeout: float) -> bool:
        return not self.active and time.monotonic() - self.idle_since > timeout


def _read_event(
    messages: Queue, monitor: WorkerMonitor, progress, processes: list[BaseProcess]
) -> bool:
    try:
        monitor.record(messages.get(timeout=0.1), progress)
        return True
    except queue.Empty:
        return any(process.is_alive() for process in processes)


def _collect_replies(
    messages: Queue,
    processes: list[BaseProcess],
    total: int,
    desc: str,
    safety: bool,
    task_timeout: float,
    process_timeout: float,
) -> WorkerReplies:
    monitor = WorkerMonitor()
    # Isolated workers enforce their own timeout first. The parent watchdog
    # also covers a dead or hung outer worker in either safety mode.
    allowance = process_timeout + (2 if safety else 0)
    with tqdm(total=total, desc=desc) as progress:
        while len(monitor.replies) < total:
            if not _read_event(messages, monitor, progress, processes):
                break
            monitor.expire(processes, allowance)
            if monitor.is_idle(process_timeout + task_timeout):
                break
    return monitor.replies


def _enqueue_tasks(
    tasks: Queue, inputs: FilesWithMeta, devices: list[str], worker_count: int
) -> None:
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


def _start_workers(
    context,
    processes: list[BaseProcess],
    tasks: Queue,
    messages: Queue,
    worker_count: int,
    logging: bool,
    safety: bool,
    filter_one: WorkerFunction,
    error_stdout: Callable[[str], Any],
    task_timeout: float,
    process_timeout: float,
) -> None:
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


def run_workers(
    context: BaseContext,
    inputs: FilesWithMeta,
    devices: list[str],
    worker_count: int,
    filter_one: WorkerFunction,
    desc: str,
    logging: bool,
    safety: bool,
    error_stdout: Callable[[str], Any],
    task_timeout: float,
    process_timeout: float,
) -> WorkerReplies:
    tasks, messages = context.Queue(), context.Queue()
    processes: list[BaseProcess] = []
    try:
        _enqueue_tasks(tasks, inputs, devices, worker_count)
        _start_workers(
            context,
            processes,
            tasks,
            messages,
            worker_count,
            logging,
            safety,
            filter_one,
            error_stdout,
            task_timeout,
            process_timeout,
        )
        return _collect_replies(
            messages,
            processes,
            len(inputs),
            desc,
            safety,
            task_timeout,
            process_timeout,
        )
    finally:
        for process in processes:
            stop_process(process)
        tasks.cancel_join_thread()
        tasks.close()
        messages.close()
