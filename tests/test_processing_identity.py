from pathlib import Path

import pytest

from terminal_app.processing_utils.base import Stage
from terminal_app.processing_utils.pipeline import run_stages
from terminal_app.processing_utils.types import StageItem, normalize_items


class ReversePairs(Stage):
    name = "reverse"

    def __call__(self, files):
        pairs = [(item.path, item.meta) for item in reversed(files)]
        return pairs, pairs, {}


def test_legacy_pairs_cannot_swap_same_path_attempt_identities():
    inputs = [
        StageItem("a", Path("same.stl"), {"owner": "a"}),
        StageItem("b", Path("same.stl"), {"owner": "b"}),
    ]
    with pytest.raises(ValueError, match="ambiguous output path"):
        run_stages([ReversePairs()], filtered_files=inputs)
    assert [(item.item_id, item.meta["owner"]) for item in inputs] == [
        ("a", "a"),
        ("b", "b"),
    ]


def test_reordered_legacy_pairs_preserve_unambiguous_identities():
    inputs = [
        StageItem("a", Path("a.stl"), {"owner": "a"}),
        StageItem("b", Path("b.stl"), {"owner": "b"}),
    ]
    all_items, passed, _ = run_stages([ReversePairs()], filtered_files=inputs)[
        "reverse"
    ]
    assert {item.item_id: item.meta["owner"] for item in all_items} == {
        "a": "a",
        "b": "b",
    }
    assert [item.item_id for item in passed] == ["b", "a"]


def test_explicit_ids_allow_reordered_attempts_with_same_path():
    inputs = [
        StageItem("a", Path("same.stl"), {"owner": "a"}),
        StageItem("b", Path("same.stl"), {"owner": "b"}),
    ]
    result = normalize_items(list(reversed(inputs)), inputs)
    assert [(item.item_id, item.meta["owner"]) for item in result] == [
        ("b", "b"),
        ("a", "a"),
    ]
