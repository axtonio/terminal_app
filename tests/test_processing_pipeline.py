from pathlib import Path

import pytest

from terminal_app.processing_utils.core import (
    ParallelStages,
    SequenceStages,
    Stage,
    run_stages,
)
from terminal_app.processing_utils.types import StageItem, add_error
from terminal_app.processing_utils.utils import files_transition


class FunctionStage(Stage):
    def __init__(self, name, function, callbacks=()):
        self._name = name
        self.function = function
        self.callbacks = list(callbacks)

    @property
    def name(self):
        return self._name

    def __call__(self, items):
        all_files, passed, errors = [], [], {}
        for item in items:
            success, error = self.function(item)
            all_files.append(item)
            if success:
                passed.append(item)
            if error:
                add_error(errors, item, "", error)
        return all_files, passed, errors


def put(section, value, passed=True):
    def apply(item):
        item.meta[section] = value
        return passed, None if passed else section + " failed"

    return apply


def test_nested_sequence_keeps_rejected_attempts_and_branch_errors():
    original = [
        StageItem("one", Path("one.py"), {}),
        StageItem("two", Path("two.py"), {}),
    ]
    code = FunctionStage(
        "code",
        lambda item: (
            item.item_id == "one",
            "syntax" if item.item_id == "two" else None,
        ),
    )
    cd = FunctionStage("CD", put("cd", {"value": 2}))
    iou = FunctionStage("IoU", put("iou", {"value": None}, False))
    geometry = ParallelStages("geometry", [cd, iou], pass_condition=any)
    callbacks = []
    cad = SequenceStages(
        "cad",
        [code, geometry],
        callbacks=[lambda results, name: callbacks.append(name)],
    )
    results = run_stages([cad], filtered_files=original)
    assert list(results) == [
        "cad/code",
        "cad/geometry/CD",
        "cad/geometry/IoU",
        "cad/geometry",
        "cad",
    ]
    all_items, passed, errors = results["cad"]
    assert [item.item_id for item in all_items] == ["one", "two"]
    assert [item.item_id for item in passed] == ["one"]
    assert all_items[0].meta == {"cd": {"value": 2}, "iou": {"value": None}}
    assert {(error.item_id, error.stage) for error in errors.values()} == {
        ("two", "cad/code"),
        ("one", "cad/geometry/IoU"),
    }
    assert callbacks == ["cad"]
    assert original[0].meta == {}


def test_parallel_snapshots_merge_only_changed_fields_and_preserve_origin():
    start = StageItem("id", Path("input"), {"CD": {"value": 1}, "IoU": {"value": 0.1}})
    branches = ParallelStages(
        "both",
        [
            FunctionStage("CD", put("CD", {"value": 2})),
            FunctionStage("IoU", put("IoU", {"value": 0.7})),
        ],
    )
    result = run_stages([branches], filtered_files=[start])["both"]
    assert result[0][0].meta == {"CD": {"value": 2}, "IoU": {"value": 0.7}}
    assert not result[2]


def test_parallel_same_file_different_attempts_are_not_merged():
    inputs = [
        StageItem("first", Path("shared"), {}),
        StageItem("second", Path("shared"), {}),
    ]
    stages = ParallelStages(
        "both", [FunctionStage("x", put("x", 1)), FunctionStage("y", put("y", 2))]
    )
    all_items, passed, _ = run_stages([stages], filtered_files=inputs)["both"]
    assert [item.item_id for item in all_items] == ["first", "second"]
    assert len(passed) == 2


def test_parallel_metadata_conflict_is_explicit_item_failure():
    node = ParallelStages(
        "both",
        [FunctionStage("a", put("value", 1)), FunctionStage("b", put("value", 2))],
    )
    all_items, passed, errors = run_stages(
        [node], filtered_files=[StageItem("x", Path("x"), {})]
    )["both"]
    assert len(all_items) == 1
    assert not passed
    assert "Conflicting branch metadata" in next(iter(errors.values())).message


def test_incoming_transitions_preserve_identity_and_path_selector_order():
    def change(item):
        assert item.path.suffix == ".stl"
        item.path = Path("mesh.stl")
        return True, None

    branch = FunctionStage("mesh", change)
    branch.transition = lambda all_files, filtered, errors: files_transition(
        all_files, filtered, errors, lambda path: path.with_suffix(".stl")
    )
    failed = FunctionStage("bad", put("bad", True, False))
    node = ParallelStages(
        "parallel",
        [failed, branch],
        pass_condition=lambda outcomes: outcomes == [False, True],
    )
    after = FunctionStage("after", lambda item: (item.path == Path("mesh.stl"), None))
    result = run_stages(
        [SequenceStages("cad", [node, after])],
        filtered_files=[StageItem("id", Path("input.py"), {})],
    )
    assert result["cad"][1][0].item_id == "id"
    assert result["cad"][1][0].path == Path("mesh.stl")


def test_selector_failure_and_false_condition_have_distinct_errors():
    def bad_selector(branches):
        return None

    failed = FunctionStage("bad", put("bad", True, False))
    inputs = [StageItem("id", Path("input"), {})]
    result = run_stages([ParallelStages("false", [failed])], filtered_files=inputs)[
        "false"
    ]
    assert len(result[2]) == 1
    result = run_stages(
        [
            ParallelStages(
                "true",
                [failed],
                pass_condition=lambda _: True,
                output_path_selector=bad_selector,
            )
        ],
        filtered_files=inputs,
    )["true"]
    assert len(result[2]) == 2
    assert result[1] == []


def test_cache_policy_validated_and_resolved_by_subtree():
    seen = []
    a = FunctionStage("a", lambda item: (seen.append(a._use_meta) is None, None))
    b = FunctionStage("b", lambda item: (seen.append(b._use_meta) is None, None))
    node = SequenceStages("cad", [a, b])
    inputs = [StageItem("id", Path("input"), {})]
    run_stages([node], filtered_files=inputs, use_meta=["cad/a"])
    assert seen == [True, False]
    seen.clear()
    run_stages([node], filtered_files=inputs, use_meta=["cad"])
    assert seen == [True, True]
    assert a._use_meta is None
    with pytest.raises(ValueError, match="Unknown use_meta"):
        run_stages([node], filtered_files=inputs, use_meta=["typo"])


def test_missing_leaf_result_does_not_drop_attempt():
    class MissingStage(FunctionStage):
        def __call__(self, items):
            return [], [], {}

    result = run_stages(
        [MissingStage("missing", None)],
        filtered_files=[StageItem("id", Path("x"), {"old": 1})],
    )["missing"]
    assert result[0][0].meta == {"old": 1}
    assert result[1] == []
    assert next(iter(result[2].values())).item_id == "id"


def test_transition_and_leaf_errors_keep_both_events_for_same_item():
    stage = FunctionStage("leaf", put("leaf", None, False))

    def transition(all_files, filtered, errors):
        add_error(errors, all_files[0], "", "incoming warning")
        return all_files, filtered, errors

    stage.transition = transition
    result = run_stages([stage], filtered_files=[StageItem("id", Path("input"), {})])[
        "leaf"
    ]
    assert {error.message for error in result[2].values()} == {
        "incoming warning",
        "leaf failed",
    }


def test_one_stage_instance_cannot_receive_two_cache_policies():
    stage = FunctionStage("leaf", put("leaf", 1))
    with pytest.raises(ValueError, match="exactly one tree position"):
        run_stages(
            [SequenceStages("one", [stage]), SequenceStages("two", [stage])],
            filtered_files=[],
        )
