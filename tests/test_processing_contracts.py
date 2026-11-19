from pathlib import Path

import pytest

from terminal_app.processing_utils.core import (
    ParallelStages,
    SequenceStages,
    Stage,
    run_stages,
)
from terminal_app.processing_utils.types import StageError, StageItem


class EchoStage(Stage):
    def __init__(self, name):
        self._name = name

    @property
    def name(self):
        return self._name

    def __call__(self, items):
        return items, items, {}


class ErrorStage(EchoStage):
    def __call__(self, items):
        item = items[0]
        error = StageError(item.item_id, item.path, self.name, self.name + " failed")
        return items, items, {"error": error}


def test_transition_changes_to_selected_item_reach_stage_without_mutating_input():
    stage = EchoStage("mesh")

    def transition(all_files, filtered_files, errors):
        filtered_files[0].path = Path("output.stl")
        filtered_files[0].meta["ready"] = True
        return all_files, filtered_files, errors

    stage.transition = transition
    original = StageItem("id", Path("input.py"))
    all_files, passed, errors = run_stages([stage], filtered_files=[original])["mesh"]
    assert passed[0].path == Path("output.stl")
    assert passed[0].meta == {"ready": True}
    assert all_files[0] is passed[0]
    assert not errors
    assert original.path == Path("input.py")
    assert original.meta == {}


@pytest.mark.parametrize("composite", [SequenceStages, ParallelStages])
def test_composites_keep_distinct_errors_with_identical_mapping_keys(composite):
    node = composite("parent", [ErrorStage("one"), ErrorStage("two")])
    result = run_stages([node], filtered_files=[StageItem("id", Path("input"))])
    assert {error.message for error in result["parent"][2].values()} == {
        "one failed",
        "two failed",
    }


def test_errors_cannot_reference_another_attempt():
    class UnknownErrorStage(EchoStage):
        def __call__(self, items):
            error = StageError("unknown", items[0].path, self.name, "failed")
            return items, items, {"error": error}

    with pytest.raises(ValueError, match="unknown item"):
        run_stages(
            [UnknownErrorStage("leaf")], filtered_files=[StageItem("id", Path("input"))]
        )


def test_omitted_item_keeps_its_reported_error():
    class MissingStage(EchoStage):
        def __call__(self, items):
            error = StageError(
                items[0].item_id, items[0].path, "", "failed before output"
            )
            return [], [], {"error": error}

    all_files, passed, errors = run_stages(
        [MissingStage("leaf")], filtered_files=[StageItem("id", Path("input"))]
    )["leaf"]
    assert len(all_files) == 1
    assert not passed
    assert "failed before output" in {error.message for error in errors.values()}
    assert all(error.stage == "leaf" for error in errors.values())


def test_stage_tree_cycle_fails_before_execution():
    node = SequenceStages("parent", [EchoStage("leaf")])
    node.stages = (node,)
    with pytest.raises(ValueError, match="exactly one tree position"):
        run_stages([node], filtered_files=[])


@pytest.mark.parametrize(
    "names", [("", "leaf"), ("parent/leaf", "leaf"), ("leaf", "leaf")]
)
def test_invalid_sibling_names_are_rejected(names):
    with pytest.raises(ValueError, match="Invalid or duplicate stage names"):
        run_stages(
            [SequenceStages("parent", [EchoStage(name) for name in names])],
            filtered_files=[],
        )


def test_composite_callback_updates_flow_forward_without_changing_child_snapshot():
    def annotate(results, name):
        results[name][0][0].meta["annotation"] = "ready"

    node = SequenceStages("parent", [EchoStage("child")], callbacks=[annotate])
    result = run_stages(
        [node, EchoStage("after")], filtered_files=[StageItem("id", Path("input"))]
    )
    assert result["after"][1][0].meta == {"annotation": "ready"}
    assert result["parent/child"][0][0].meta == {}
    assert result["parent"][0][0] is result["parent"][1][0]
