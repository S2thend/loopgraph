"""Concurrency control policies."""

from __future__ import annotations

import asyncio
import heapq
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncContextManager, AsyncIterator, List, Protocol

from .._debug import log_branch, log_parameter, log_variable_change


class ConcurrencyManager(Protocol):
    """Protocol describing a priority-aware concurrency controller."""

    def slot(self, key: str, priority: int = 0) -> AsyncContextManager[None]:
        """Acquire a concurrency slot honoring the provided priority."""
        ...


class SemaphorePolicy(ConcurrencyManager):
    """Manage shared concurrency with an asyncio semaphore.

    >>> async def demo():
    ...     policy = SemaphorePolicy(limit=2)
    ...     async with policy.slot("worker", priority=0):
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
        permits = int(getattr(self._semaphore, "_value", 0))
        log_variable_change(func_name, "permits", permits)
        return permits

    def slot(self, key: str, priority: int = 0) -> AsyncContextManager[None]:
        """Acquire a semaphore slot for the duration of the context."""

        @asynccontextmanager
        async def _slot() -> AsyncIterator[None]:
            func_name = "SemaphorePolicy.slot"
            log_parameter(func_name, key=key, priority=priority)
            await self._semaphore.acquire()
            log_variable_change(
                func_name, "permits_after_acquire", self.available_permits
            )
            try:
                log_branch(func_name, "enter_context")
                yield
            finally:
                log_branch(func_name, "exit_context")
                self._semaphore.release()
                log_variable_change(
                    func_name, "permits_after_release", self.available_permits
                )

        return _slot()


@dataclass(order=True)
class _PriorityEntry:
    priority: int
    order: int
    key: str = field(compare=False)


class PrioritySemaphorePolicy(ConcurrencyManager):
    """Semaphore implementation that releases slots in priority order.

    >>> async def demo():
    ...     policy = PrioritySemaphorePolicy(limit=1)
    ...     order: List[str] = []
    ...
    ...     async def worker(name: str, priority: int, delay: float = 0.0) -> None:
    ...         await asyncio.sleep(delay)
    ...         async with policy.slot(name, priority=priority):
    ...             order.append(name)
    ...
    ...     await asyncio.gather(
    ...         worker("low", priority=10, delay=0.01),
    ...         worker("high", priority=0, delay=0.0),
    ...     )
    ...     return order
    >>> import asyncio
    >>> asyncio.run(demo())
    ['high', 'low']
    """

    def __init__(self, limit: int) -> None:
        func_name = "PrioritySemaphorePolicy.__init__"
        log_parameter(func_name, limit=limit)
        if limit <= 0:
            log_branch(func_name, "invalid_limit")
            raise ValueError("limit must be positive")
        log_branch(func_name, "valid_limit")
        self._limit = limit
        log_variable_change(func_name, "self._limit", self._limit)
        self._available = limit
        log_variable_change(func_name, "self._available", self._available)
        self._queue: List[_PriorityEntry] = []
        log_variable_change(func_name, "self._queue", self._queue)
        self._order = 0
        log_variable_change(func_name, "self._order", self._order)
        self._condition = asyncio.Condition()
        log_variable_change(func_name, "self._condition", self._condition)

    def slot(self, key: str, priority: int = 0) -> AsyncContextManager[None]:
        """Acquire a slot honoring the lowest priority value first."""

        @asynccontextmanager
        async def _slot() -> AsyncIterator[None]:
            func_name = "PrioritySemaphorePolicy.slot"
            log_parameter(func_name, key=key, priority=priority)
            entry = _PriorityEntry(priority=priority, order=self._order, key=key)
            self._order += 1
            log_variable_change(func_name, "entry", entry)
            async with self._condition:
                heapq.heappush(self._queue, entry)
                log_variable_change(func_name, "queue", list(self._queue))
                while not self._can_acquire(entry):
                    log_branch(func_name, "wait_for_turn")
                    await self._condition.wait()
                log_branch(func_name, "acquired_priority_slot")
                self._available -= 1
                heapq.heappop(self._queue)
                log_variable_change(func_name, "self._available", self._available)
            try:
                log_branch(func_name, "enter_context")
                yield
            finally:
                async with self._condition:
                    log_branch(func_name, "release_slot")
                    self._available += 1
                    log_variable_change(func_name, "self._available", self._available)
                    self._condition.notify_all()

        return _slot()

    def _can_acquire(self, entry: _PriorityEntry) -> bool:
        """Return True if the entry can take a slot."""

        func_name = "PrioritySemaphorePolicy._can_acquire"
        log_parameter(func_name, entry=entry)
        if self._available <= 0:
            log_branch(func_name, "no_available_permits")
            return False
        if not self._queue:
            log_branch(func_name, "queue_empty")
            return False
        head = self._queue[0]
        log_variable_change(func_name, "head", head)
        if head is not entry:
            log_branch(func_name, "not_head_of_queue")
            return False
        log_branch(func_name, "can_acquire")
        return True
