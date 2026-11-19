import json
from pathlib import Path

import pytest

from terminal_app.processing_utils.metadata_io import read_metadata
from terminal_app.processing_utils.types import StageItem
from terminal_app.processing_utils.utils import save_meta_callback


@pytest.mark.parametrize("relative", [False, True])
@pytest.mark.parametrize("stats_key", ["score", None])
def test_regular_save_preserves_unowned_protocol_values(tmp_path, relative, stats_key):
    path = tmp_path / "sample.stl"
    path.write_text("mesh")
    target = tmp_path / "sample_meta.json"
    protocol = {
        "{json_path}": {"literal": "text containing {json_path}/as-a-token"},
        "harbor_result": {"task_id": {"path": "{json_path}/opaque-task"}},
        "existing_absolute_path": str(path),
        "values": ["{json_path}", "{json_path}/another-protocol-value"],
    }
    sibling = {"preview": "{json_path}/sibling.png", "absolute": str(path)}
    target.write_text(json.dumps({"generation_statistics": protocol, "sibling": sibling}))
    update = {"score": {"value": 3}, "input": path}
    if stats_key is not None:
        update["generation_statistics"] = {"stale": True}
    item = StageItem("id", path, update)
    save_meta_callback(
        {"metric": ([item], [item], {})},
        "metric" if stats_key is not None else None,
        stats_key,
        file_key="input",
        relative=relative,
        for_each_file=True,
    )
    assert json.loads(target.read_text()) == {
        "generation_statistics": protocol,
        "sibling": sibling,
        "score": {"value": 3},
        "input": "{json_path}/sample.stl" if relative else str(path),
    }


@pytest.mark.parametrize("relative", [False, True])
def test_link_materialization_rebases_only_explicit_value_references(tmp_path, relative):
    source_dir = tmp_path / 'source"quoted'
    source_dir.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    preview = source_dir / "preview.png"
    preview.write_bytes(b"preview")
    source = source_dir / "original_meta.json"
    sibling = {
        "{json_path}/literal-key": "{json_path}",
        "text": "embedded {json_path}/token",
        "absolute": str(preview),
        "nested": [{"preview": "{json_path}/preview.png"}],
    }
    original = json.dumps({"sibling_statistics": sibling}).encode()
    source.write_bytes(original)
    target = output / "sample_meta.json"
    target.symlink_to(source)
    path = output / "sample.stl"
    item = StageItem("id", path, {"score": {"value": 3}})
    save_meta_callback(
        {"metric": ([item], [item], {})},
        "metric",
        "score",
        relative=relative,
        for_each_file=True,
    )
    saved = json.loads(target.read_text())
    stored_preview = saved["sibling_statistics"]["nested"][0]["preview"]
    assert stored_preview.startswith("{json_path}/")
    assert Path(stored_preview.replace("{json_path}", str(output))).resolve() == preview
    loaded = read_metadata(target)
    assert Path(loaded["sibling_statistics"]["nested"][0]["preview"]).resolve() == preview
    assert saved == {
        "sibling_statistics": {
            **sibling,
            "nested": [{"preview": stored_preview}],
        },
        "score": {"value": 3},
    }
    assert not target.is_symlink()
    assert source.read_bytes() == original
