import json
from functools import partial
from pathlib import Path

from terminal_app.processing_utils.base import Stage
from terminal_app.processing_utils.pipeline import SequenceStages, run_stages
from terminal_app.processing_utils.stage_utils import DatasetStatsCallback
from terminal_app.processing_utils.types import StageItem
from terminal_app.processing_utils.utils import stage_stats


class MetricStage(Stage):
    name = "metric"

    def __init__(self, value):
        self.value = value

    def __call__(self, files):
        for item in files:
            item.meta["metric_file"] = str(item.path)
            item.meta["metric_statistics"] = {"value": self.value}
        return files, files, {}


def test_nested_dataset_callback_uses_own_stage_despite_root_name(tmp_path):
    callback = DatasetStatsCallback(
        {
            "metric": partial(
                stage_stats,
                field_configs={"value": {"kind": "statistics"}},
                file_key="metric_file",
                stats_key="metric_statistics",
            )
        },
        tmp_path,
        "errors",
        "statistics",
        None,
        False,
    )
    nested = MetricStage(2)
    nested.callbacks = [callback]
    run_stages(
        [MetricStage(100), SequenceStages("parent", [nested])],
        filtered_files=[StageItem("one", Path("sample.stl"), {})],
    )
    saved = json.loads((tmp_path / "statistics.json").read_text())
    values = saved["metric_statistics"]["all_metric_file"]["statistics"]
    assert values["value"]["mean"]["value"] == 2
    assert list(callback.stage_stats) == ["metric"]


def test_default_callbacks_cannot_leak_between_custom_stage_instances():
    first, second = MetricStage(1), MetricStage(2)
    calls = []
    first.callbacks += (lambda results, name: calls.append(name),)
    run_stages([first], filtered_files=[StageItem("one", Path("one"), {})])
    run_stages([second], filtered_files=[StageItem("two", Path("two"), {})])
    assert calls == ["metric"]
    assert not second.callbacks
