import json
from pathlib import Path

from terminal_app.processing_utils.statistics import calculate_stats
from terminal_app.processing_utils.types import StageItem
from terminal_app.processing_utils.utils import save_meta_callback

FIELDS = {
    "CD": {"kind": "statistics", "store_examples": True},
    "flag": {"kind": "ratio", "store_examples": True},
}


def test_statistics_keep_zero_and_example_with_single_observation():
    result = calculate_stats([("one", {"CD": 0, "flag": False})], FIELDS)
    assert result["summary"] == {"count": 1}
    assert result["statistics"]["CD"]["mean"] == {"value": 0, "example": "one"}
    assert result["statistics"]["CD"]["std"] == {"value": 0, "example": None}
    assert result["ratios"]["flag"] == {
        "count": 0,
        "ratio": 0,
        "positive_example": None,
        "negative_example": "one",
    }


def test_empty_groups_are_json_safe_and_keep_declared_schema():
    result = calculate_stats([], FIELDS)
    assert result["summary"]["count"] == 0
    assert result["statistics"]["CD"]["mean"] == {"value": None, "example": None}
    assert result["ratios"]["flag"]["ratio"] is None
    json.dumps(result, allow_nan=False)


def test_missing_observation_cannot_be_negative_example():
    result = calculate_stats(
        [("missing", {}), ("positive", {"flag": True}), ("negative", {"flag": False})],
        FIELDS,
    )
    assert result["ratios"]["flag"] == {
        "count": 1,
        "ratio": 1 / 3,
        "positive_example": "positive",
        "negative_example": "negative",
    }


def test_representative_examples_are_nearest_and_nan_inf_excluded():
    result = calculate_stats(
        [
            ("zero", {"CD": 0}),
            ("ten", {"CD": 10}),
            ("eleven", {"CD": 11}),
            ("missing", {"CD": float("nan")}),
            ("infinite", {"CD": float("inf")}),
        ],
        FIELDS,
    )
    assert result["statistics"]["CD"]["mean"] == {"value": 7, "example": "ten"}
    assert result["statistics"]["CD"]["max"]["example"] == "eleven"
    json.dumps(result, allow_nan=False)


def test_section_save_preserves_newer_sibling_metadata(tmp_path: Path):
    path = tmp_path / "sample.stl"
    output = tmp_path / "sample_meta.json"
    output.write_text(
        json.dumps(
            {
                "cd_statistics": {"CD": 2},
                "iou_statistics": {"IoU": 0.1},
                "iou_file": "current.stl",
                "source": "keep",
            }
        )
    )
    snapshot = {
        "cd_statistics": {"CD": 1},
        "iou_statistics": {"IoU": 0.8},
        "iou_file": "stale.stl",
    }
    item = StageItem("id", path, snapshot)
    save_meta_callback(
        {"iou": ([item], [item], {})}, "iou", "iou_statistics", for_each_file=True
    )
    assert json.loads(output.read_text()) == {
        "cd_statistics": {"CD": 2},
        "iou_statistics": {"IoU": 0.8},
        "iou_file": "current.stl",
        "source": "keep",
    }


def test_writer_preserves_explicit_file_key_without_copying_sibling(tmp_path: Path):
    path = tmp_path / "sample"
    item = StageItem(
        "id",
        path,
        {"custom_input": str(path), "score": {"value": 0}, "sibling": {"old": 1}},
    )
    save_meta_callback(
        {"score": ([item], [item], {})},
        "score",
        "score",
        for_each_file=True,
        file_key="custom_input",
    )
    assert json.loads((tmp_path / "sample_meta.json").read_text()) == {
        "custom_input": str(path),
        "score": {"value": 0},
    }
