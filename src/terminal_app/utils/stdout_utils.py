import json
import logging
import os
import sys
from enum import StrEnum
from pprint import pprint
from textwrap import dedent
from typing import Any, Sequence

_ORIG_STDOUT = sys.stdout


def kill_all_output():
    """
    Disables the entire logger and redirects stdout/stderr to /dev/null.
    """
    logging.disable(logging.CRITICAL)
    logging.getLogger().handlers.clear()
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull_fd, 1)
    os.dup2(devnull_fd, 2)
    os.close(devnull_fd)


class TerminalAppFormatting(StrEnum):
    MDASH = "&#8212"
    ANTONIO_TG = "@Antonio_Rodriges"
    ANTONIO_NIKNAME = "axtonio"

    @staticmethod
    def hashtag(value: str) -> str:
        return f"#{value}"

    @staticmethod
    def bold(value: str) -> str:
        return f"<b>{value}</b>"

    @staticmethod
    def italic(value: str) -> str:
        return f"<i>{value}</i>"

    @staticmethod
    def code(value: str) -> str:
        return f"<code>{value}</code>"

    @staticmethod
    def strike(value: str) -> str:
        return f"<strike>{value}</strike>"

    @staticmethod
    def underline(value: str) -> str:
        return f"<underline>{value}</underline>"

    @staticmethod
    def pre(value: str, language: str) -> str:
        return f'<pre language="{language}">{value}</pre>'

    @staticmethod
    def dict_formatting(data: dict[str, Any]) -> str:
        return "\n\n".join([f"{name + ':'}\n{value}" for name, value in data.items()])

    @staticmethod
    def list_formatting(data: Sequence[Any], start: int = 1) -> str:
        return "\n".join([f"{ind + start}. {x}" for ind, x in enumerate(data)])

    @staticmethod
    def notice(message: str) -> str:
        return "Notice: " + message

    @staticmethod
    def error(message: str) -> str:
        return "ERROR: " + message

    @staticmethod
    def command(command: str) -> str:
        return f"/{command}"

    @staticmethod
    def commands(commands: list[Any]) -> str:
        return "\n".join(
            [
                f"{getattr(command, 'command')} {TerminalAppFormatting.MDASH} {getattr(command, 'description')}"
                for command in commands
            ]
        )

    @staticmethod
    def done_emoji(message: str) -> str:
        return f"✅ {message}"

    @staticmethod
    def fail_emoji(message: str) -> str:
        return f"❌ {message}"

    @staticmethod
    def notice_emoji(message: str) -> str:
        return f"⚠️ {message}"

    @staticmethod
    def error_emoji(message: str) -> str:
        return f"⛔ {message}"

    @staticmethod
    def new_emoji(message: str) -> str:
        return f"🆕 {message}"

    @staticmethod
    def in_process_emoji(message: str) -> str:
        return f"⏳ {message}"


class AttentionPrint:

    DEFAULT_LOG: str | None = None
    DEFAULT_CNT = 20
    HTML = dedent(
        """
    <html>
    <head>
        <title>
            {name}
        </title>
    </head>
        <body style="background-color:rgba(47,49,60,255);">
            <h1 style={color}>{name}</h1>
            <h2 style={color}>Metadata</h2>
            <div style={color}>{metadata}</div>
            <h2 style={color}>Dialog</h2>
            {body}
        </body>
    </html>
    """
    ).strip()

    def __init__(self, name: str, cnt: int = DEFAULT_CNT, point: bool = False):
        self.name = name
        self.point = point
        self.cnt = cnt

    @staticmethod
    def notice(name: str = "Notice", cnt: int = DEFAULT_CNT) -> str:
        half_len: int = int((cnt - len(name)) / 2)
        result = "!" + "-" * half_len + name + "-" * half_len + "!"
        result += "\n"
        return result

    @staticmethod
    def pretty_list(data: list, exclude: list = []) -> str:
        result: str = ""
        for ind, item in enumerate(data):
            if item not in exclude:
                result += f"{ind}. {item}"
                if ind != len(data) - 1:
                    result += "\n"

        return result

    def __enter__(self):
        if self.point is True:
            name = "Start" + " " + self.name
        else:
            name = self.name

        print(self.notice(name, self.cnt))

        return self

    @staticmethod
    def pretty_dict(data: Any):
        print(json.dumps(data, sort_keys=False, ensure_ascii=False, indent=4))

    @staticmethod
    def pprint(data: Any):
        pprint(data)

    @staticmethod
    def plog(
        data: Any,
        name: str = "data",
        desc: dict[str, str] = {},
        path: str | None = DEFAULT_LOG,
        mode: str = "a",
        pretty_list: bool = False,
    ):
        if mode not in ["w", "a"]:
            print("Incorrect logging mode")
            return
        if path:
            with open(path, mode) as f:

                sys.stdout = f
                with AttentionPrint(name=name) as log:

                    print(f"{name} = ", end="")
                    if pretty_list:
                        log.pprint(data)

                    else:
                        if isinstance(data, dict):
                            log.pprint(data)
                        else:
                            print(data)

                    if desc:
                        print("\n")
                        for key, value in desc.items():
                            print(f"{key.upper()} ", value, end="\n")

                sys.stdout = _ORIG_STDOUT

    def __exit__(self, type, value, traceback):
        print("\n" * 2)
        if self.point is True:
            name = "End" + " " + self.name
        else:
            name = ""

        print(self.notice(name, self.cnt))

        print("\n")
