import io
import json
import logging
import os
import sys
from subprocess import CompletedProcess, run
from textwrap import dedent
from types import SimpleNamespace
from unittest.mock import Mock

import requests

from terminal_app.env import ProjectConfig, source
from terminal_app.env import env as project_environment
from terminal_app.env.verify_ssl_certificate import verify_ssl_certs
from terminal_app.logging.logging import TerminalAppHandler, register_logger
from terminal_app.utils import utils
from terminal_app.utils.stdout_utils import AttentionPrint, TerminalAppFormatting


def test_hidden_config_uses_environment_and_decodes_values(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", {"PORT": "9000"})
    path = tmp_path / ".config.json"
    path.write_text(json.dumps({"PORT": 8080, "DEBUG": True, "OPTIONS": [1, 2]}))
    assert source(path) == {"PORT": 9000, "DEBUG": True, "OPTIONS": [1, 2]}
    assert source(tmp_path / "missing.env", check_only=True) is False
    assert not (tmp_path / "missing.env").exists()


def test_source_lookup_and_regular_file_replacement(tmp_path, monkeypatch):
    mode = tmp_path / "mode"
    mode.mkdir()
    global_config = tmp_path / "global"
    global_config.mkdir()
    monkeypatch.setattr(
        os,
        "environ",
        {"MODE_CONFIG_DIR": str(mode), "GLOB_CONFIG_DIR": str(global_config)},
    )
    (global_config / "first.json").write_text('{"old": 1}')
    (mode / "second.json").write_text('{"new": 2}')
    assert source(["first.json", "second.json"]) == {"new": 2}


def test_remote_configuration_uses_request_result(tmp_path, monkeypatch):
    monkeypatch.setattr(
        os, "environ", {"MODE_CONFIG_DIR": str(tmp_path), "TOKEN": "REMOTE"}
    )
    (tmp_path / "remote.yaml").write_text(
        "remotes:\n  HOST: example.invalid\n  PORT: 1234\n"
    )
    values = tmp_path / ".values.json"
    values.write_text('{"TOKEN": "REMOTE"}')
    calls = []

    def request(url):
        calls.append(url)
        return SimpleNamespace(text="42\n", raise_for_status=lambda: None)

    monkeypatch.setattr(requests, "get", request)
    assert source(values)["TOKEN"] == 42
    assert calls == ["http://example.invalid:1234/TOKEN"]


def test_project_configuration_initializes_only_requested_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", {})
    config_file = tmp_path / ".terminal_app.yaml"
    monkeypatch.setattr(project_environment, "CONFIG_FILE", config_file)
    config = ProjectConfig(BASE_DIR=tmp_path, WORK_DIR=tmp_path, INIT_FOLDERS=False)
    assert config.GLOB_CONFIG_DIR == tmp_path / "configs"
    assert not config.GLOB_CONFIG_DIR.exists()
    assert config_file.exists()
    assert "# Terminal App" in str(config)
    assert os.environ["GLOB_CONFIG_DIR"] == str(tmp_path / "configs")


def test_logger_reference_does_not_mutate_formatted_record(tmp_path):
    path = tmp_path / "messages.log"
    terminal = io.StringIO()
    handler = TerminalAppHandler(terminal, path, mode="w")
    record = logging.LogRecord(
        "test", logging.INFO, __file__, 1, "hello %s", ("world",), None
    )
    try:
        handler.emit(record)
        handler.flush()
        assert path.read_text() == "hello world\n"
        assert f"{path}, line 1" in terminal.getvalue()
        assert record.msg == "hello %s"
        assert record.args == ("world",)
    finally:
        handler.close()
    assert TerminalAppHandler.get_line(logging.Logger("without_handlers")) == ""


def test_existing_logger_clear_detaches_all_handlers(tmp_path):
    name = f"foundation_{tmp_path.name}"
    logger = register_logger(name=name)
    handlers = [logging.NullHandler(), logging.NullHandler()]
    for handler in handlers:
        logger.addHandler(handler)
    replacement = register_logger(name=name, if_exist="clear", without_handlers=True)
    assert replacement.handlers == []


def test_gpu_discovery_loads_optional_torch_only_when_needed(monkeypatch):
    loader = Mock(
        return_value=SimpleNamespace(cuda=SimpleNamespace(device_count=lambda: 3))
    )
    monkeypatch.setattr(utils.importlib, "import_module", loader)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "2,4")
    assert utils.cuda_count() == 2
    loader.assert_not_called()
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES")
    assert utils.cuda_count() == 3
    loader.assert_called_once_with("torch")


def test_gpu_fallback_does_not_require_torch(monkeypatch):
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)

    def missing_torch(name):
        assert name == "torch"
        raise ImportError("optional dependency")

    monkeypatch.setattr(utils.importlib, "import_module", missing_torch)
    monkeypatch.setattr(
        utils.subprocess,
        "run",
        lambda *a, **kw: CompletedProcess(a, 0, "GPU 0\nGPU 1\n", ""),
    )
    assert utils.cuda_count() == 2
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "2, 4")
    assert utils.list_cuda_devices() == ["cuda:0", "cuda:1"]


def test_ssl_adds_certificates_and_retries_without_network(tmp_path, monkeypatch):
    certificates = tmp_path / "certificates"
    certificates.mkdir()
    (certificates / "custom.pem").write_bytes(b"custom")
    bundle = tmp_path / "bundle.pem"
    bundle.write_bytes(b"base")
    calls = []

    def request(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise requests.exceptions.SSLError("untrusted")

    monkeypatch.setattr("terminal_app.env.verify_ssl_certificate.requests.get", request)
    monkeypatch.setattr(
        "terminal_app.env.verify_ssl_certificate.certifi.where", lambda: str(bundle)
    )
    verify_ssl_certs("https://example.invalid", lambda: certificates)
    assert len(calls) == 2
    assert bundle.read_bytes() == b"basecustom"


def test_annotation_paths_and_nested_relative_values(tmp_path):
    mesh = tmp_path / "mesh.stl"
    mesh.touch()
    annotations = tmp_path / "paths.json"
    annotations.write_text('["mesh.stl"]')
    assert utils.annotations_to_path_list(annotations, read_json=True) == [mesh]
    assert utils.to_relative({"file": mesh, "value": 0}, tmp_path) == {
        "file": "{json_path}/mesh.stl",
        "value": 0,
    }
    assert utils.to_relative({"file": "mesh.stl"}, tmp_path, reverse=True) == {
        "file": str(mesh)
    }


def test_public_formatting_api_and_print_redirection(tmp_path, capsys):
    assert TerminalAppFormatting.MDASH.value == "&#8212"
    assert TerminalAppFormatting.bold("message") == "<b>message</b>"
    assert TerminalAppFormatting.done_emoji("done") == "✅ done"
    path = tmp_path / "print.log"
    AttentionPrint.plog({"value": 1}, path=str(path), desc={"source": "test"})
    print("restored")
    assert capsys.readouterr().out == "restored\n"
    assert "value" in path.read_text()


def test_terminal_handler_can_append_non_utf8_messages(tmp_path):
    path = tmp_path / "cp1251.log"
    terminal = io.StringIO()
    handler = TerminalAppHandler(terminal, path, encoding="cp1251")
    try:
        for message in ("первое сообщение", "второе сообщение"):
            record = logging.LogRecord(
                "test", logging.INFO, __file__, 1, message, (), None
            )
            handler.emit(record)
        handler.flush()
        assert path.read_text(encoding="cp1251").splitlines() == [
            "первое сообщение",
            "второе сообщение",
        ]
        assert f"{path}, line 2" in terminal.getvalue()
    finally:
        handler.close()


def test_core_imports_without_integration_extras(tmp_path):
    # A fresh interpreter prevents earlier integration tests from hiding eager imports.
    code = dedent("""
        import sys
        sys.modules.update(selenium=None, seleniumwire=None, torch=None, gspread=None)
        from terminal_app.processing_utils.core import run_stages
        from terminal_app.utils.utils import cuda_count
        assert callable(run_stages)
        assert callable(cuda_count)
    """)
    result = run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_source_public_export_accepts_explicit_check_modes(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"enabled": true}')
    assert source(config, check_only=False) == {"enabled": True}
    assert source(config, check_only=True, raise_if_exception=True) is True
