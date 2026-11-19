from abc import ABC, abstractmethod
from typing import Sequence

from .types import ErrorsDict, FilesWithMeta, PipesResult, StageResult


class Callback(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def __call__(self, stages_result: PipesResult, stage_name: str | None) -> None:
        pass


class Stage(ABC):
    callbacks: Sequence[Callback] = ()
    _use_meta: bool | None = None

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def __call__(self, filtered_files: FilesWithMeta | None) -> StageResult:
        pass

    def transition(
        self,
        all_files: FilesWithMeta,
        filtered_files: FilesWithMeta,
        errors: ErrorsDict,
    ) -> StageResult:
        """Transform this node's incoming files before it executes."""
        return all_files, filtered_files, errors
