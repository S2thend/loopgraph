"""Asynchronous event bus implementation."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .._debug import (
    log_branch,
    log_loop_iteration,
    log_parameter,
    log_variable_change,
)
from ..core.types import EventType, NodeStatus

EventListener = Callable[["Event"], Awaitable[None]]


@dataclass(frozen=True)
class Event:
    """Event emitted during workflow execution.

    >>> evt = Event(
    ...     id="evt-1",
    ...     graph_id="graph-1",
    ...     node_id="node-1",
    ...     type=EventType.NODE_COMPLETED,
    ... )
    >>> evt.type
    <EventType.NODE_COMPLETED: 'node_completed'>
    """

    id: str
    graph_id: str
    node_id: Optional[str]
    type: EventType
    payload: Any = None
    timestamp: float = field(default_factory=lambda: time.time())
    replay: bool = False
    visit_count: Optional[int] = None
    status: Optional[NodeStatus] = None


class EventBus:
    """Simple in-memory event bus.

    >>> async def demo():
    ...     bus = EventBus()
    ...     received = []
    ...
    ...     async def listener(event: Event) -> None:
    ...         received.append(event.id)
    ...
    ...     bus.subscribe(EventType.NODE_COMPLETED, listener)
    ...     await bus.emit(
    ...         Event(
    ...             id="evt",
    ...             graph_id="g",
    ...             node_id="n",
    ...             type=EventType.NODE_COMPLETED,
    ...         )
    ...     )
    ...     return received
    >>> asyncio.run(demo())
    ['evt']
    """

    def __init__(self) -> None:
        func_name = "EventBus.__init__"
        log_parameter(func_name)
        self._listeners: Dict[Optional[EventType], List[EventListener]] = {}
        log_variable_change(func_name, "self._listeners", self._listeners)

    def subscribe(
        self,
        event_type: Optional[EventType],
        listener: EventListener,
    ) -> None:
        """Register a listener for a specific event type or all events.

        >>> bus = EventBus()
        >>> async def noop(_event: Event) -> None:
        ...     pass
        >>> bus.subscribe(None, noop)
        """
        func_name = "EventBus.subscribe"
        log_parameter(func_name, event_type=event_type, listener=listener)
        listeners = self._listeners.setdefault(event_type, [])
        log_variable_change(func_name, "listeners_before", list(listeners))
        listeners.append(listener)
        log_variable_change(func_name, "listeners_after", list(listeners))

    def unsubscribe(
        self,
        event_type: Optional[EventType],
        listener: EventListener,
    ) -> None:
        """Remove a listener from the bus if present.

        >>> bus = EventBus()
        >>> async def noop(_event: Event) -> None:
        ...     pass
        >>> bus.subscribe(None, noop)
        >>> bus.unsubscribe(None, noop)
        """
        func_name = "EventBus.unsubscribe"
        log_parameter(func_name, event_type=event_type, listener=listener)
        listeners = self._listeners.get(event_type, [])
        log_variable_change(func_name, "listeners_before", list(listeners))
        if listener in listeners:
            log_branch(func_name, "listener_present")
            listeners.remove(listener)
            log_variable_change(func_name, "listeners_after", list(listeners))
        else:
            log_branch(func_name, "listener_missing")

    async def emit(self, event: Event) -> List[Any]:
        """Emit an event to all registered listeners.

        >>> async def demo():
        ...     bus = EventBus()
        ...     events: List[str] = []
        ...
        ...     async def collector(evt: Event) -> None:
        ...         events.append(evt.id)
        ...
        ...     bus.subscribe(None, collector)
        ...     await bus.emit(
        ...         Event(
        ...             id="evt-1",
        ...             graph_id="g",
        ...             node_id=None,
        ...             type=EventType.WORKFLOW_COMPLETED,
        ...         )
        ...     )
        ...     return events
        >>> asyncio.run(demo())
        ['evt-1']
        """
        func_name = "EventBus.emit"
        log_parameter(func_name, event=event)
        listeners = list(self._listeners.get(event.type, []))
        log_variable_change(func_name, "typed_listeners", listeners)
        global_listeners = list(self._listeners.get(None, []))
        log_variable_change(func_name, "global_listeners", global_listeners)
        all_listeners = listeners + global_listeners
        log_variable_change(func_name, "all_listeners", all_listeners)
        if not all_listeners:
            log_branch(func_name, "no_listeners")
            return []
        log_branch(func_name, "dispatch_listeners")
        tasks = []
        log_variable_change(func_name, "tasks", tasks)
        for iteration, listener in enumerate(all_listeners):
            log_loop_iteration(func_name, "listeners", iteration)
            task = asyncio.create_task(listener(event))
            log_variable_change(func_name, "task", task)
            tasks.append(task)
            log_variable_change(func_name, "tasks", list(tasks))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        log_variable_change(func_name, "results", results)
        return results
