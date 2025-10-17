"""Function registry for node handlers."""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Dict, TypeGuard

from .._debug import log_branch, log_parameter, log_variable_change

Handler = Callable[..., Any]


def _is_awaitable(value: object) -> TypeGuard[Awaitable[Any]]:
    """Type guard helping to determine whether a value can be awaited.

    >>> _is_awaitable(1)
    False
    >>> class DummyAwaitable:
    ...     def __await__(self):
    ...         yield
    ...         return None
    >>> _is_awaitable(DummyAwaitable())
    True
    """

    func_name = "_is_awaitable"
    log_parameter(func_name, value=value)
    result = inspect.isawaitable(value)
    log_variable_change(func_name, "result", result)
    return bool(result)


async def _resolve_result(value: object) -> Any:
    """Normalize handler results into awaited values.

    >>> import asyncio
    >>> asyncio.run(_resolve_result(3))
    3
    >>> async def sample() -> str:
    ...     return "ok"
    >>> asyncio.run(_resolve_result(sample()))
    'ok'
    """

    func_name = "_resolve_result"
    log_parameter(func_name, value=value)
    if _is_awaitable(value):
        log_branch(func_name, "awaitable")
        awaited = await value
        log_variable_change(func_name, "awaited", awaited)
        return awaited
    log_branch(func_name, "immediate")
    log_variable_change(func_name, "value", value)
    return value


class FunctionRegistry:
    """Manage handler functions keyed by name.

    >>> import asyncio
    >>> registry = FunctionRegistry()
    >>> async def handler(value: int) -> int:
    ...     return value + 1
    >>> registry.register("inc", handler)
    >>> asyncio.run(registry.execute("inc", 1))
    2
    """

    def __init__(self) -> None:
        func_name = "FunctionRegistry.__init__"
        log_parameter(func_name)
        self._handlers: Dict[str, Handler] = {}
        log_variable_change(func_name, "self._handlers", self._handlers)

    def register(self, name: str, handler: Handler) -> None:
        """Register a handler by name.

        >>> registry = FunctionRegistry()
        >>> registry.register("noop", lambda: None)
        """
        func_name = "FunctionRegistry.register"
        log_parameter(func_name, name=name, handler=handler)
        self._handlers[name] = handler
        log_variable_change(
            func_name, f"self._handlers[{name!r}]", self._handlers[name]
        )

    def get(self, name: str) -> Handler:
        """Retrieve a registered handler."""
        func_name = "FunctionRegistry.get"
        log_parameter(func_name, name=name)
        if name not in self._handlers:
            log_branch(func_name, "missing_handler")
            raise KeyError(f"Handler '{name}' is not registered")
        log_branch(func_name, "handler_found")
        handler = self._handlers[name]
        log_variable_change(func_name, "handler", handler)
        return handler

    async def execute(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """Execute a registered handler, awaiting async functions.

        >>> import asyncio
        >>> registry = FunctionRegistry()
        >>> registry.register("add", lambda a, b: a + b)
        >>> asyncio.run(registry.execute("add", 1, 2))
        3
        """
        func_name = "FunctionRegistry.execute"
        log_parameter(func_name, name=name, args=args, kwargs=kwargs)
        handler = self.get(name)
        log_variable_change(func_name, "handler", handler)
        result = handler(*args, **kwargs)
        log_variable_change(func_name, "result", result)
        resolved = await _resolve_result(result)
        log_variable_change(func_name, "resolved", resolved)
        return resolved
