import json
import logging
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, Callable, Literal

import gspread
import pandas as pd
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from gspread_dataframe import set_with_dataframe
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
from tenacity import retry, stop_after_attempt, wait_fixed

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

TColumnConfig = Literal[
    "type",
    "formatting",
]

TFile = Literal["image", "document", "google_document"]


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


FORMATTING_REGISTRY = {
    "width": format_width,
    "decreasing": format_decreasing,
    "increasing": format_increasing,
}


def _get_or_create_folder(drive_service, folder_name: str, parent_id: str) -> str:
    query = f"name = '{folder_name}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = drive_service.files().list(q=query, fields="files(id)").execute()
    files = results.get("files", [])

    if files:
        return files[0]["id"]

    file_metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = (
        drive_service.files()
        .create(body=file_metadata, fields="id", supportsAllDrives=True)
        .execute()
    )
    return folder.get("id")


def _upload_file_to_drive(
    drive_service,
    local_path: str,
    filename: str,
    folder_id: str,
    convert_to_google_doc: bool = False,
    make_subfolders: bool = False,
    replace_existing: bool = False,
) -> tuple[str, str]:

    if make_subfolders and len(Path(filename).parts) > 1:
        parts = Path(filename).parts
        subfolder_name = parts[0]
        subfolder_id = _get_or_create_folder(drive_service, subfolder_name, folder_id)

        return _upload_file_to_drive(
            drive_service,
            local_path,
            os.path.join(*parts[1:]),
            subfolder_id,
            convert_to_google_doc,
            make_subfolders,
            replace_existing,
        )

    query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
    results = (
        drive_service.files().list(q=query, fields="files(id, mimeType)").execute()
    )
    files = results.get("files", [])
    if files:
        file_obj = files[0]
        file_id = file_obj["id"]

        if not replace_existing:
            logger.info(
                f"File {filename} already exists in folder {folder_id}. Skipping upload."
            )
            return file_id, filename

        if file_obj.get("mimeType") == "application/vnd.google-apps.document":
            logger.info(f"Updating existing Google Doc: {filename} ({file_id})")

            mime_type, _ = mimetypes.guess_type(local_path)
            if not mime_type:
                mime_type = "application/octet-stream"

            media = MediaFileUpload(local_path, mimetype=mime_type)

            drive_service.files().update(
                fileId=file_id,
                media_body=media,
                supportsAllDrives=True,
            ).execute()

            return file_id, filename

        logger.info(f"Deleting and replacing file: {filename} ({file_id})")
        drive_service.files().delete(fileId=file_id, supportsAllDrives=True).execute()

    mime_type, _ = mimetypes.guess_type(local_path)
    if not mime_type:
        mime_type = "application/octet-stream"

    file_metadata: dict[str, Any] = {
        "name": filename,
    }

    file_metadata["parents"] = [folder_id]

    if convert_to_google_doc:
        file_metadata["mimeType"] = "application/vnd.google-apps.document"

    media = MediaFileUpload(local_path, mimetype=mime_type)
    uploaded_file = (
        drive_service.files()
        .create(
            body=file_metadata,
            media_body=media,
            fields="id",
            supportsAllDrives=True,
        )
        .execute()
    )
    file_id = uploaded_file.get("id")

    drive_service.permissions().create(
        fileId=file_id,
        body={"role": "reader", "type": "anyone"},
        supportsAllDrives=True,
    ).execute()

    return file_id, filename


def process_image(
    drive_service,
    local_path: str,
    folder_id: str,
    filename_extractor: Callable[[str], str] = lambda x: Path(x).name,
    make_subfolders: bool = False,
    replace_existing: bool = False,
) -> str:
    file_id, _ = _upload_file_to_drive(
        drive_service,
        local_path,
        filename_extractor(local_path),
        folder_id,
        make_subfolders=make_subfolders,
        replace_existing=replace_existing,
    )
    public_link = f"https://drive.google.com/uc?id={file_id}"
    return f'=IMAGE("{public_link}")'


def process_document(
    drive_service,
    local_path: str,
    folder_id: str,
    filename_extractor: Callable[[str], str] = lambda x: Path(x).name,
    make_subfolders: bool = False,
    replace_existing: bool = False,
) -> str:
    file_id, file_name = _upload_file_to_drive(
        drive_service,
        local_path,
        filename_extractor(local_path),
        folder_id,
        make_subfolders=make_subfolders,
        replace_existing=replace_existing,
    )
    view_link = f"https://drive.google.com/open?id={file_id}"
    return f'=HYPERLINK("{view_link}", "{file_name}")'


def process_link(
    drive_service,
    local_path: str,
    filename_extractor: Callable[[str], str] = lambda x: Path(x).name,
) -> str:

    return f'=HYPERLINK("{local_path}", "{filename_extractor(local_path)}")'


def process_google_document(
    drive_service,
    local_path: str,
    folder_id: str,
    filename_extractor: Callable[[str], str] = lambda x: Path(x).stem,
    make_subfolders: bool = False,
    replace_existing: bool = False,
) -> str:
    file_id, file_name = _upload_file_to_drive(
        drive_service,
        local_path,
        filename_extractor(local_path),
        folder_id,
        convert_to_google_doc=True,
        make_subfolders=make_subfolders,
        replace_existing=replace_existing,
    )
    view_link = f"https://drive.google.com/open?id={file_id}"
    return f'=HYPERLINK("{view_link}", "{file_name}")'


FILE_TYPE_REGISTRY = {
    "image": process_image,
    "document": process_document,
    "google_document": process_google_document,
    "link": process_link,
}


def set_with_dataframe_and_images(
    worksheet: gspread.Worksheet,
    df: pd.DataFrame,
    drive_service,
    columns_config: dict[str, dict[TColumnConfig, Any]] | None = None,
    row: int = 1,
    col: int = 1,
    include_index: bool = False,
    include_column_header: bool = True,
    resize: bool = False,
):

    if columns_config:
        for col_name in df.columns:
            col_config = columns_config.get(col_name, {})
            column_type_config = col_config.get("type", {})

            column_type_name = column_type_config.get("name", None)
            kwargs = column_type_config.get("kwargs", {})

            if column_type_name is None:
                continue

            handler = FILE_TYPE_REGISTRY.get(column_type_name)

            if handler:
                for idx in df.index:
                    local_path = df.at[idx, col_name]

                    if isinstance(local_path, str):
                        try:
                            df.at[idx, col_name] = handler(
                                drive_service, local_path, **kwargs
                            )
                        except Exception as e:
                            logger.error(f"Failed to upload {local_path}: {e}")
                            df.at[idx, col_name] = "Upload Error"
                    else:
                        df.at[idx, col_name] = ""

    set_with_dataframe(
        worksheet=worksheet,
        dataframe=df,
        include_index=include_index,
        include_column_header=include_column_header,
        row=row,
        col=col,
        resize=resize,
    )


def get_credentials(creds_path: Path | str, scopes: list[str]):

    creds_path = Path(creds_path)
    if not creds_path.exists():
        raise FileNotFoundError(f"Credentials file not found: {creds_path}")

    with open(creds_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = {}

    # 1. Service Account
    if data.get("type") == "service_account":
        logger.info("Using Service Account credentials")
        return ServiceAccountCredentials.from_service_account_file(
            creds_path, scopes=scopes
        )

    # 2. OAuth 2.0 Client ID (User)
    logger.info("Using OAuth 2.0 User credentials")
    token_path = creds_path.parent / f"{creds_path.stem}_token.json"
    creds = None

    if token_path.exists():
        creds = UserCredentials.from_authorized_user_file(str(token_path), scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired token")
            creds.refresh(Request())
        else:
            logger.info("Starting OAuth flow (check browser)...")
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), scopes)
            creds = flow.run_local_server(port=0)

        with open(token_path, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return creds


def send_to_google(
    creds_path: Path | str,
    spreadsheet_id: str,
    results: dict[str, pd.DataFrame] | dict[str, list[dict[str, Any]]],
    sheet_config: dict[str, Any] | None = None,
    columns_config: dict[str, dict[TColumnConfig, Any]] | None = None,
    round: int | None = None,
    batch_size: int = 10,
    delay_seconds: int = 60,
):

    if columns_config is None:
        columns_config = {}

    logger.info(f"Start collecting eval_results from {len(results)} files")
    dfs = {
        k: (v if isinstance(v, pd.DataFrame) else pd.DataFrame(v))
        for k, v in results.items()
    }
    if round is not None:
        dfs = {k: df.round(round) for k, df in dfs.items()}

    dfs = {
        k: (df if isinstance(df.index, pd.RangeIndex) else df.reset_index())
        for k, df in dfs.items()
    }
    logger.info(f"End collecting eval_results from {len(results)} files")

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    credentials = get_credentials(creds_path, SCOPES)

    gc = gspread.authorize(credentials)
    drive_service = build("drive", "v3", credentials=credentials)

    try:
        spreadsheet = gc.open_by_key(spreadsheet_id)
        logger.info(f"Find spreadsheet {spreadsheet_id}")
    except gspread.SpreadsheetNotFound:
        spreadsheet = gc.create("Validation Metrics")
        logger.info(f"Create spreadsheet {spreadsheet_id}")

    for val_set_name, df in dfs.items():
        total_rows = len(df)
        if total_rows == 0:
            continue

        num_batches = (total_rows + batch_size - 1) // batch_size
        logger.info(
            f"Start processing {val_set_name} | length={total_rows} | batch_size={batch_size} | num_batches={num_batches}"
        )
        try:
            worksheet = spreadsheet.worksheet(val_set_name)
            worksheet.clear()
            logger.info(f"Find worksheet {val_set_name}")
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=val_set_name, rows=100, cols=20)
            logger.info(f"Create worksheet {val_set_name}")

        for batch_num in range(num_batches):
            start_row = batch_num * batch_size
            end_row = min((batch_num + 1) * batch_size, total_rows)
            batch_df = df.iloc[start_row:end_row]

            start_cell = 1 if batch_num == 0 else (batch_num * batch_size + 2)

            @retry(wait=wait_fixed(delay_seconds), stop=stop_after_attempt(3))
            def upload_batch():

                set_with_dataframe_and_images(
                    worksheet=worksheet,
                    df=batch_df.copy(),
                    drive_service=drive_service,
                    columns_config=columns_config,
                    row=start_cell,
                    col=1,
                    include_index=False,
                    include_column_header=True if batch_num == 0 else False,
                    resize=(batch_num == 0),
                )

            upload_batch()
            logger.info(
                f"Send {batch_num+1}/{num_batches} | rows {start_row+1}-{end_row}"
            )

            if batch_num == num_batches - 1:
                logger.info("✨ Start formatting...")

                rules = get_conditional_format_rules(worksheet)
                rules.clear()
                worksheet.columns_auto_resize(0, len(df.columns))

                for col_idx, col_name in enumerate(df.columns, start=1):
                    col_letter = gspread.utils.rowcol_to_a1(1, col_idx)[:-1]
                    cell_range = f"{col_letter}2:{col_letter}{total_rows+1}"

                    col_config = columns_config.get(col_name, {})
                    formatting_configs = col_config.get("formatting", [])

                    for formatting_config in formatting_configs:
                        fmt_name = formatting_config.get("name", "")
                        kwargs = formatting_config.get("kwargs", {})

                        if fmt_name in FORMATTING_REGISTRY:
                            rule_func = FORMATTING_REGISTRY[fmt_name]
                            rule = rule_func(cell_range, worksheet, **kwargs)
                            if rule:
                                rules.append(rule)

                rules.save()

                if sheet_config and "height" in sheet_config:
                    set_row_heights(
                        worksheet, [(f"2:{total_rows + 1}", sheet_config["height"])]
                    )
                else:
                    set_row_heights(worksheet, [(f"2:{total_rows + 1}", 21)])

                last_col_idx = len(df.columns)
                last_col_letter = gspread.utils.rowcol_to_a1(1, last_col_idx)[:-1]

                format_cell_range(
                    worksheet,
                    f"A2:{last_col_letter}{total_rows+1}",
                    CellFormat(verticalAlignment="MIDDLE", horizontalAlignment="LEFT"),
                )
                format_cell_range(
                    worksheet, f"A2:C{total_rows+1}", CellFormat(wrapStrategy="WRAP")
                )

                logger.info("✅ End formatting")

            if batch_num < num_batches - 1:
                logger.info(f"⏳ Sleep {delay_seconds} before next batch processing")
                time.sleep(delay_seconds)

        logger.info(f"✅ Successfully processed {val_set_name}")
        logger.info(f"⏳ Sleep {delay_seconds} before next val_set")
        time.sleep(delay_seconds)
