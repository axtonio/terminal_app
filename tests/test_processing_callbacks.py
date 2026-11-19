import json
from functools import partial
from pathlib import Path
from unittest.mock import Mock

from terminal_app.processing_utils.base import Callback, Stage
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
    callback = Mock(spec=Callback, side_effect=lambda results, name: calls.append(name))
    callback.name = "record"
    first.callbacks += (callback,)
    run_stages([first], filtered_files=[StageItem("one", Path("one"), {})])
    run_stages([second], filtered_files=[StageItem("two", Path("two"), {})])
    assert calls == ["metric"]
    assert not second.callbacks


def test_stage_and_final_callbacks_report_progress_and_duration():
    messages = []
    stage_callback = Mock(spec=Callback)
    stage_callback.name = "save_meta"
    final_callback = Mock(spec=Callback)
    final_callback.name = "dataset_stats"
    stage = MetricStage(1)
    stage.callbacks = [stage_callback]
    results = run_stages(
        [stage],
        callbacks=[final_callback],
        stdout=messages.append,
        filtered_files=[StageItem("one", Path("one"), {})],
    )
    stage_callback.assert_called_once_with(results, "metric")
    final_callback.assert_called_once_with(results, None)
    assert messages[2:4] == ["Do stage callbacks", "Do save_meta callback"]
    assert messages[4].startswith("save_meta callback duration: ")
    assert messages[5:7] == [
        "Do final callbacks after all stages",
        "Do dataset_stats callback",
    ]
    assert messages[7].startswith("dataset_stats callback duration: ")
