from .color import Color, RESET
from .cycle_functions import app_input


class Colorize:
    def __init__(self, color: Color) -> None:
        self.color = color

    def colorize_terminal_output(
        self, header: str | None = None, content: str | None = None
    ) -> str:
        if header is not None:
            message = f"{self.color.txt}{header}: {content}{RESET}"
        else:
            message = f"{self.color.txt}{content}{RESET}"
        return message

    def colorize_terminal_input(
        self, header: str | None = None, content: str | None = None
    ) -> str:
        message = ""
        
        if header is not None:
            message += f"{self.color.txt}{header}: "
        if content is not None:
            message += f"{self.color.txt}{content}"
        
        message = app_input(message)
        if message:
            f"{message}{RESET}"
        return message



