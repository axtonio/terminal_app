"""Convert configured file cells before writing dataframe batches."""

from typing import Any, Callable

import gspread
import pandas as pd
from gspread_dataframe import set_with_dataframe

from terminal_app.google_sheets.drive import FILE_TYPE_REGISTRY
from terminal_app.google_sheets.logging import logger
from terminal_app.google_sheets.types import TColumnConfig


def _file_cell(
    handler: Callable[..., str], drive_service: Any, local_path: object, kwargs: dict
) -> str:
    if not isinstance(local_path, str):
        return ""
    try:
        return handler(drive_service, local_path, **kwargs)
    except Exception as error:
        logger.error("Failed to upload %s: %s", local_path, error)
        return "Upload Error"


def _convert_columns(
    frame: pd.DataFrame,
    drive_service: Any,
    columns_config: dict[str, dict[TColumnConfig, Any]],
) -> None:
    for col_name in frame.columns:
        type_config = columns_config.get(col_name, {}).get("type", {})
        handler = FILE_TYPE_REGISTRY.get(type_config.get("name"))
        if handler is None:
            continue
        kwargs = type_config.get("kwargs", {})
        for index in frame.index:
            frame.at[index, col_name] = _file_cell(
                handler, drive_service, frame.at[index, col_name], kwargs
            )


def set_with_dataframe_and_images(
    worksheet: gspread.Worksheet,
    df: pd.DataFrame,
    drive_service: Any,
    columns_config: dict[str, dict[TColumnConfig, Any]] | None = None,
    row: int = 1,
    col: int = 1,
    include_index: bool = False,
    include_column_header: bool = True,
    resize: bool = False,
) -> None:
    if columns_config:
        _convert_columns(df, drive_service, columns_config)
    set_with_dataframe(
        worksheet=worksheet,
        dataframe=df,
        include_index=include_index,
        include_column_header=include_column_header,
        row=row,
        col=col,
        resize=resize,
    )
