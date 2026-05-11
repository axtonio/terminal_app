from __future__ import annotations

import json
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    import flask  # type: ignore

import urllib.parse


class Curlify:
    def __init__(
        self,
        request: requests.PreparedRequest | requests.Request | flask.Request,
        localhost=False,
        compressed=False,
        verify=True,
    ):
        self.request = request
        self.url = self.request.url

        if localhost:
            parsed = urllib.parse.urlparse(self.request.url)
            parsed = parsed._replace(netloc=f"127.0.0.1:{parsed.port}")
            self.url = urllib.parse.urlunparse(parsed)
        self.compressed = compressed
        self.verify = verify

    def headers(self) -> str:
        """organize headers

        Returns:
            str: return string of set headers
        """

        def validation(k, v):
            if k == "Host":
                v = self.url
            return f'"{k}: {v}"'

        headers = [validation(k, v) for k, v in self.request.headers.items()]

        return " -H ".join(headers)

    def body(self) -> str | None:
        if not isinstance(self.request, requests.PreparedRequest):
            if isinstance(self.request.data, dict):
                return json.dumps(self.request.data)
            return str(self.request.data, "utf-8")

        return (
            self.request.body
            if isinstance(self.request.body, str | None)
            else str(self.request.body, "utf-8")
        )

    def to_curl(self) -> str:
        """build curl command

        Returns:
            str: string represents curl command
        """
        method_part = f"curl -X {self.request.method}"
        headers_part = f" -H {self.headers()}" if self.headers() else ""
        body_part = f" -d '{self.body()}'" if self.body() else ""
        url_part = f" {self.url}"

        curl = method_part + headers_part + body_part + url_part
        if self.compressed:
            curl += " --compressed"
        if not self.verify:
            curl += " --insecure"

        return curl
