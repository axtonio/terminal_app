from enum import Enum


CSI = "\033["
OSC = "\033]"
BEL = "\a"


def code_to_chars(code: int) -> str:
    return CSI + str(code) + "m"


RESET = code_to_chars(39)
RESET_ALL = code_to_chars(0)


class Color(Enum):
    BLACK = 30
    RED = 31
    GREEN = 32, "color:rgba(72,179,123,255);"
    YELLOW = 33
    BLUE = 34, "color:rgba(123,189,203,255);"
    MAGENTA = 35
    PURPLE = 36, "color:rgba(72,179,123,255);"

    # WHITE = 37
    # RESET = 39
    # RESET_ALL = 0

    # # These are fairly well supported, but not part of the standard.
    # LIGHTBLACK_EX = 90
    # LIGHTRED_EX = 91
    # LIGHTGREEN_EX = 92
    # LIGHTYELLOW_EX = 93
    # LIGHTBLUE_EX = 94
    # LIGHTMAGENTA_EX = 95
    # LIGHTCYAN_EX = 96
    # LIGHTWHITE_EX = 97

    def __init__(self, txt: int, html: str = "color:rgba(72,179,123,255);") -> None:
        self.txt = code_to_chars(txt)
        self.html = html
