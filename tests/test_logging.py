from terminal_app.logging import register_logger
from logging import Logger
from pathlib import Path


logger = register_logger(
    "test.log", terminal_app_handler=True, terminal_app_stream=open("test_logging.log", "a")
)

logger.info("A")
logger.error("B")
