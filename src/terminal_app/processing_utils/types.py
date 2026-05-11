from pathlib import Path
from typing import Any

ErrorsDict = dict[Path, str]
FilesWithMeta = list[tuple[Path, dict[str, Any]]]

PipesResult = dict[
    str,
    tuple[
        FilesWithMeta,
        FilesWithMeta,
        ErrorsDict,
    ],
]
StageResult = tuple[
    FilesWithMeta,
    FilesWithMeta,
    ErrorsDict,
]
