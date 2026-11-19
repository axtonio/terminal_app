from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4


@dataclass
class StageItem:
    """One attempt, whose identity survives file changes and parallel branches.

    Pair iteration/indexing supports existing path/meta consumers. Producers must
    preserve ``item_id`` when they change a path or metadata.
    """

    item_id: str
    path: Path
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.path = Path(self.path)

    def __iter__(self) -> Iterator[Any]:
        return iter((self.path, self.meta))

    def __getitem__(self, index: int):
        return (self.path, self.meta)[index]


@dataclass(frozen=True)
class StageError:
    item_id: str
    path: Path
    stage: str
    message: str


ErrorsDict = dict[str, StageError]
FilesWithMeta = list[StageItem]
StageResult = tuple[FilesWithMeta, FilesWithMeta, ErrorsDict]
PipesResult = dict[str, StageResult]


@dataclass(frozen=True)
class BranchResult:
    stage_name: str
    item: StageItem
    passed: bool
    errors: ErrorsDict


def _legacy_item(value, available: dict[Path, list[str]], require_identity: bool):
    path, meta = value
    ids = available.get(Path(path), [])
    if require_identity and not ids:
        raise ValueError("A changed output path must retain its StageItem.item_id")
    if require_identity and len(ids) != 1:
        raise ValueError("An ambiguous output path must retain its StageItem.item_id")
    return StageItem(ids.pop(0) if ids else uuid4().hex, Path(path), meta)


def normalize_items(files, source: FilesWithMeta | None = None) -> FilesWithMeta:
    """Accept legacy path/meta pairs only when their identity is unambiguous."""
    available: dict[Path, list[str]] = {}
    for item in source or []:
        available.setdefault(item.path, []).append(item.item_id)
    result = []
    for value in files:
        if isinstance(value, StageItem):
            item = value
        else:
            item = _legacy_item(value, available, source is not None)
        result.append(item)
    ids = [item.item_id for item in result]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate item_id in stage input or result")
    return result


def add_error(errors: ErrorsDict, item: StageItem, stage: str, message: str):
    key = f"{stage}:{item.item_id}"
    suffix = 1
    while key in errors:
        suffix += 1
        key = f"{stage}:{item.item_id}:{suffix}"
    errors[key] = StageError(item.item_id, item.path, stage, message)
