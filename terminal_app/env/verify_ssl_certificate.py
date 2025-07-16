__all__ = ["verify_ssl_certs"]

import os
import certifi
import requests
from pathlib import Path
from typing import Callable
from terminal_app.logging import TERMINAL_APP_LOGGER


def verify_ssl_certs(
    url: str,
    cert_dir: Path | Callable[[], Path] = lambda: Path(
        os.environ.get("CERTS_DIR", "certs")
    ),
):

    if isinstance(cert_dir, Callable):
        cert_dir = cert_dir()

    for attempt in range(2):
        try:
            requests.get(url=url, verify=True)
        except requests.exceptions.SSLError:
            assert cert_dir.exists(), "The folder must exist"
            assert cert_dir.is_dir(), "The certificates folder should be a directory"
            if attempt == 0:

                cert_file = certifi.where()

                for file in cert_dir.iterdir():
                    if file.is_file():
                        if file.suffix == ".pem":
                            with open(file, "rb") as infile:
                                custom_cert = infile.read()
                            with open(cert_file, "ab") as outfile:
                                outfile.write(custom_cert)
                            TERMINAL_APP_LOGGER.info(
                                f"Added the {file.name} to the certificates"
                            )

                continue

            TERMINAL_APP_LOGGER.warning("The certificates were not installed")

    TERMINAL_APP_LOGGER.info("Certificates found...")
