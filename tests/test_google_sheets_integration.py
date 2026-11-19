"""Local integration checks; Google requests and upload adapters are mocked."""

from importlib import import_module
from io import StringIO
from unittest.mock import Mock

import pytest

pd = pytest.importorskip("pandas")
for dependency in (
    "gspread",
    "google.auth.transport.requests",
    "google.oauth2.credentials",
    "google.oauth2.service_account",
    "google_auth_oauthlib.flow",
    "googleapiclient.discovery",
    "googleapiclient.http",
    "gspread_dataframe",
    "gspread_formatting",
    "tenacity",
):
    pytest.importorskip(dependency)

dataframe_module = import_module("terminal_app.google_sheets.dataframe")
drive_module = import_module("terminal_app.google_sheets.drive")
reports = import_module("terminal_app.google_sheets.send_metrics")


def test_batches_keep_offsets_headers_and_input_data(monkeypatch):
    client = Mock()
    spreadsheet = client.open_by_key.return_value
    worksheet = spreadsheet.worksheet.return_value
    monkeypatch.setattr(reports, "get_credentials", Mock(return_value=object()))
    monkeypatch.setattr(reports.gspread, "authorize", Mock(return_value=client))
    monkeypatch.setattr(reports, "build", Mock(return_value=object()))
    upload = Mock()
    formatting = Mock()
    sleep = Mock()
    monkeypatch.setattr(reports, "set_with_dataframe_and_images", upload)
    monkeypatch.setattr(reports, "format_worksheet", formatting)
    monkeypatch.setattr(reports.time, "sleep", sleep)
    frame = pd.DataFrame({"CD": [1.123, 2.234, 3.345]})

    reports.send_to_google(
        "unused.json",
        "sheet",
        {"results": frame},
        round=2,
        batch_size=2,
        delay_seconds=0,
    )

    first, second = upload.call_args_list
    assert first.kwargs["row"] == 1
    assert second.kwargs["row"] == 4
    assert first.kwargs["include_column_header"] is True
    assert second.kwargs["include_column_header"] is False
    assert first.kwargs["resize"] is True
    assert second.kwargs["resize"] is False
    assert first.kwargs["df"]["CD"].tolist() == [1.12, 2.23]
    assert second.kwargs["df"]["CD"].tolist() == [3.34]
    assert frame["CD"].tolist() == [1.123, 2.234, 3.345]
    worksheet.clear.assert_called_once_with()
    formatting.assert_called_once()
    assert sleep.call_count == 2


def test_retry_uses_original_paths_after_upload_mutates_dataframe(monkeypatch):
    attempted = []

    def upload(**kwargs):
        frame = kwargs["df"]
        attempted.append(frame.at[0, "image"])
        frame.at[0, "image"] = '=IMAGE("already uploaded")'
        if len(attempted) == 1:
            raise RuntimeError("temporary worksheet failure")

    monkeypatch.setattr(reports, "set_with_dataframe_and_images", upload)
    monkeypatch.setattr(reports, "format_worksheet", Mock())
    frame = pd.DataFrame({"image": ["result.png"]})
    reports._send_frame(Mock(), frame, Mock(), {}, None, 1, 0)
    assert attempted == ["result.png", "result.png"]
    assert frame.at[0, "image"] == "result.png"


def test_file_cell_conversion_preserves_error_and_empty_behavior(monkeypatch):
    calls = []

    def process(_service, path, *, folder_id):
        calls.append((path, folder_id))
        if path == "failed.png":
            raise ValueError("missing file")
        return '=IMAGE("public-url")'

    monkeypatch.setitem(dataframe_module.FILE_TYPE_REGISTRY, "image", process)
    upload = Mock()
    monkeypatch.setattr(dataframe_module, "set_with_dataframe", upload)
    frame = pd.DataFrame({"image": ["ok.png", "failed.png", None], "CD": [0, 1, 2]})
    dataframe_module.set_with_dataframe_and_images(
        Mock(),
        frame,
        Mock(),
        {"image": {"type": {"name": "image", "kwargs": {"folder_id": "folder"}}}},
    )
    assert frame["image"].tolist() == ['=IMAGE("public-url")', "Upload Error", ""]
    assert frame["CD"].tolist() == [0, 1, 2]
    assert calls == [("ok.png", "folder"), ("failed.png", "folder")]
    upload.assert_called_once()


@pytest.mark.parametrize("replace", [False, True])
def test_existing_google_document_is_skipped_or_updated(monkeypatch, replace):
    service = Mock()
    files = service.files.return_value
    files.list.return_value.execute.return_value = {
        "files": [
            {"id": "existing", "mimeType": "application/vnd.google-apps.document"}
        ]
    }
    media = Mock()
    monkeypatch.setattr(drive_module, "MediaFileUpload", media)
    assert reports._upload_file_to_drive(
        service, "local.txt", "report", "folder", replace_existing=replace
    ) == ("existing", "report")
    assert files.update.call_count == int(replace)
    files.delete.assert_not_called()
    files.create.assert_not_called()
    service.permissions.assert_not_called()


def test_original_public_google_helpers_still_resolve():
    assert reports.process_image is drive_module.process_image
    assert reports.process_document is drive_module.process_document
    assert reports.process_google_document is drive_module.process_google_document
    assert reports.process_link(Mock(), "https://example.test/report") == (
        '=HYPERLINK("https://example.test/report", "report")'
    )
    assert reports.FILE_TYPE_REGISTRY is drive_module.FILE_TYPE_REGISTRY


def test_split_modules_emit_credentials_logs_with_original_configuration(
    monkeypatch, tmp_path
):
    credentials_module = import_module("terminal_app.google_sheets.credentials")
    logging_module = import_module("terminal_app.google_sheets.logging")
    destination = StringIO()
    monkeypatch.setattr(reports.stream_handler, "stream", destination)
    credential_factory = Mock(return_value=object())
    monkeypatch.setattr(
        credentials_module.ServiceAccountCredentials,
        "from_service_account_file",
        credential_factory,
    )
    credentials = tmp_path / "service.json"
    credentials.write_text('{"type": "service_account"}')

    assert (
        reports.get_credentials(credentials, ["test-scope"])
        is credential_factory.return_value
    )

    assert credentials_module.logger is reports.logger
    assert drive_module.logger is reports.logger
    assert dataframe_module.logger is reports.logger
    assert logging_module.logger is reports.logger
    assert logging_module.formatter is reports.formatter
    assert reports.stream_handler.formatter is reports.formatter
    assert reports.logger.level == 20
    assert (
        sum(handler is reports.stream_handler for handler in reports.logger.handlers)
        == 1
    )
    output = destination.getvalue()
    assert output.count("Using Service Account credentials") == 1
    assert (
        " - terminal_app.google_sheets.send_metrics - INFO - Using Service Account credentials"
        in output
    )
