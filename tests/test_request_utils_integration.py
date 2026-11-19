"""Request and browser adapters are exercised without network connections."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

pytest.importorskip("selenium.webdriver.chrome.options")
pytest.importorskip("selenium.webdriver.chrome.service")
pytest.importorskip("selenium.webdriver.chrome.webdriver")

proxy_module = import_module("terminal_app.request_utils.proxy_utils")
Curlify = import_module("terminal_app.request_utils.curlify").Curlify


def test_curlify_keeps_request_body_and_header_quoting():
    request = requests.Request(
        "POST",
        "https://example.test:9000/path",
        data={"message": "hello"},
        headers={"Host": "example.test", "Content-Type": "application/json"},
    )
    command = Curlify(request, localhost=True, compressed=True, verify=False).to_curl()
    assert command == (
        'curl -X POST -H "Host: https://127.0.0.1:9000/path"'
        ' -H "Content-Type: application/json"'
        ' -d \'{"message": "hello"}\' https://127.0.0.1:9000/path --compressed --insecure'
    )


@pytest.mark.parametrize("body", [None, "hello", b"hello", bytearray(b"hello")])
def test_prepared_request_body_is_text_or_absent(body):
    request = requests.Request("POST", "https://example.test/path").prepare()
    request.body = body
    assert Curlify(request).body() == (None if body is None else "hello")


def test_flask_compatible_request_does_not_require_flask():
    request = SimpleNamespace(
        method="POST", url="https://example.test/path", headers={}, data=b"hello"
    )
    assert Curlify(request).to_curl() == (
        "curl -X POST -d 'hello' https://example.test/path"
    )


@pytest.mark.parametrize("fullscreen", [False, True])
def test_browser_factory_receives_existing_proxy_and_options(monkeypatch, fullscreen):
    driver_factory = Mock()
    loader = Mock(return_value=SimpleNamespace(Chrome=driver_factory))
    monkeypatch.setattr(proxy_module, "import_module", loader)

    result = proxy_module.open_driver(
        "user:secret@proxy.test:8000", fullscreen, 800, 600, "/custom/chromedriver"
    )

    loader.assert_called_once_with("seleniumwire.webdriver")
    assert result is driver_factory.return_value
    kwargs = driver_factory.call_args.kwargs
    assert kwargs["service"].path == "/custom/chromedriver"
    assert kwargs["options"].arguments == [
        "--start-maximized" if fullscreen else "--window-size=800,600"
    ]
    assert kwargs["options"].experimental_options == {
        "excludeSwitches": ["enable-automation"],
        "useAutomationExtension": False,
        "detach": True,
    }
    assert kwargs["seleniumwire_options"] == {
        "proxy": {
            "http": "http://user:secret@proxy.test:8000",
            "https": "http://user:secret@proxy.test:8000",
            "no_proxy": "localhost,127.0.0.1",
        }
    }
