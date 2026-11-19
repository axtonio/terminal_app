"""Shared logging configuration preserving the original report module identity."""

import logging

logger = logging.getLogger("terminal_app.google_sheets.send_metrics")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def _existing_stream_handler() -> logging.StreamHandler:
    for handler in logger.handlers:
        if (
            isinstance(handler, logging.StreamHandler)
            and handler.name == "terminal_app.google_sheets"
        ):
            return handler
    return logging.StreamHandler()


stream_handler = _existing_stream_handler()
stream_handler.set_name("terminal_app.google_sheets")
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)
