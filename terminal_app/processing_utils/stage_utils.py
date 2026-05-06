import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from terminal_app.processing_utils import (
    Callback,
    PipesResult,
    dataset_stats,
    save_meta_callback,
    save_pickle_callback,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ProcessingConfig:
    annotations: Sequence[str | Path] | None
    output: Path
    max_workers: int
    use_meta: bool
    meta_suffix: str
    prefix: str | None


@dataclass(slots=True)
class SaveMetaCallbackConfig:
    for_each_file: bool
    for_all_files: bool


@dataclass(slots=True)
class SavePickleCallbackConfig:
    pickle_mapping: dict[str, str]
    root_folder: Path
    pickle_name: str


@dataclass(slots=True)
class DatasetStatsCallbackConfig:
    stage_stats: dict[str, Callable[[PipesResult, str, dict[str, Any]], None]]
    print_stats: bool


@dataclass(slots=True)
class CallbackConfig:
    name: str
    processing: ProcessingConfig
    dataset_stats_callback: DatasetStatsCallbackConfig | None
    save_meta_callback: SaveMetaCallbackConfig | None
    save_pickle_callback: SavePickleCallbackConfig | None


class DatasetStatsCallback(Callback):
    def __init__(
        self,
        stage_stats: dict[str, Callable[[PipesResult, str, dict[str, Any]], None]],
        output: Path,
        failed_output_name: str,
        stat_output_name: str,
        prefix: str | None,
        print_stats: bool,
    ):
        self.output = output
        self.prefix = prefix or ""
        self.stage_stats = stage_stats
        self.failed_output_name = failed_output_name
        self.stat_output_name = stat_output_name
        self.print_stats = print_stats

    def __call__(self, stages_result: PipesResult, stage_name: str | None) -> None:
        dataset_stats(
            stages_result,
            stage_stats=self.stage_stats,
            failed_output=self.output / f"{self.prefix}{self.failed_output_name}.json",
            stat_output=self.output / f"{self.prefix}{self.stat_output_name}.json",
            stdout=logger.info,
            relative=True,
            print_stats=self.print_stats,
        )

    @property
    def name(self) -> str:
        return "dataset_statistics"


class SaveMetaCallback(Callback):
    def __init__(
        self,
        output: Path,
        meta_output_name: str,
        for_each_file: bool,
        for_all_files: bool,
        meta_suffix: str,
        prefix: str | None,
    ):
        self.output = output
        self.prefix = prefix or ""
        self.meta_output_name = meta_output_name
        self.for_each_file = for_each_file
        self.for_all_files = for_all_files
        self.meta_suffix = meta_suffix

    def __call__(self, stages_result: PipesResult, stage_name: str | None) -> None:
        save_meta_callback(
            stages_result,
            stage_name,
            output_path=(
                self.output / f"{self.prefix}{self.meta_output_name}.json"
                if self.for_all_files
                else None
            ),
            relative=True,
            for_each_file=self.for_each_file,
            each_file_output_path=lambda file: file.with_name(
                file.stem + self.meta_suffix
            ),
        )

    @property
    def name(self) -> str:
        return "save_meta"


class SavePickleCallback(Callback):
    def __init__(self, root_folder: Path, output_path: Path, mapping: dict[str, str]):
        self.root_folder = root_folder
        self.output_path = output_path
        self.mapping = mapping

    def __call__(self, stages_result: PipesResult, stage_name: str | None) -> None:
        save_pickle_callback(
            stages_result,
            root_folder=self.root_folder,
            output_path=self.output_path,
            mapping=self.mapping,
        )

    @property
    def name(self) -> str:
        return "save_pickle"


def get_default_callbacks(config: CallbackConfig):
    callbacks: list[Callback] = []
    if config.dataset_stats_callback is not None:
        callbacks.append(
            DatasetStatsCallback(
                config.dataset_stats_callback.stage_stats,
                config.processing.output,
                f"{config.name}_errors",
                f"{config.name}_statistics",
                prefix=config.processing.prefix,
                print_stats=config.dataset_stats_callback.print_stats,
            )
        )
    if config.save_meta_callback is not None:
        callbacks.append(
            SaveMetaCallback(
                config.processing.output,
                f"{config.name}_meta",
                config.save_meta_callback.for_each_file,
                config.save_meta_callback.for_all_files,
                config.processing.meta_suffix,
                prefix=config.processing.prefix,
            )
        )
    if config.save_pickle_callback is not None:
        callbacks.append(
            SavePickleCallback(
                config.save_pickle_callback.root_folder,
                config.processing.output / config.save_pickle_callback.pickle_name,
                config.save_pickle_callback.pickle_mapping,
            )
        )

    return callbacks


def process_failed_filter(
    failed_filter: str | None, passed: bool, meta: dict[str, Any], stats_key: str
):
    if failed_filter:
        meta[stats_key][f"is_{failed_filter}"] = True
        if passed:
            meta[stats_key]["warning"] = failed_filter
        else:
            meta[stats_key]["error"] = failed_filter


def process_meta_file(meta_file: Path, meta: dict[str, Any], stats_key: str):
    failed_filter: str | None = None
    passed: bool = True

    saved_meta: dict = json.loads(
        meta_file.read_text().replace("{json_path}", meta_file.parent.as_posix())
    )
    failed_filter = saved_meta.get("error", None)
    if failed_filter:
        meta.update(saved_meta)
        passed = False
        return meta, failed_filter, passed
    if (meta_data := saved_meta.get(stats_key, None)) is not None:
        meta[stats_key] = meta_data
        if (failed_filter := meta_data.get("error", None)) is not None:
            passed = False
        else:
            failed_filter = meta_data.get("warning", None)
        return meta, failed_filter, passed

    return None
