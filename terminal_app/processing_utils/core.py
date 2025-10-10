import multiprocessing as mp
import os
import queue
import time
from pathlib import Path
from typing import Any, Callable, Literal

from tqdm import tqdm

from terminal_app.utils import kill_all_output


def _list_cuda_devices():
    vis = os.environ.get("CUDA_VISIBLE_DEVICES")
    if vis is not None:
        ids = [x for x in vis.split(",") if x.strip() != ""]
        if len(ids) > 0:
            return [f"cuda:{i}" for i in range(len(ids))]
    try:
        import torch  # type: ignore

        return [f"cuda:{i}" for i in range(torch.cuda.device_count())]
    except Exception:
        return []


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
    without_logging: bool,
    safety: bool,
    filter_one: Callable[
        [str, dict[str, Any], str], tuple[Path | str, dict[str, Any], str | None, bool]
    ],
    error_stdout: Callable[[Any], Any],
):
    if without_logging:
        kill_all_output()

    # Подготовим локальный контекст для дочерних подпроцессов ТОЛЬКО если запрошен 'fork'
    if safety:
        fork_ctx = mp.get_context("fork")

    while True:
        try:
            task = task_queue.get(timeout=300)

            if safety:
                # Локальный подпроцесс через fork — быстро и дёшево
                result_q = fork_ctx.Queue()

                def worker_function(queue: mp.Queue, *args):
                    result = filter_one(*args)
                    queue.put(result)

                p = fork_ctx.Process(target=worker_function, args=(result_q,) + task)
                result = None
                failed_reason = ""
                try:
                    p.start()
                    p.join(timeout=50)

                    try:
                        result = result_q.get(timeout=1)
                    except queue.Empty:
                        failed_reason = "Can't get result from queue"

                    if p.is_alive():
                        p.terminate()
                        p.join(timeout=50)

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
            error_stdout(f"Worker {worker_id} failed: {str(e)}, {task[0]}")


def process_files(
    all_files: list[tuple[Path, dict[str, Any]]] | None,
    filtered_files: list[tuple[Path, dict[str, Any]]] | None,
    errors: dict[Path, str],
    filter_one: Callable[
        [str, dict[str, Any], str], tuple[Path | str, dict[str, Any], str | None, bool]
    ],
    desc: str,
    max_workers: int | None = None,
    root_folder: Path | None = None,
    pattern: str | None = None,
    override_files: list[tuple[Path, dict[str, Any]]] | None = None,
    safety: bool = False,
    without_logging: bool = False,
    start_method: Literal["fork", "spawn"] | None = None,
    device: Literal["cuda", "cpu"] = "cpu",
    error_stdout: Callable[[Any], Any] = _stdout,
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

    if override_files:
        filtered_files = override_files

    if (
        all_files is None
        and filtered_files is None
        and pattern is not None
        and root_folder is not None
    ):
        filtered_files = [(p, {}) for p in root_folder.rglob(pattern)]
    elif filtered_files is None:
        raise Exception("There are no matching files")

    q = ctx.Queue()
    progress_q = ctx.Queue()
    total = len(filtered_files)

    if device == "cpu":
        for file, meta in filtered_files:
            q.put((str(file), meta, "cpu"))
    else:
        # НЕ импортируем torch в родителе без нужды
        cuda_devices = _list_cuda_devices()
        if not cuda_devices:
            raise RuntimeError("No CUDA devices found or visible")
        for ind, (file, meta) in enumerate(filtered_files):
            q.put((str(file), meta, cuda_devices[ind % len(cuda_devices)]))

    processes: list[mp.Process] = []

    # Если device='cuda', не создаём больше процессов, чем GPU (по желанию)
    if device == "cuda":
        try:
            n_devices = len(_list_cuda_devices())
            max_workers = min(max_workers, max(1, n_devices))
        except Exception:
            pass
    else:
        max_workers = min(max_workers, mp.cpu_count())

    max_workers = min(max_workers, total)

    for i in range(max_workers):
        p = ctx.Process(  # type: ignore
            target=worker,
            args=(q, progress_q, i, without_logging, safety, filter_one, error_stdout),
        )
        p.start()
        processes.append(p)

    all_files_with_meta: list[tuple[Path, dict[str, Any]]] = []
    filtered_files_with_meta: list[tuple[Path, dict[str, Any]]] = []

    with tqdm(total=total, desc=desc) as pbar:
        completed = 0
        while completed < total:
            try:
                file, meta, error, passed = progress_q.get(timeout=300)
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

    # Корректно завершаем процессы
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
