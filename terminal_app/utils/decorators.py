import asyncio
import inspect
from collections.abc import Mapping
from functools import wraps
from typing import Any, Awaitable, Callable, Coroutine, TypeVar, overload

T = TypeVar("T")


def coroutine(func):
    @wraps(func)
    def wrapper_coroutine(*args, **kwargs):
        f = func(*args, **kwargs)
        next(f)
        return f

    return wrapper_coroutine


class classproperty:
    def __init__(self, func):
        self.fget = func

    def __get__(self, instance, owner):
        return self.fget(owner)


__all__ = ["get_params", "safety_call"]


def get_params(
    fn: Callable, /, params: Mapping[str, Any]
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    args: list[Any] = []
    kwargs: dict[str, Any] = {}
    signature = inspect.signature(fn)
    positional_only = [
        param.name
        for param in signature.parameters.values()
        if param.kind == param.POSITIONAL_ONLY
    ]

    other = [
        param.name
        for param in signature.parameters.values()
        if param.name not in positional_only
    ]

    args_names = tuple(params.keys())

    for arg_name in positional_only:
        if arg_name in args_names:
            args.append(params[arg_name])

    for arg_name in other:
        if arg_name in args_names:
            kwargs[arg_name] = params[arg_name]

    return (tuple(args), kwargs)


@overload
def safety_call(
    fn: Callable[..., Awaitable[T]], /
) -> Callable[..., Coroutine[Any, Any, T]]:
    pass


@overload
def safety_call(fn: Callable[..., T], /) -> Callable[..., T]:
    pass


@overload
async def safety_call(
    fn: Callable[..., Awaitable[T]], /, params: Mapping[str, Any]
) -> T:
    pass


@overload
def safety_call(fn: Callable[..., T], /, params: Mapping[str, Any]) -> T:
    pass


def safety_call(
    fn: Callable[..., T], /, params: Mapping[str, Any] | None = None
) -> T | Coroutine | Callable[..., T]:
    if params is None:

        @wraps(fn)
        def wrapper(**kwargs):

            return safety_call(fn, params=kwargs)

        setattr(wrapper, "__signature__", inspect.signature(fn))
        return wrapper

    args, kwargs = get_params(fn, params)

    if asyncio.iscoroutinefunction(fn):
        return fn(*args, **kwargs)
    else:
        return fn(*args, **kwargs)


def set_params(
    args: tuple[tuple[Any, int], ...] = (), kwargs: dict[str, Any] | None = None
):

    def decorator(func: Callable[..., Any]):

        @wraps(func)
        def wrapper(*a, **kw):
            arguments = list(a)

            for arg in args:
                value, ind = arg
                arguments.insert(ind, value)

            if kwargs is not None:
                kw.update(kwargs)

            return func(*arguments, **kw)

        setattr(wrapper, "__signature__", inspect.signature(func))
        return wrapper

    return decorator
