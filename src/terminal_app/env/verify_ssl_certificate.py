import os
from collections.abc import Callable
from pathlib import Path

import certifi
import requests

from terminal_app.logging.logging import TERMINAL_APP_LOGGER


def _install_certificates(cert_dir: Path) -> None:
    cert_file = Path(certifi.where())
    for certificate in cert_dir.iterdir():
        if certificate.is_file() and certificate.suffix == ".pem":
            with cert_file.open("ab") as output:
                output.write(certificate.read_bytes())
            TERMINAL_APP_LOGGER.info(
                "Added the %s to the certificates", certificate.name
            )


def verify_ssl_certs(
    url: str,
    cert_dir: Path | Callable[[], Path] = lambda: Path(
        os.environ.get("CERTS_DIR", "certs")
    ),
) -> None:
    directory = cert_dir() if callable(cert_dir) else cert_dir
    for attempt in range(2):
        try:
            requests.get(url=url, verify=True)
        except requests.exceptions.SSLError:
            assert directory.exists(), "The folder must exist"
            assert directory.is_dir(), "The certificates folder should be a directory"
            if attempt == 0:
                _install_certificates(directory)
            else:
                TERMINAL_APP_LOGGER.warning("The certificates were not installed")
    TERMINAL_APP_LOGGER.info("Certificates found...")
