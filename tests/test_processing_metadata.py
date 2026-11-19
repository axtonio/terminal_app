import json

import pytest

from terminal_app.processing_utils.types import StageError, StageItem
from terminal_app.processing_utils.utils import save_meta_callback


def test_filtered_save_does_not_copy_another_items_error_with_the_same_path(tmp_path):
    path = tmp_path / "shared.stl"
    good = StageItem("good", path, {"score": {}})
    bad = StageItem("bad", path, {"score": {}})
    error = StageError("bad", path, "metric", "bad item")
    save_meta_callback(
        {"metric": ([good, bad], [good], {"bad": error})},
        "metric",
        "score",
        filtered_only=True,
        for_each_file=True,
    )
    assert json.loads((tmp_path / "shared_meta.json").read_text()) == {"score": {}}


def test_save_matches_error_identity_after_path_change(tmp_path):
    path = tmp_path / "output.stl"
    item = StageItem("id", path, {"score": {"elapsed": 2}, "input": str(path)})
    error = StageError("id", tmp_path / "input.py", "metric", "computation failed")
    save_meta_callback(
        {"metric": ([item], [], {"error": error})},
        "metric",
        "score",
        file_key="input",
        for_each_file=True,
    )
    assert json.loads((tmp_path / "output_meta.json").read_text()) == {
        "score": {"elapsed": 2, "error": "computation failed"},
        "input": str(path),
    }


def test_legacy_save_still_matches_path_errors(tmp_path):
    path = tmp_path / "sample.stl"
    save_meta_callback(
        {"metric": ([(path, {})], [], {path: "failed"})},
        "metric",
        "score",
        for_each_file=True,
    )
    assert json.loads((tmp_path / "sample_meta.json").read_text()) == {
        "score": {"error": "failed"}
    }


def test_failed_symlink_replacement_keeps_source_and_link(tmp_path):
    source = tmp_path / "source_meta.json"
    original = '{"sibling": {"value": 3}}'
    source.write_text(original)
    target = tmp_path / "sample_meta.json"
    target.symlink_to(source.name)
    item = StageItem("id", tmp_path / "sample.stl", {"score": {"bad": object()}})
    before = set(tmp_path.iterdir())
    with pytest.raises(TypeError, match="not JSON serializable"):
        save_meta_callback(
            {"metric": ([item], [item], {})}, "metric", "score", for_each_file=True
        )
    assert target.is_symlink()
    assert source.read_text() == original
    assert set(tmp_path.iterdir()) == before


def test_empty_owned_update_keeps_metadata_symlink(tmp_path):
    source = tmp_path / "source_meta.json"
    original = b'{"sibling": {"value": 3}}\n'
    source.write_bytes(original)
    target = tmp_path / "sample_meta.json"
    target.symlink_to(source.name)
    item = StageItem("id", tmp_path / "sample.stl", {"sibling": {"value": 8}})
    save_meta_callback(
        {"metric": ([item], [item], {})}, "metric", "score", for_each_file=True
    )
    assert target.is_symlink()
    assert target.readlink().as_posix() == source.name
    assert target.read_bytes() == original
    assert source.read_bytes() == original
