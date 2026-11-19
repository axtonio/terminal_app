import json
from pathlib import Path

from terminal_app.processing_utils.core import SequenceStages, run_stages
from terminal_app.processing_utils.default_stage import DefaultStage, StageConfig
from terminal_app.processing_utils.stage_utils import ProcessingConfig
from terminal_app.processing_utils.types import StageItem


def compute(file):
    return {"value": 9}, None, True


def build_stage(use_meta):
    return DefaultStage(
        StageConfig(
            name="metric",
            file_key="sample_file",
            statistics_key="sample_statistics",
            processing=ProcessingConfig(None, None, 1, use_meta, "_meta.json", None),
            dataset_stats_callback=None,
            save_meta_callback=None,
            save_pickle_callback=None,
            worker_wrapper=compute,
            task_timeout=1,
            process_timeout=2,
        )
    )


def test_cache_policy_controls_symlink_inputs_and_callbacks_still_run(tmp_path: Path):
    source = tmp_path / "source.stl"
    source.write_text("mesh")
    source.with_name("source_meta.json").write_text(
        json.dumps({"sample_statistics": {"value": 1}})
    )
    link = tmp_path / "link.stl"
    link.symlink_to(source.name)
    node = build_stage(True)
    callbacks = []
    node.callbacks = [lambda result, name: callbacks.append(name)]
    inputs = [StageItem("id", link, {"sample_statistics": {"value": 0}})]
    cached = run_stages(
        [SequenceStages("cad", [node])], filtered_files=inputs, use_meta=["cad"]
    )
    assert cached["cad"][0][0].meta["sample_statistics"]["value"] == 1
    fresh = run_stages(
        [SequenceStages("cad", [node])], filtered_files=inputs, use_meta=[]
    )
    assert fresh["cad"][0][0].meta["sample_statistics"]["value"] == 9
    assert callbacks == ["cad/metric", "cad/metric"]


def test_missing_input_replaces_stale_owned_section(tmp_path: Path):
    source = StageItem(
        "id",
        tmp_path / "missing",
        {"sample_statistics": {"value": 1}, "other": {"keep": 3}},
    )
    result = run_stages([build_stage(False)], filtered_files=[source], use_meta=[])[
        "metric"
    ]
    assert result[0][0].meta == {
        "sample_file": str(source.path),
        "sample_statistics": {"error": "file_not_exist"},
        "other": {"keep": 3},
    }
    assert not result[1]


def test_cached_global_failure_cannot_restore_stale_sibling_sections(tmp_path: Path):
    source = tmp_path / "input"
    source.write_text("mesh")
    source.with_name("input_meta.json").write_text(
        json.dumps({"error": "failed", "sibling_statistics": {"value": 0}})
    )
    item = StageItem("id", source, {"sibling_statistics": {"value": 8}})
    result = run_stages([build_stage(True)], filtered_files=[item], use_meta=True)[
        "metric"
    ]
    assert result[0][0].meta["sibling_statistics"] == {"value": 8}
    assert result[0][0].meta["sample_statistics"]["error"] == "failed"
