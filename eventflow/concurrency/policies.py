"""Concurrency control policies."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, cast

from .._debug import log_branch, log_parameter, log_variable_change


class SemaphorePolicy:
    """Manage shared concurrency with an asyncio semaphore.

    >>> async def demo():
    ...     policy = SemaphorePolicy(limit=2)
    ...     async with policy.slot():
    ...         return policy.available_permits
    >>> import asyncio
    >>> asyncio.run(demo())
    1
    """

    def __init__(self, limit: int) -> None:
        func_name = "SemaphorePolicy.__init__"
        log_parameter(func_name, limit=limit)
        if limit <= 0:
            log_branch(func_name, "invalid_limit")
            raise ValueError("limit must be positive")
        log_branch(func_name, "valid_limit")
        self._limit = limit
        log_variable_change(func_name, "self._limit", self._limit)
        self._semaphore = asyncio.Semaphore(limit)
        log_variable_change(func_name, "self._semaphore", self._semaphore)

    @property
    def available_permits(self) -> int:
        """Return currently available semaphore permits.

        >>> policy = SemaphorePolicy(limit=1)
        >>> policy.available_permits
        1
        """
        func_name = "SemaphorePolicy.available_permits"
        log_parameter(func_name)
        permits = cast(int, getattr(self._semaphore, "_value", 0))
        log_variable_change(func_name, "permits", permits)
        return permits

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Acquire a semaphore slot for the duration of the context.

        >>> async def demo():
        ...     policy = SemaphorePolicy(limit=1)
        ...     async with policy.slot():
        ...         return policy.available_permits
        >>> import asyncio
        >>> asyncio.run(demo())
        0
        """
        func_name = "SemaphorePolicy.slot"
        log_parameter(func_name)
        await self._semaphore.acquire()
        log_variable_change(func_name, "permits_after_acquire", self.available_permits)
        try:
            log_branch(func_name, "enter_context")
            yield
        finally:
            log_branch(func_name, "exit_context")
            self._semaphore.release()
            log_variable_change(
                func_name, "permits_after_release", self.available_permits
            )
