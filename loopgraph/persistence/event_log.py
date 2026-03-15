"""Persistence interfaces and in-memory event log implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Protocol

from .._debug import (
    log_branch,
    log_loop_iteration,
    log_parameter,
    log_variable_change,
)
from ..bus.eventbus import Event


class EventLog(Protocol):
    """Protocol for append-only event logs.

    >>> from loopgraph.core.types import EventType
    >>> log = InMemoryEventLog()
    >>> log.append(Event(id="evt", graph_id="g", node_id=None, type=EventType.NODE_COMPLETED))
    >>> [evt.type for evt in log.iter("g")]
    [<EventType.NODE_COMPLETED: 'node_completed'>]
    """

    def append(self, event: Event) -> None:
        """Persist an event in the log."""

    def iter(self, graph_id: str) -> Iterable[Event]:
        """Replay events for a graph."""
        ...


@dataclass
class InMemoryEventLog(EventLog):
    """Simple in-memory event log.

    >>> from ..core.types import EventType
    >>> log = InMemoryEventLog()
    >>> log.append(Event(id="evt-1", graph_id="graph", node_id=None, type=EventType.WORKFLOW_COMPLETED))
    >>> [evt.id for evt in log.iter("graph")]
    ['evt-1']
    """

    _events: List[Event] = field(default_factory=list)

    def append(self, event: Event) -> None:
        func_name = "InMemoryEventLog.append"
        log_parameter(func_name, event=event)
        self._events.append(event)
        log_variable_change(func_name, "self._events", self._events)

    def iter(self, graph_id: str) -> Iterable[Event]:
        func_name = "InMemoryEventLog.iter"
        log_parameter(func_name, graph_id=graph_id)
        for iteration, event in enumerate(self._events):
            log_loop_iteration(func_name, "events", iteration)
            if event.graph_id == graph_id:
                log_branch(func_name, "graph_match")
                yield event
            else:
                log_branch(func_name, "graph_mismatch")
