"""Google authentication kept separate from report formatting and uploads."""

import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow

from terminal_app.google_sheets.logging import logger


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
