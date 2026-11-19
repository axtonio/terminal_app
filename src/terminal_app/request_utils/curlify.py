import json
import urllib.parse
from collections.abc import Mapping
from typing import Protocol

import requests


class RequestLike(Protocol):
    """The request attributes used here, including Flask's request interface."""

    @property
    def url(self) -> str: ...

    @property
    def method(self) -> str: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    @property
    def data(self) -> bytes: ...


HttpRequest = requests.PreparedRequest | requests.Request | RequestLike


def _text(value: str | bytes | None) -> str | None:
    return value.decode("utf-8") if isinstance(value, bytes) else value


class Curlify:
    def __init__(
        self,
        request: HttpRequest,
        localhost: bool = False,
        compressed: bool = False,
        verify: bool = True,
    ) -> None:
        self.request = request
        self.url = _text(request.url)
        if localhost:
            parsed = urllib.parse.urlparse(self.url or "")
            parsed = parsed._replace(netloc=f"127.0.0.1:{parsed.port}")
            self.url = urllib.parse.urlunparse(parsed)
        self.compressed = compressed
        self.verify = verify

    def headers(self) -> str:
        """Return the request headers in curl argument order."""
        headers = self.request.headers or {}
        return " -H ".join(
            f'"{key}: {self.url if key == "Host" else value}"'
            for key, value in headers.items()
        )

    def body(self) -> str | None:
        data = (
            self.request.body
            if isinstance(self.request, requests.PreparedRequest)
            else self.request.data
        )
        if isinstance(data, dict):
            return json.dumps(data)
        if isinstance(data, (bytearray, memoryview)):
            return bytes(data).decode("utf-8")
        if isinstance(data, (str, bytes)) or data is None:
            return _text(data)
        raise TypeError("Curlify requires a text, bytes, dictionary, or empty body")

    def to_curl(self) -> str:
        """Build a curl command from the supplied request."""
        headers = self.headers()
        body = self.body()
        method = _text(self.request.method)
        method_part = f"curl -X {method}"
        headers_part = f" -H {headers}" if headers else ""
        body_part = f" -d '{body}'" if body else ""
        curl = method_part + headers_part + body_part + f" {self.url}"
        if self.compressed:
            curl += " --compressed"
        if not self.verify:
            curl += " --insecure"
        return curl
