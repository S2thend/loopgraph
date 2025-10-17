"""Fundamental enums and dataclasses shared across EventFlow modules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from .._debug import log_parameter, log_variable_change


class NodeKind(str, Enum):
    """Enumerated node kinds supported by EventFlow."""

    TASK = "task"
    SWITCH = "switch"
    AGGREGATE = "aggregate"
    TERMINAL = "terminal"


class NodeStatus(str, Enum):
    """Execution states tracked for each node."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class EventType(str, Enum):
    """Event kinds emitted during workflow execution."""

    NODE_SCHEDULED = "node_scheduled"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    WORKFLOW_COMPLETED = "workflow_completed"


@dataclass(frozen=True)
class VisitOutcome:
    """Represents the result of a node execution attempt."""

    status: NodeStatus
    detail: Optional[str] = None
    payload: Optional[Any] = None

    @classmethod
    def success(cls, payload: Optional[Any] = None) -> "VisitOutcome":
        """Construct a successful outcome.

        >>> VisitOutcome.success({"count": 2}).status
        <NodeStatus.COMPLETED: 'completed'>
        """
        func_name = "VisitOutcome.success"
        log_parameter(func_name, payload=payload)
        outcome = cls(status=NodeStatus.COMPLETED, payload=payload)
        log_variable_change(func_name, "outcome", outcome)
        return outcome

    @classmethod
    def failure(cls, detail: Optional[str] = None) -> "VisitOutcome":
        """Construct a failed outcome.

        >>> VisitOutcome.failure("boom").detail
        'boom'
        """
        func_name = "VisitOutcome.failure"
        log_parameter(func_name, detail=detail)
        outcome = cls(status=NodeStatus.FAILED, detail=detail)
        log_variable_change(func_name, "outcome", outcome)
        return outcome
