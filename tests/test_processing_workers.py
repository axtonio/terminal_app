import os
import queue
import time
from pathlib import Path

import pytest

from terminal_app.processing_utils.core import process_files
from terminal_app.processing_utils.types import StageItem


def raise_empty(file, meta, device):
    if file == "bad":
        meta.clear()
        raise queue.Empty("task raised Empty")
    return Path(file).with_suffix(".out"), meta, None, True


def exit_worker(file, meta, device):
    if file == "bad":
        os._exit(1)
    return file, meta, None, True


def hang_worker(file, meta, device):
    time.sleep(10)
    return file, meta, None, True


@pytest.mark.parametrize("safety", [False, True])
def test_task_empty_is_failure_and_worker_processes_next_item(safety):
    inputs = [
        StageItem("bad-id", Path("bad"), {"incoming": 1}),
        StageItem("good-id", Path("good"), {}),
    ]
    all_items, passed, errors = process_files(
        inputs,
        raise_empty,
        "test",
        max_workers=1,
        safety=safety,
        start_method="fork",
        task_timeout=1,
        process_timeout=2,
    )
    assert [item.item_id for item in all_items] == ["bad-id", "good-id"]
    assert all_items[0].meta == {"incoming": 1}
    assert [item.item_id for item in passed] == ["good-id"]
    assert passed[0].path == Path("good.out")
    assert "Empty" in next(iter(errors.values())).message


@pytest.mark.parametrize("safety", [False, True])
def test_process_death_accounts_for_every_input(safety):
    inputs = [
        StageItem("bad-id", Path("bad"), {"incoming": 1}),
        StageItem("good-id", Path("good"), {}),
    ]
    all_items, passed, errors = process_files(
        inputs,
        exit_worker,
        "test",
        max_workers=1,
        safety=safety,
        start_method="fork",
        task_timeout=1,
        process_timeout=1,
    )
    assert len(all_items) == 2
    assert {item.item_id for item in passed} | {
        error.item_id for error in errors.values()
    } == {"bad-id", "good-id"}
    assert any(error.item_id == "bad-id" for error in errors.values())


@pytest.mark.parametrize("safety", [False, True])
def test_task_timeout_is_accounted_for(safety):
    started = time.monotonic()
    result = process_files(
        [StageItem("id", Path("input"), {})],
        hang_worker,
        "test",
        max_workers=1,
        safety=safety,
        start_method="fork",
        task_timeout=1,
        process_timeout=0.2,
    )
    assert time.monotonic() - started < 5
    assert len(result[0]) == len(result[2]) == 1
    assert result[1] == []


def test_spawn_preserves_identity():
    result = process_files(
        [StageItem("id", Path("good"), {})],
        raise_empty,
        "test",
        max_workers=1,
        start_method="spawn",
        task_timeout=1,
        process_timeout=5,
    )
    assert result[1][0].item_id == "id"
