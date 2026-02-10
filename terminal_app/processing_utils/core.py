import multiprocessing as mp
import queue
import time
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

from tqdm import tqdm

from terminal_app.utils import (
    annotations_to_path_list,
    kill_all_output,
    list_cuda_devices,
)


def _stdout(x):
    return


def run_stages(
    stages: dict[
        str,
        Callable[
            [
                list[tuple[Path, dict[str, Any]]] | None,
                list[tuple[Path, dict[str, Any]]] | None,
                dict[Path, str],
            ],
            tuple[
                list[tuple[Path, dict[str, Any]]],
                list[tuple[Path, dict[str, Any]]],
                dict[Path, str],
            ],
        ],
    ],
    transitions: (
        dict[
            str,
            Callable[
                [
                    list[tuple[Path, dict[str, Any]]],
                    list[tuple[Path, dict[str, Any]]],
                    dict[Path, str],
                ],
                tuple[
                    list[tuple[Path, dict[str, Any]]],
                    list[tuple[Path, dict[str, Any]]],
                    dict[Path, str],
                ],
            ],
        ]
        | None
    ) = None,
    callbacks: (
        dict[
            str,
            Callable[
                [
                    dict[
                        str,
                        tuple[
                            list[tuple[Path, dict[str, Any]]],
                            list[tuple[Path, dict[str, Any]]],
                            dict[Path, str],
                        ],
                    ]
                ],
                Any,
            ],
        ]
        | None
    ) = None,
    stdout: Callable[[Any], Any] = _stdout,
):

    all_files: list[tuple[Path, dict[str, Any]]] | None = None
    filtered_files: list[tuple[Path, dict[str, Any]]] | None = None
    errors: dict[Path, str] = {}
    stages_result: dict[
        str,
        tuple[
            list[tuple[Path, dict[str, Any]]],
            list[tuple[Path, dict[str, Any]]],
            dict[Path, str],
        ],
    ] = {}

    for stage_name, stage in stages.items():

        stdout(stage_name)
        start = time.time()
        stages_result[stage_name] = stage(all_files, filtered_files, errors)
        end = time.time()
        stdout(f"{stage_name} duration: {end-start}s")

        if transitions and transitions.get(stage_name):
            all_files, filtered_files, errors = transitions[stage_name](
                *stages_result[stage_name]
            )

    stdout("Do callbacks")
    if callbacks:
        for cb_name, cb_fn in callbacks.items():
            stdout(cb_name)
            start = time.time()
            cb_fn(stages_result)
            end = time.time()
            stdout(f"{cb_name} duration: {end-start}s")


def worker(
    task_queue: mp.Queue,
    result_queue: mp.Queue,
    worker_id: int,
    logging: bool,
    safety: bool,
    filter_one: Callable[
        [str, dict[str, Any], str], tuple[Path | str, dict[str, Any], str | None, bool]
    ],
    error_stdout: Callable[[Any], Any],
    task_timeout: int = 300,
    process_timeout: int = 120,
):
    if not logging:
        kill_all_output()

    fork_ctx = None

    while True:
        task = None
        try:
            task = task_queue.get(timeout=task_timeout)

            if safety:
                if fork_ctx is None:
                    fork_ctx = mp.get_context("fork")

                result_q = fork_ctx.Queue()

                def worker_function(queue: mp.Queue, *args):
                    result = filter_one(*args)
                    queue.put(result)

                p = fork_ctx.Process(target=worker_function, args=(result_q,) + task)
                result = None
                failed_reason = ""
                try:
                    p.start()
                    p.join(timeout=process_timeout)

                    try:
                        result = result_q.get(timeout=1)
                    except queue.Empty:
                        failed_reason = "Can't get result from queue"

                    if p.is_alive():
                        p.terminate()
                        p.join(timeout=process_timeout)

                        if p.is_alive():
                            p.kill()
                            p.join()
                            message = "Process was forcibly killed after timeout"
                            failed_reason += " | " + message
                            error_stdout(message)
                except Exception as e:
                    message = f"Error handling process: {e}"
                    error_stdout(message)
                    failed_reason += " | " + message
                    if p.is_alive():
                        p.kill()
                        p.join()

                if result is None:
                    result = (Path(task[0]), task[1], failed_reason, False)

                result_queue.put(result)
            else:

                result_queue.put(
                    filter_one(
                        *task,
                    )
                )
        except queue.Empty:
            break
        except Exception as e:
            task_file = task[0] if task else None
            error_stdout(f"Worker {worker_id} failed: {str(e)}, {task_file}")


def process_files(
    all_files: list[tuple[Path, dict[str, Any]]] | None,
    filtered_files: list[tuple[Path, dict[str, Any]]] | None,
    errors: dict[Path, str],
    filter_one: Callable[
        [str, dict[str, Any], str], tuple[Path | str, dict[str, Any], str | None, bool]
    ],
    desc: str,
    max_workers: int | None = None,
    annotations: Path | str | Sequence[Path | str] | None = None,
    override_files: list[tuple[Path, dict[str, Any]]] | None = None,
    safety: bool = False,
    logging: bool = True,
    start_method: Literal["fork", "spawn"] | None = None,
    device: Literal["cuda", "cpu"] = "cpu",
    error_stdout: Callable[[Any], Any] = _stdout,
    info_stdout: Callable[[Any], Any] = _stdout,
    postprocessing_func: (
        Callable[
            [
                list[tuple[Path, dict[str, Any]]],
                list[tuple[Path, dict[str, Any]]],
                dict[Path, str],
            ],
            tuple[
                list[tuple[Path, dict[str, Any]]],
                list[tuple[Path, dict[str, Any]]],
                dict[Path, str],
            ],
        ]
        | None
    ) = None,
):

    assert not (safety and device == "cuda"), "Safety mode work only on cpu"
    ctx = mp.get_context(start_method) if start_method else mp.get_context()
    if max_workers is None:
        max_workers = mp.cpu_count()

    info_stdout(f"Starting processing with {max_workers} workers")

    if override_files:
        filtered_files = override_files

    if all_files is None and filtered_files is None and annotations is not None:
        filtered_files = [(p, {}) for p in annotations_to_path_list(annotations)]
    elif filtered_files is None:
        raise Exception("There are no matching files")

    q = ctx.Queue()
    progress_q = ctx.Queue()
    total = len(filtered_files)

    if device == "cpu":
        for file, meta in filtered_files:
            q.put((str(file), meta, "cpu"))
    else:
        # lazy import
        cuda_devices = list_cuda_devices()
        if not cuda_devices:
            raise RuntimeError("No CUDA devices found or visible")
        for ind, (file, meta) in enumerate(filtered_files):
            q.put((str(file), meta, cuda_devices[ind % len(cuda_devices)]))
    processes: list[mp.Process] = []

    if device == "cuda":
        try:
            n_devices = len(list_cuda_devices())
            max_workers = min(max_workers, max(1, n_devices))
        except Exception:
            pass
    else:
        max_workers = min(max_workers, mp.cpu_count())

    max_workers = min(max_workers, total)
    for i in range(max_workers):
        p = ctx.Process(  # type: ignore
            target=worker,
            args=(q, progress_q, i, logging, safety, filter_one, error_stdout),
        )
        p.start()
        processes.append(p)
    all_files_with_meta: list[tuple[Path, dict[str, Any]]] = []
    filtered_files_with_meta: list[tuple[Path, dict[str, Any]]] = []
    with tqdm(total=total, desc=desc) as pbar:
        completed = 0
        while completed < total:
            try:
                file, meta, error, passed = progress_q.get(timeout=15)
                all_files_with_meta.append((file, meta))
                if error:
                    errors[file] = error
                if passed:
                    filtered_files_with_meta.append((file, meta))
                completed += 1
                pbar.update(1)
            except queue.Empty:
                if all(not p.is_alive() for p in processes):
                    break

    for p in processes:
        if p.is_alive():
            p.terminate()
        p.join(timeout=5)
        if p.is_alive():
            p.kill()
    if postprocessing_func:
        all_files_with_meta, filtered_files_with_meta, errors = postprocessing_func(
            all_files_with_meta, filtered_files_with_meta, errors
        )

    return all_files_with_meta, filtered_files_with_meta, errors
