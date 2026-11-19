from pathlib import Path

import pytest

from terminal_app.processing_utils.base import Stage
from terminal_app.processing_utils.pipeline import run_stages
from terminal_app.processing_utils.types import StageError, StageItem


class ResultStage(Stage):
    name = "leaf"

    def __init__(self, result):
        self.result = result

    def __call__(self, items):
        return self.result(items)


def test_error_normalization_preserves_colliding_generated_and_explicit_keys():
    def result(items):
        item = items[0]
        return (
            items,
            items,
            {
                "first": StageError(item.item_id, item.path, "", "first event"),
                "leaf:id": StageError(item.item_id, item.path, "leaf", "second event"),
            },
        )

    errors = run_stages(
        [ResultStage(result)], filtered_files=[StageItem("id", Path("input"))]
    )["leaf"][2]
    assert {error.message for error in errors.values()} == {
        "first event",
        "second event",
    }


def test_passed_item_must_be_present_in_declared_all_files():
    stage = ResultStage(lambda items: ([], items, {}))
    with pytest.raises(ValueError, match="absent from all_files"):
        run_stages([stage], filtered_files=[StageItem("id", Path("input"))])
