import inspect
import logging
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Callable, Literal

from terminal_app.utils import link_file

from .core import Stage, process_files
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
from .utils import (
    FilesWithMeta,
)

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
    if not file.exists():
        return (file, meta, "file_not_exist", False)

    passed: bool = True
    failed_filter: str | None = None

    meta[file_key] = file_str
    meta[stats_key] = {}

    meta_path = file.with_name(file.stem + meta_suffix)

    if file.is_symlink():
        meta_name = file.readlink().stem + meta_suffix
        source_meta_path = (file.parent / file.readlink()).with_name(meta_name)

        if source_meta_path.exists() and (
            not meta_path.exists() or meta_path.is_symlink()
        ):
            link_file(file.readlink().with_name(meta_name), meta_path)
            use_meta = True

    get_result = False
    if use_meta and meta_path.exists():
        meta_result = process_meta_file(meta_path, meta, stats_key)
        if meta_result is not None:
            get_result = True
            meta, failed_filter, passed = meta_result
            if not meta.get(stats_key, None) and passed:
                get_result = False

    if not get_result:
        try:
            meta[stats_key], failed_filter, passed = _call_worker_function(
                function,
                file,
                device,
            )
        except Exception as ex:
            logger.error(str(ex))
            logger.error(f"File: {file_str}")
            passed = False
            failed_filter = str(ex)

    process_failed_filter(failed_filter, passed, meta, stats_key)

    return (file, meta, failed_filter, passed)


def _process_files(
    use_meta: bool,
    meta_suffix: str,
    file_key: str,
    statistics_key: str,
    worker_wrapper: WorkerFn,
    start_method: _StartMethod,
    task_timeout: int,
    process_timeout: int,
    safety: bool,
    description: str,
    logging: bool,
):
    return partial(
        process_files,
        filter_one=partial(
            _process_file_worker_wrapper,
            function=worker_wrapper,
            use_meta=use_meta,
            meta_suffix=meta_suffix,
            file_key=file_key,
            stats_key=statistics_key,
        ),
        desc=description,
        error_stdout=logger.error,
        start_method=start_method,
        task_timeout=task_timeout,
        process_timeout=process_timeout,
        safety=safety,
        logging=logging,
    )


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
        return partial(
            _process_files(
                use_meta=self.config.processing.use_meta,
                meta_suffix=self.config.processing.meta_suffix,
                file_key=self.config.file_key,
                statistics_key=self.config.statistics_key,
                worker_wrapper=self.config.worker_wrapper,
                start_method=self.config.start_method,
                task_timeout=self.config.task_timeout,
                process_timeout=self.config.process_timeout,
                safety=self.config.safety,
                description=self.config.description,
                logging=self.config.logging,
            ),
            annotations=self.config.processing.annotations,
            max_workers=self.config.processing.max_workers,
        )(filtered_files)
