from pathlib import Path

from terminal_app.logging import register_logger


def test_register_logger_writes_file_and_terminal_stream(tmp_path: Path) -> None:
    log_file = tmp_path / "app.log"
    stream_file = tmp_path / "terminal.log"

    with stream_file.open("w+", encoding="utf-8") as stream:
        logger = register_logger(
            log_file,
            name=f"test_{tmp_path.name}",
            terminal_app_handler=True,
            terminal_app_stream=stream,
            if_exist="clear",
        )
        logger.info("hello")

        for handler in logger.handlers:
            flush = getattr(handler, "flush", None)
            if flush is not None:
                flush()

        stream.flush()
        stream.seek(0)

        assert log_file.exists()
        assert "hello" in log_file.read_text()
        assert f"{log_file}, line 1" in stream.read()
