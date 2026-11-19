"""Batch report upload, with compatibility imports for the original module API."""

import time
from pathlib import Path
from typing import Any

import gspread
import pandas as pd
from googleapiclient.discovery import build
from tenacity import Retrying, stop_after_attempt, wait_fixed

from terminal_app.google_sheets.credentials import get_credentials as get_credentials
from terminal_app.google_sheets.dataframe import (
    set_with_dataframe_and_images as set_with_dataframe_and_images,
)
from terminal_app.google_sheets.drive import (
    FILE_TYPE_REGISTRY as FILE_TYPE_REGISTRY,
)
from terminal_app.google_sheets.drive import (
    _get_or_create_folder as _get_or_create_folder,
)
from terminal_app.google_sheets.drive import (
    _upload_file_to_drive as _upload_file_to_drive,
)
from terminal_app.google_sheets.drive import (
    process_document as process_document,
)
from terminal_app.google_sheets.drive import (
    process_google_document as process_google_document,
)
from terminal_app.google_sheets.drive import (
    process_image as process_image,
)
from terminal_app.google_sheets.drive import (
    process_link as process_link,
)
from terminal_app.google_sheets.formatting import (
    DUSTY_RED as DUSTY_RED,
)
from terminal_app.google_sheets.formatting import (
    FORMATTING_REGISTRY as FORMATTING_REGISTRY,
)
from terminal_app.google_sheets.formatting import (
    SAGE_GREEN as SAGE_GREEN,
)
from terminal_app.google_sheets.formatting import (
    WARM_SAND as WARM_SAND,
)
from terminal_app.google_sheets.formatting import (
    format_decreasing as format_decreasing,
)
from terminal_app.google_sheets.formatting import (
    format_increasing as format_increasing,
)
from terminal_app.google_sheets.formatting import (
    format_width as format_width,
)
from terminal_app.google_sheets.formatting import (
    format_worksheet,
)
from terminal_app.google_sheets.logging import formatter as formatter
from terminal_app.google_sheets.logging import logger as logger
from terminal_app.google_sheets.logging import stream_handler as stream_handler
from terminal_app.google_sheets.types import TColumnConfig as TColumnConfig
from terminal_app.google_sheets.types import TFile as TFile


def _dataframes(
    results: dict[str, pd.DataFrame] | dict[str, list[dict[str, Any]]],
    decimals: int | None,
) -> dict[str, pd.DataFrame]:
    frames = {
        key: (value if isinstance(value, pd.DataFrame) else pd.DataFrame(value))
        for key, value in results.items()
    }
    if decimals is not None:
        frames = {key: frame.round(decimals) for key, frame in frames.items()}
    return {
        key: (frame if isinstance(frame.index, pd.RangeIndex) else frame.reset_index())
        for key, frame in frames.items()
    }


def _worksheet(spreadsheet: gspread.Spreadsheet, name: str) -> gspread.Worksheet:
    try:
        worksheet = spreadsheet.worksheet(name)
        worksheet.clear()
        logger.info("Find worksheet %s", name)
        return worksheet
    except gspread.WorksheetNotFound:
        logger.info("Create worksheet %s", name)
        return spreadsheet.add_worksheet(title=name, rows=100, cols=20)


def _upload_batch(
    worksheet: gspread.Worksheet,
    frame: pd.DataFrame,
    drive_service: Any,
    columns_config: dict[str, dict[TColumnConfig, Any]],
    batch_num: int,
    batch_size: int,
) -> None:
    # Each retry starts from fresh cells, so already generated formulas are not
    # accidentally treated as local file paths on the next upload attempt.
    start_row = batch_num * batch_size
    end_row = min(start_row + batch_size, len(frame))
    set_with_dataframe_and_images(
        worksheet=worksheet,
        df=frame.iloc[start_row:end_row].copy(),
        drive_service=drive_service,
        columns_config=columns_config,
        row=1 if batch_num == 0 else start_row + 2,
        col=1,
        include_index=False,
        include_column_header=batch_num == 0,
        resize=batch_num == 0,
    )


def _send_frame(
    worksheet: gspread.Worksheet,
    frame: pd.DataFrame,
    drive_service: Any,
    columns_config: dict[str, dict[TColumnConfig, Any]],
    sheet_config: dict[str, Any] | None,
    batch_size: int,
    delay_seconds: int,
) -> None:
    num_batches = (len(frame) + batch_size - 1) // batch_size
    for batch_num in range(num_batches):
        Retrying(wait=wait_fixed(delay_seconds), stop=stop_after_attempt(3))(
            _upload_batch,
            worksheet,
            frame,
            drive_service,
            columns_config,
            batch_num,
            batch_size,
        )
        logger.info("Send %s/%s", batch_num + 1, num_batches)
        if batch_num == num_batches - 1:
            logger.info("Start formatting")
            format_worksheet(worksheet, frame, columns_config, sheet_config)
            logger.info("End formatting")
        else:
            logger.info("Sleep %s before next batch processing", delay_seconds)
            time.sleep(delay_seconds)


def send_to_google(
    creds_path: Path | str,
    spreadsheet_id: str,
    results: dict[str, pd.DataFrame] | dict[str, list[dict[str, Any]]],
    sheet_config: dict[str, Any] | None = None,
    columns_config: dict[str, dict[TColumnConfig, Any]] | None = None,
    round: int | None = None,
    batch_size: int = 10,
    delay_seconds: int = 60,
) -> None:
    if columns_config is None:
        columns_config = {}
    logger.info("Start collecting eval_results from %s files", len(results))
    frames = _dataframes(results, round)
    logger.info("End collecting eval_results from %s files", len(results))
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = get_credentials(creds_path, scopes)
    client = gspread.authorize(credentials)
    drive_service = build("drive", "v3", credentials=credentials)
    try:
        spreadsheet = client.open_by_key(spreadsheet_id)
        logger.info("Find spreadsheet %s", spreadsheet_id)
    except gspread.SpreadsheetNotFound:
        spreadsheet = client.create("Validation Metrics")
        logger.info("Create spreadsheet %s", spreadsheet_id)
    for name, frame in frames.items():
        if len(frame) == 0:
            continue
        logger.info(
            "Start processing %s | length=%s | batch_size=%s",
            name,
            len(frame),
            batch_size,
        )
        worksheet = _worksheet(spreadsheet, name)
        _send_frame(
            worksheet,
            frame,
            drive_service,
            columns_config,
            sheet_config,
            batch_size,
            delay_seconds,
        )
        logger.info("Successfully processed %s", name)
        logger.info("Sleep %s before next val_set", delay_seconds)
        time.sleep(delay_seconds)
