import json
import os
from pathlib import Path
from typing import Any

import paramiko

from terminal_app.request_utils.curlify import Curlify, HttpRequest


class SSHClient(paramiko.SSHClient):
    def __init__(
        self, name: str, password: str | None = None, path: Path = Path("~/.ssh")
    ) -> None:
        self.config = paramiko.SSHConfig.from_path(
            os.path.expanduser(path / "config")
        ).lookup(name)
        super().__init__()

        self.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.load_host_keys(os.path.expanduser(path / "known_hosts"))

        if self.config.get("identityfile"):
            self.config.update({"key_filename": self.config["identityfile"]})
            self.config.pop("identityfile")

        self.config.update({"username": self.config["user"]})
        self.config.pop("user")
        if password:
            self.config.update({"password": password})

        self.connect(**self.config)  # type: ignore
        transport = self.get_transport()
        if transport is not None:
            transport.set_keepalive(60)

    def http_request(self, request: HttpRequest) -> dict[str, Any]:
        ssh_stdin, ssh_stdout, ssh_stderr = self.exec_command(
            Curlify(request, localhost=True).to_curl()
        )
        ssh_stdin.close()

        res_line = ""
        for line in ssh_stdout:
            res_line += line

        print(res_line)

        return json.loads(res_line)
