import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from terminal_app.processing_utils.core import Callback, SequenceStages, run_stages
from terminal_app.processing_utils.default_stage import DefaultStage, StageConfig
from terminal_app.processing_utils.stage_utils import (
    ProcessingConfig,
    SaveMetaCallbackConfig,
)
from terminal_app.processing_utils.types import StageItem


def compute(file):
    return {"value": 9}, None, True


def build_stage(use_meta, output=None):
    return DefaultStage(
        StageConfig(
            name="metric",
            file_key="sample_file",
            statistics_key="sample_statistics",
            processing=ProcessingConfig(None, output, 1, use_meta, "_meta.json", None),
            dataset_stats_callback=None,
            save_meta_callback=SaveMetaCallbackConfig(True, False) if output else None,
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
    callback = Mock(
        spec=Callback, side_effect=lambda result, name: callbacks.append(name)
    )
    callback.name = "record"
    node.callbacks = [callback]
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


def crash(file):
    os._exit(1)


@pytest.mark.parametrize("safety", [False, True])
def test_worker_death_cannot_restore_seeded_cached_score(tmp_path: Path, safety):
    source = tmp_path / "input"
    source.write_text("mesh")
    node = build_stage(False)
    node.config.worker_wrapper = crash
    node.config.safety = safety
    item = StageItem(
        "id",
        source,
        {
            "sample_statistics": {"pd_file": "old", "value": 1},
            "sibling_statistics": {"value": 8},
        },
    )
    result = run_stages([node], filtered_files=[item], use_meta=[])["metric"]
    assert result[0][0].meta["sample_statistics"] == {}
    assert result[0][0].meta["sibling_statistics"] == {"value": 8}
    assert not result[1]
    assert len(result[2]) == 1


@pytest.mark.parametrize("safety", [False, True])
def test_worker_death_is_saved_with_owned_file_and_sibling_metadata(tmp_path, safety):
    source = tmp_path / "input.stl"
    source.write_text("mesh")
    target = tmp_path / "input_meta.json"
    target.write_text(json.dumps({"sibling_statistics": {"value": 3}}))
    node = build_stage(False, tmp_path)
    node.config.worker_wrapper = crash
    node.config.safety = safety
    result = run_stages(
        [node], filtered_files=[StageItem("id", source, {})], use_meta=False
    )["metric"]
    saved = json.loads(target.read_text())
    assert saved["sample_statistics"]["error"] == next(iter(result[2].values())).message
    assert saved["sample_file"] == "{json_path}/input.stl"
    assert saved["sibling_statistics"] == {"value": 3}


@pytest.mark.parametrize("has_cached_section", [False, True])
@pytest.mark.parametrize("source_name", ["source", 'source"quoted'])
def test_symlink_cache_saves_locally_without_changing_source(
    tmp_path, has_cached_section, source_name
):
    source_dir, output = tmp_path / source_name, tmp_path / "output"
    source_dir.mkdir()
    output.mkdir()
    source = source_dir / "original.stl"
    source.write_text("mesh")
    preview = source_dir / "preview.png"
    preview.write_bytes(b"preview")
    source_meta = source_dir / "original_meta.json"
    payload = {"sibling_statistics": {"preview": "{json_path}/preview.png", "value": 3}}
    if has_cached_section:
        payload["sample_statistics"] = {
            "value": 1,
            "preview": "{json_path}/preview.png",
        }
    original = json.dumps(payload)
    source_meta.write_text(original)
    sample = output / "sample.stl"
    sample.symlink_to(source)
    item = StageItem("id", sample, {})
    node = build_stage(True, output)
    cached = run_stages([node], filtered_files=[item], use_meta=True)["metric"][0][0]
    local_meta = output / "sample_meta.json"
    if has_cached_section:
        assert Path(cached.meta["sample_statistics"]["preview"]).resolve() == preview
        saved = json.loads(local_meta.read_text())
        saved_preview = saved["sample_statistics"]["preview"].replace(
            "{json_path}", str(output)
        )
        assert Path(saved_preview).resolve() == preview
    values = [cached.meta["sample_statistics"]["value"]] + [
        run_stages([node], filtered_files=[item], use_meta=policy)["metric"][0][0].meta[
            "sample_statistics"
        ]["value"]
        for policy in (False, True)
    ]
    assert values == [1 if has_cached_section else 9, 9, 9]
    assert not local_meta.is_symlink()
    saved = json.loads(local_meta.read_text())
    assert saved["sibling_statistics"]["value"] == 3
    saved_preview = saved["sibling_statistics"]["preview"].replace(
        "{json_path}", str(output)
    )
    assert Path(saved_preview).resolve() == preview
    assert source_meta.read_text() == original
