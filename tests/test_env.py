from pathlib import Path

import pytest

from terminal_app.env import SourceEnv, source


def test_source_reads_json_file(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text('{"PORT": 8080, "DEBUG": true, "NAME": "cadpac"}')

    data = source(config)

    assert data["PORT"] == 8080
    assert data["DEBUG"] is True
    assert data["NAME"] == "cadpac"


def test_source_env_missing_key_has_helpful_message() -> None:
    env = SourceEnv({"EXISTING": "value"})

    with pytest.raises(KeyError) as exc_info:
        _ = env["MISSING"]

    message = str(exc_info.value)
    assert "MISSING" in message
    assert "configuration environment" in message
