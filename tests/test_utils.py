from terminal_app.utils import AllParams, TerminalAppFormatting, chunks


def test_all_params_keeps_self_reference() -> None:
    params = AllParams({"a": 1}, b=2)

    assert params["all_params"] is params
    assert params["a"] == 1
    assert params["b"] == 2

    params["all_params"] = "ignored"

    assert params["all_params"] is params


def test_chunks_splits_list_into_equal_groups() -> None:
    assert chunks([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_terminal_app_formatting_helpers() -> None:
    assert TerminalAppFormatting.bold("text") == "<b>text</b>"
    assert TerminalAppFormatting.list_formatting(["one", "two"]) == "1. one\n2. two"
