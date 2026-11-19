import inspect
import logging
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Callable, Literal

from terminal_app.utils.utils import link_file

from .base import Stage
from .stage_utils import (
    CallbackConfig,
    DatasetStatsCallbackConfig,
    ProcessingConfig,
    SaveMetaCallbackConfig,
    SavePickleCallbackConfig,
    get_default_callbacks,
    process_failed_filter,
    process_meta_file,
)
from .types import FilesWithMeta, StageItem
from .workers import process_files

logger = logging.getLogger(__name__)

_StartMethod = Literal["fork", "spawn"]


def _call_worker_function(
    function: (
        Callable[[Path], tuple[dict[str, Any], str | None, bool]]
        | Callable[[Path, str], tuple[dict[str, Any], str | None, bool]]
    ),
    file: Path,
    device: str,
) -> tuple[dict[str, Any], str | None, bool]:
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        signature = None

    callable_function: Any = function
    if signature is not None and "device" in signature.parameters:
        return callable_function(file, device)
    return callable_function(file)


Result = tuple[dict[str, Any], str | None, bool]
WorkerFn = Callable[[Path], Result] | Callable[[Path, str], Result]


def _link_cached_meta(file: Path, meta_path: Path, meta_suffix: str) -> None:
    if not file.is_symlink():
        return
    source = file.readlink()
    meta_name = source.stem + meta_suffix
    source_meta_path = (file.parent / source).with_name(meta_name)
    if source_meta_path.exists() and (not meta_path.exists() or meta_path.is_symlink()):
        link_file(source.with_name(meta_name), meta_path)


def _cached_result(meta_path: Path, meta: dict, stats_key: str):
    if not meta_path.exists():
        return None
    result = process_meta_file(meta_path, meta, stats_key)
    if result is None:
        return None
    loaded, _, passed = result
    return None if not loaded.get(stats_key) and passed else result


def _evaluate_file(file, meta, device, function, stats_key):
    try:
        meta[stats_key], failed_filter, passed = _call_worker_function(
            function, file, device
        )
    except Exception as ex:
        logger.error(str(ex))
        logger.error(f"File: {file}")
        passed, failed_filter = False, str(ex)
    return meta, failed_filter, passed


def _process_file_worker_wrapper(
    file_str: str,
    meta: dict[str, Any],
    device: str,
    use_meta: bool,
    function: WorkerFn,
    file_key: str,
    stats_key: str,
    meta_suffix: str,
):
    file = Path(file_str)
    meta[file_key] = file_str
    meta[stats_key] = {}
    if not file.exists():
        meta[stats_key]["error"] = "file_not_exist"
        return (file, meta, "file_not_exist", False)

    meta_path = file.with_name(file.stem + meta_suffix)

    cached = None
    if use_meta:
        _link_cached_meta(file, meta_path, meta_suffix)
        cached = _cached_result(meta_path, meta, stats_key)
    meta, failed_filter, passed = (
        cached
        if cached is not None
        else _evaluate_file(file, meta, device, function, stats_key)
    )

    process_failed_filter(failed_filter, passed, meta, stats_key)

    return (file, meta, failed_filter, passed)


def _prepare_item(item: StageItem, statistics_key: str, file_key: str) -> StageItem:
    # Clear owned cached data in the parent as well: a killed worker cannot
    # return its cleanup, and fallback must never mistake yesterday's score
    # for the current attempt's result. Sibling metadata remains untouched.
    item.meta[statistics_key] = {}
    item.meta[file_key] = str(item.path)
    return item


@dataclass(slots=True)
class StageConfig:
    name: str
    file_key: str
    statistics_key: str
    processing: ProcessingConfig
    dataset_stats_callback: DatasetStatsCallbackConfig | None
    save_meta_callback: SaveMetaCallbackConfig | None
    save_pickle_callback: SavePickleCallbackConfig | None
    worker_wrapper: WorkerFn
    start_method: _StartMethod = "fork"
    task_timeout: int = 300
    process_timeout: int = 120
    safety: bool = False
    description: str = "Processing files"
    logging: bool = True


class DefaultStage(Stage):

    def __init__(self, config: StageConfig):
        self._name = config.name
        self.config = config
        self.callbacks = get_default_callbacks(
            CallbackConfig(
                name=self._name,
                statistics_key=self.config.statistics_key,
                file_key=self.config.file_key,
                processing=config.processing,
                dataset_stats_callback=config.dataset_stats_callback,
                save_meta_callback=config.save_meta_callback,
                save_pickle_callback=config.save_pickle_callback,
            )
        )

    @property
    def name(self) -> str:
        return self._name

    def __call__(self, filtered_files: FilesWithMeta | None) -> Any:
        policy = (
            self._use_meta
            if self._use_meta is not None
            else self.config.processing.use_meta
        )
        if not isinstance(policy, bool):
            raise ValueError("A stage-path cache policy must be resolved by run_stages")
        return process_files(
            filtered_files,
            filter_one=partial(
                _process_file_worker_wrapper,
                function=self.config.worker_wrapper,
                use_meta=policy,
                meta_suffix=self.config.processing.meta_suffix,
                file_key=self.config.file_key,
                stats_key=self.config.statistics_key,
            ),
            prepare_item=partial(
                _prepare_item,
                statistics_key=self.config.statistics_key,
                file_key=self.config.file_key,
            ),
            desc=self.config.description,
            error_stdout=logger.error,
            start_method=self.config.start_method,
            task_timeout=self.config.task_timeout,
            process_timeout=self.config.process_timeout,
            safety=self.config.safety,
            logging=self.config.logging,
            annotations=self.config.processing.annotations,
            max_workers=self.config.processing.max_workers,
            override_files=self.config.processing.override_files,
        )
