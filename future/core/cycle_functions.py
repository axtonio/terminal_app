import sys
from typing import Callable, Any
from functools import wraps
from copy import deepcopy

from terminal_app.base import BaseOptions
from .color import RESET_ALL
from .stdout_decoration import AttentionPrint


def exit_command() -> bool:
    return_command()
    sys.exit()


def return_command() -> bool:
    print(RESET_ALL)
    return True


class QuitOrReturnOptions(BaseOptions):
    QUIT = "q", exit_command
    RETURN = "r", return_command


def app_input(message: str) -> str:
    prompt = input(message)
    if prompt == QuitOrReturnOptions.RETURN.command or prompt == "":
        prompt = QuitOrReturnOptions.RETURN.command
        QuitOrReturnOptions.RETURN.execute(prompt)
        return ""

    QuitOrReturnOptions.QUIT.execute(prompt)
    return prompt


def question_input(message: str) -> bool | str:
    prompt = app_input(f"{message} [y/n]")
    if not prompt:
        return ""

    if prompt not in ["y", "n"]:
        print("Incorrect input")
        return question_input(message)

    return True if prompt == "y" else False


def number_input(message: str, list: list[Any] | None = None) -> Any:
    prompt = app_input(message)
    if not prompt:
        return ""

    try:
        prompt = int(prompt)
        if list is None:
            return prompt
        else:
            return list[prompt]

    except Exception as ex:
        print("Incorrect input")
        print(ex)
        return number_input(message, list)


def cycle_decorator(
    message: Callable[..., str], pass_in_message: bool = False, **upper_kwargs
):
    def decorator(func: Callable[..., Any]) -> Callable[..., bool]:
        assert (
            func.__annotations__["return"] is not None
        ), "Function should not return None"

        @wraps(func)
        def wrapper(**kwargs) -> bool:
            data = deepcopy(upper_kwargs)
            if pass_in_message:
                data.update(kwargs)
            while prompt := app_input(
                f"\n{AttentionPrint.notice(func.__name__.upper())}{message(**data)}"
            ):

                kwargs.update(prompt=prompt)
                kwargs.update(data)

                func(**kwargs)

            return False

        return wrapper

    return decorator


def cycle_options(
    options,
    message: Callable[..., str] = lambda: "Choose options",
    mode: str = "",
    default: Callable[..., None] = lambda **kwargs: print("Incorrect input"),
    returnable: bool = False,
    **kwargs,
) -> Any:
    assert issubclass(
        options, BaseOptions
    ), "Options must be inherited from BaseOptions"

    while prompt := app_input(
        f"\n{AttentionPrint.notice(mode.upper())}{message()}:\n{options.present}user input: "
    ):

        results: list = []
        for option in options:
            results.append(option.execute(prompt, **kwargs))

        tmp: Any = None
        for result in results:
            if result is not None:
                if returnable:
                    return result
                tmp = result

        if tmp is not None:
            continue

        print()
        default(prompt=prompt, **kwargs)
        print()
