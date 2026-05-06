import logging
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Callable

from terminal_app.processing_utils import (
    FilesWithMeta,
    Stage,
    process_files,
)
from terminal_app.utils import link_file

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

logger = logging.getLogger(__name__)


def _process_file_worker_wrapper(
    file_str: str,
    meta: dict[str, Any],
    device: str,
    use_meta: bool,
    function: Callable[[Path], tuple[dict[str, Any], str | None, bool]],
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
        source_meta_path = (
            (file.parent / file.readlink()).resolve().with_name(file.stem + meta_suffix)
        )
        if source_meta_path.exists():
            link_file(file.readlink().with_name(file.stem + meta_suffix), meta_path)
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
            meta[stats_key], failed_filter, passed = function(
                file,
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
    worker_wrapper: Callable[[Path], tuple[dict[str, Any], str | None, bool]],
    file_key: str,
    statistics_key: str,
    description: str,
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
        start_method="fork",  # Explicitly use fork to avoid serialization issues with spawn
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
    worker_wrapper: Callable[[Path], tuple[dict[str, Any], str | None, bool]]
    description: str = "Processing files"


class DefaultStage(Stage):

    def __init__(self, config: StageConfig):
        self._name = config.name
        self.config = config
        self.callbacks = get_default_callbacks(
            CallbackConfig(
                name=self._name,
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
                worker_wrapper=self.config.worker_wrapper,
                file_key=self.config.file_key,
                statistics_key=self.config.statistics_key,
                description=self.config.description,
            ),
            annotations=self.config.processing.annotations,
            max_workers=self.config.processing.max_workers,
        )(filtered_files)
