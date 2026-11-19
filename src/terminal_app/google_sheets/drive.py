"""Drive file uploads and spreadsheet hyperlink generation."""

import mimetypes
import os
from pathlib import Path
from typing import Any, Callable

from googleapiclient.http import MediaFileUpload

from terminal_app.google_sheets.logging import logger


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

            media = _media_file(local_path)

            drive_service.files().update(
                fileId=file_id,
                media_body=media,
                supportsAllDrives=True,
            ).execute()

            return file_id, filename

        logger.info(f"Deleting and replacing file: {filename} ({file_id})")
        drive_service.files().delete(fileId=file_id, supportsAllDrives=True).execute()

    file_metadata: dict[str, Any] = {
        "name": filename,
    }

    file_metadata["parents"] = [folder_id]

    if convert_to_google_doc:
        file_metadata["mimeType"] = "application/vnd.google-apps.document"

    media = _media_file(local_path)
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


def _media_file(local_path: str) -> MediaFileUpload:
    mime_type, _ = mimetypes.guess_type(local_path)
    return MediaFileUpload(local_path, mimetype=mime_type or "application/octet-stream")


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


FILE_TYPE_REGISTRY: dict[str, Callable[..., str]] = {
    "image": process_image,
    "document": process_document,
    "google_document": process_google_document,
    "link": process_link,
}
