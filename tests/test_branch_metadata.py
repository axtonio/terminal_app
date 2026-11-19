import math
from copy import deepcopy
from pathlib import Path

import pytest

from terminal_app.processing_utils.branch_metadata import merge_branch_metadata
from terminal_app.processing_utils.types import BranchResult, StageItem


def branch(name, metadata):
    return BranchResult(name, StageItem("id", Path("input"), metadata), True, {})


def test_independent_nested_changes_preserve_null_deletion_and_snapshots():
    original = {
        "nullable": 1,
        "removed": None,
        "nested": {"old": 1, "kept": 2},
    }
    left = deepcopy(original)
    left["nullable"] = None
    del left["removed"]
    right = deepcopy(original)
    del right["nested"]["old"]
    right["nested"]["new"] = None
    branches = [branch("left", left), branch("right", right)]
    expected = {"nullable": None, "nested": {"kept": 2, "new": None}}
    assert merge_branch_metadata(original, branches) == expected
    merged = merge_branch_metadata(original, list(reversed(branches)))
    assert merged == expected
    merged["nested"]["kept"] = 100
    assert original["nested"] == {"old": 1, "kept": 2}
    assert left["nested"] == {"old": 1, "kept": 2}
    assert right["nested"] == {"kept": 2, "new": None}


def test_identical_deletions_are_compatible():
    assert (
        merge_branch_metadata(
            {"removed": None}, [branch("left", {}), branch("right", {})]
        )
        == {}
    )


def test_deletion_and_explicit_null_conflict():
    with pytest.raises(ValueError, match="Conflicting branch metadata"):
        merge_branch_metadata(
            {"value": 1}, [branch("delete", {}), branch("null", {"value": None})]
        )


@pytest.mark.parametrize("replacement", [None, {}, []])
def test_parent_replacement_conflicts_with_nested_edit(replacement):
    original = {"nested": {"value": 1}}
    branches = [
        branch("replace", {"nested": replacement}),
        branch("edit", {"nested": {"value": 2}}),
    ]
    for ordered in (branches, list(reversed(branches))):
        with pytest.raises(ValueError, match="Conflicting branch metadata"):
            merge_branch_metadata(original, ordered)


def test_nan_values_do_not_create_false_conflicts_in_unchanged_metadata():
    original = {"nested": {"sample": [float("nan"), 1]}}
    left = deepcopy(original)
    left["left"] = 1
    left["new"] = float("nan")
    right = deepcopy(original)
    right["right"] = 2
    right["new"] = float("nan")
    merged = merge_branch_metadata(
        original, [branch("left", left), branch("right", right)]
    )
    assert merged["left"] == 1
    assert merged["right"] == 2
    assert math.isnan(merged["new"])
    assert math.isnan(merged["nested"]["sample"][0])
