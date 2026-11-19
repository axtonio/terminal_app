"""Formatting rules and worksheet presentation."""

from typing import Any, Callable

import gspread
import pandas as pd
from gspread.utils import rowcol_to_a1
from gspread_formatting import (
    CellFormat,
    Color,
    ConditionalFormatRule,
    GradientRule,
    GridRange,
    InterpolationPoint,
    format_cell_range,
    get_conditional_format_rules,
    set_column_width,
    set_row_heights,
)

from terminal_app.google_sheets.types import TColumnConfig

DUSTY_RED = Color(0.8, 0.4, 0.4)
WARM_SAND = Color(0.9, 0.8, 0.5)
SAGE_GREEN = Color(0.4, 0.7, 0.5)


def format_decreasing(cell_range: str, worksheet: gspread.Worksheet):
    return ConditionalFormatRule(
        ranges=[GridRange.from_a1_range(cell_range, worksheet)],
        gradientRule=GradientRule(
            minpoint=InterpolationPoint(color=SAGE_GREEN, type="MIN"),
            midpoint=InterpolationPoint(color=WARM_SAND, type="PERCENTILE", value="50"),
            maxpoint=InterpolationPoint(color=DUSTY_RED, type="MAX"),
        ),
    )


def format_increasing(cell_range: str, worksheet: gspread.Worksheet):
    return ConditionalFormatRule(
        ranges=[GridRange.from_a1_range(cell_range, worksheet)],
        gradientRule=GradientRule(
            minpoint=InterpolationPoint(color=DUSTY_RED, type="MIN"),
            midpoint=InterpolationPoint(color=WARM_SAND, type="PERCENTILE", value="50"),
            maxpoint=InterpolationPoint(color=SAGE_GREEN, type="MAX"),
        ),
    )


def format_width(cell_range: str, worksheet: gspread.Worksheet, value: int):

    if value:
        col_letter = cell_range.split(":")[0]
        col_letter = "".join(filter(str.isalpha, col_letter))
        set_column_width(worksheet, col_letter, value)


FORMATTING_REGISTRY: dict[str, Callable[..., Any]] = {
    "width": format_width,
    "decreasing": format_decreasing,
    "increasing": format_increasing,
}


def format_worksheet(
    worksheet: gspread.Worksheet,
    frame: pd.DataFrame,
    columns_config: dict[str, dict[TColumnConfig, Any]],
    sheet_config: dict[str, Any] | None,
) -> None:
    total_rows = len(frame)
    rules = get_conditional_format_rules(worksheet)
    rules.clear()
    worksheet.columns_auto_resize(0, len(frame.columns))
    for col_idx, col_name in enumerate(frame.columns, start=1):
        col_letter = rowcol_to_a1(1, col_idx)[:-1]
        cell_range = f"{col_letter}2:{col_letter}{total_rows + 1}"
        for config in columns_config.get(col_name, {}).get("formatting", []):
            _append_format_rule(rules, config, cell_range, worksheet)
    rules.save()
    height = sheet_config.get("height", 21) if sheet_config else 21
    set_row_heights(worksheet, [(f"2:{total_rows + 1}", height)])
    last_col_letter = rowcol_to_a1(1, len(frame.columns))[:-1]
    format_cell_range(
        worksheet,
        f"A2:{last_col_letter}{total_rows + 1}",
        CellFormat(verticalAlignment="MIDDLE", horizontalAlignment="LEFT"),
    )
    format_cell_range(
        worksheet, f"A2:C{total_rows + 1}", CellFormat(wrapStrategy="WRAP")
    )


def _append_format_rule(
    rules: Any, config: dict[str, Any], cell_range: str, worksheet: gspread.Worksheet
) -> None:
    handler = FORMATTING_REGISTRY.get(config.get("name", ""))
    if handler is None:
        return
    rule = handler(cell_range, worksheet, **config.get("kwargs", {}))
    if rule:
        rules.append(rule)
