"""Function registry for node handlers."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable, Dict

from .._debug import log_branch, log_parameter, log_variable_change

Handler = Callable[..., Any]


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
        if inspect.isawaitable(result):
            log_branch(func_name, "await_result")
            awaited = await result  # type: ignore[no-any-union]
            log_variable_change(func_name, "awaited", awaited)
            return awaited
        log_branch(func_name, "return_result")
        return result
