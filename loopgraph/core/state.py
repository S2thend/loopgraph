"""Runtime execution state helpers for LoopGraph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set

from .._debug import (
    log_branch,
    log_loop_iteration,
    log_parameter,
    log_variable_change,
)
from .graph import Graph
from .types import NodeKind, NodeStatus, VisitOutcome

SNAPSHOT_FORMAT_VERSION = 2


@dataclass
class NodeVisit:
    """Track visit metadata for a node.

    >>> visit = NodeVisit()
    >>> visit.increment("evt-1").count
    1
    """

    count: int = 0
    last_event_id: Optional[str] = None

    def increment(self, event_id: Optional[str]) -> "NodeVisit":
        """Return a new `NodeVisit` with an incremented count."""
        func_name = "NodeVisit.increment"
        log_parameter(func_name, event_id=event_id)
        new_visit = NodeVisit(count=self.count + 1, last_event_id=event_id)
        log_variable_change(func_name, "new_visit", new_visit)
        return new_visit


@dataclass
class NodeRuntimeState:
    """Mutable execution state for a single node."""

    status: NodeStatus = NodeStatus.PENDING
    outcome: Optional[VisitOutcome] = None
    visits: NodeVisit = field(default_factory=NodeVisit)
    upstream_completed: Set[str] = field(default_factory=set)
    last_payload: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the runtime state to a dictionary payload.

        >>> state = NodeRuntimeState()
        >>> state.status = NodeStatus.RUNNING
        >>> payload = state.to_dict()
        >>> payload["status"]
        'running'
        """
        func_name = "NodeRuntimeState.to_dict"
        log_parameter(func_name)
        payload = {
            "status": self.status.value,
            "outcome": None
            if self.outcome is None
            else {
                "status": self.outcome.status.value,
                "detail": self.outcome.detail,
                "payload": self.outcome.payload,
            },
            "visits": {
                "count": self.visits.count,
                "last_event_id": self.visits.last_event_id,
            },
            "upstream_completed": sorted(self.upstream_completed),
            "last_payload": self.last_payload,
        }
        log_variable_change(func_name, "payload", payload)
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "NodeRuntimeState":
        """Restore runtime state from a dictionary payload.

        >>> original = NodeRuntimeState(status=NodeStatus.COMPLETED)
        >>> restored = NodeRuntimeState.from_dict(original.to_dict())
        >>> restored.status
        <NodeStatus.COMPLETED: 'completed'>
        """
        func_name = "NodeRuntimeState.from_dict"
        log_parameter(func_name, payload=payload)
        status = NodeStatus(payload["status"])
        log_variable_change(func_name, "status", status)
        outcome_payload = payload.get("outcome")
        if outcome_payload is None:
            log_branch(func_name, "no_outcome")
            outcome = None
        else:
            log_branch(func_name, "with_outcome")
            outcome = VisitOutcome(
                status=NodeStatus(outcome_payload["status"]),
                detail=outcome_payload.get("detail"),
                payload=outcome_payload.get("payload"),
            )
        log_variable_change(func_name, "outcome", outcome)
        visits_payload = payload.get("visits", {})
        log_variable_change(func_name, "visits_payload", visits_payload)
        visits = NodeVisit(
            count=int(visits_payload.get("count", 0)),
            last_event_id=visits_payload.get("last_event_id"),
        )
        log_variable_change(func_name, "visits", visits)
        upstream_completed = set(payload.get("upstream_completed", []))
        log_variable_change(func_name, "upstream_completed", upstream_completed)
        state = cls(
            status=status,
            outcome=outcome,
            visits=visits,
            upstream_completed=upstream_completed,
            last_payload=payload.get("last_payload"),
        )
        log_variable_change(func_name, "state", state)
        return state


class ExecutionState:
    """Container for per-node runtime state tracking.

    >>> from loopgraph.core.graph import Edge, Node
    >>> from loopgraph.core.types import NodeKind
    >>> graph = Graph(
    ...     nodes={
    ...         "a": Node(id="a", kind=NodeKind.TASK, handler="A"),
    ...         "b": Node(id="b", kind=NodeKind.TASK, handler="B"),
    ...     },
    ...     edges={"e": Edge(id="e", source="a", target="b")},
    ... )
    >>> runtime = ExecutionState()
    >>> runtime.is_ready(graph, "a")
    True
    >>> runtime.mark_running("a")
    >>> runtime.mark_complete("a", event_id="evt-1", outcome=VisitOutcome.success())
    >>> runtime.note_upstream_completion("b", "a")
    >>> runtime.is_ready(graph, "b")
    True
    >>> agg_graph = Graph(
    ...     nodes={
    ...         "x": Node(id="x", kind=NodeKind.TASK, handler="X"),
    ...         "y": Node(id="y", kind=NodeKind.TASK, handler="Y"),
    ...         "agg": Node(
    ...             id="agg",
    ...             kind=NodeKind.AGGREGATE,
    ...             handler="Aggregate",
    ...             config={"required": 2},
    ...         ),
    ...     },
    ...     edges={
    ...         "e1": Edge(id="e1", source="x", target="agg"),
    ...         "e2": Edge(id="e2", source="y", target="agg"),
    ...     },
    ... )
    >>> runtime_agg = ExecutionState()
    >>> runtime_agg.note_upstream_completion("agg", "x")
    >>> runtime_agg.is_ready(agg_graph, "agg")
    False
    >>> runtime_agg.note_upstream_completion("agg", "y")
    >>> runtime_agg.is_ready(agg_graph, "agg")
    True
    """

    def __init__(self) -> None:
        func_name = "ExecutionState.__init__"
        log_parameter(func_name)
        self._states: Dict[str, NodeRuntimeState] = {}
        log_variable_change(func_name, "self._states", self._states)
        self._completed_nodes: Set[str] = set()
        log_variable_change(func_name, "self._completed_nodes", self._completed_nodes)

    def _ensure_state(self, node_id: str) -> NodeRuntimeState:
        """Ensure a runtime state entry exists for the given node."""
        func_name = "ExecutionState._ensure_state"
        log_parameter(func_name, node_id=node_id)
        if node_id not in self._states:
            log_branch(func_name, "create_state")
            self._states[node_id] = NodeRuntimeState()
            log_variable_change(
                func_name, f"self._states[{node_id!r}]", self._states[node_id]
            )
        else:
            log_branch(func_name, "state_exists")
        return self._states[node_id]

    def is_ready(self, graph: Graph, node_id: str) -> bool:
        """Check whether a node can be scheduled."""
        func_name = "ExecutionState.is_ready"
        log_parameter(func_name, node_id=node_id, graph=graph)
        state = self._ensure_state(node_id)
        log_variable_change(func_name, "state", state)
        if state.status is not NodeStatus.PENDING:
            log_branch(func_name, "not_pending")
            return False
        log_branch(func_name, "pending")

        node = graph.nodes[node_id]
        log_variable_change(func_name, "node", node)
        if node.max_visits is not None and state.visits.count >= node.max_visits:
            log_branch(func_name, "visit_limit_reached")
            return False
        log_branch(func_name, "visit_limit_available")

        upstream_nodes = graph.upstream_nodes(node_id)
        log_variable_change(func_name, "upstream_nodes", upstream_nodes)
        if not upstream_nodes:
            log_branch(func_name, "no_upstream")
            return True

        if node.kind is NodeKind.AGGREGATE:
            log_branch(func_name, "aggregate_check")
            required_raw = node.config.get("required")
            log_variable_change(func_name, "required_raw", required_raw)
            if isinstance(required_raw, int) and required_raw > 0:
                required = required_raw
            else:
                required = len(upstream_nodes)
            log_variable_change(func_name, "required", required)
            completed_count = len(state.upstream_completed)
            log_variable_change(func_name, "completed_count", completed_count)
            if completed_count >= required:
                log_branch(func_name, "aggregate_ready")
                return True
            log_branch(func_name, "aggregate_waiting")
            return False

        completed_required = True
        log_variable_change(func_name, "completed_required", completed_required)
        for iteration, upstream in enumerate(upstream_nodes):
            log_loop_iteration(func_name, "upstream_required_check", iteration)
            if upstream.id not in state.upstream_completed:
                log_branch(func_name, "upstream_missing")
                completed_required = False
                log_variable_change(func_name, "completed_required", completed_required)
                break
        else:
            log_branch(func_name, "all_marked_complete")
            log_variable_change(func_name, "completed_required", completed_required)

        if completed_required:
            log_branch(func_name, "all_upstream_completed")
            return True

        if node.allow_partial_upstream:
            log_branch(func_name, "allow_partial")
            any_completed = False
            log_variable_change(func_name, "any_completed", any_completed)
            for iteration, upstream in enumerate(upstream_nodes):
                log_loop_iteration(func_name, "upstream_partial_check", iteration)
                if upstream.id in state.upstream_completed:
                    any_completed = True
                    log_variable_change(func_name, "any_completed", any_completed)
                    break
            log_variable_change(func_name, "any_completed", any_completed)
            return any_completed

        log_branch(func_name, "upstream_incomplete")
        return False

    def mark_running(self, node_id: str) -> None:
        """Transition a node into the running state.

        >>> runtime = ExecutionState()
        >>> runtime.mark_running("node-1")
        >>> runtime.snapshot()["states"]["node-1"]["status"]
        'running'
        """
        func_name = "ExecutionState.mark_running"
        log_parameter(func_name, node_id=node_id)
        state = self._ensure_state(node_id)
        log_variable_change(func_name, "state_before", state)
        state.status = NodeStatus.RUNNING
        log_variable_change(func_name, "state_after", state)

    def mark_complete(
        self,
        node_id: str,
        event_id: Optional[str],
        outcome: VisitOutcome,
    ) -> None:
        """Mark a node as completed successfully.

        >>> runtime = ExecutionState()
        >>> runtime.mark_complete(
        ...     "node-1",
        ...     event_id="evt-1",
        ...     outcome=VisitOutcome.success({"value": 42}),
        ... )
        >>> runtime.snapshot()["completed_nodes"]
        ['node-1']
        """
        func_name = "ExecutionState.mark_complete"
        log_parameter(func_name, node_id=node_id, event_id=event_id, outcome=outcome)
        state = self._ensure_state(node_id)
        log_variable_change(func_name, "state_before", state)
        state.status = NodeStatus.COMPLETED
        log_variable_change(func_name, "state_status", state.status)
        state.outcome = outcome
        log_variable_change(func_name, "state_outcome", state.outcome)
        state.last_payload = outcome.payload
        log_variable_change(func_name, "state_last_payload", state.last_payload)
        state.visits = state.visits.increment(event_id)
        log_variable_change(func_name, "state_visits", state.visits)
        self._completed_nodes.add(node_id)
        log_variable_change(func_name, "self._completed_nodes", self._completed_nodes)

    def mark_failed(
        self,
        node_id: str,
        event_id: Optional[str],
        outcome: VisitOutcome,
    ) -> None:
        """Mark a node as failed.

        >>> runtime = ExecutionState()
        >>> runtime.mark_failed(
        ...     "node-1",
        ...     event_id="evt-1",
        ...     outcome=VisitOutcome.failure("boom"),
        ... )
        >>> runtime.snapshot()["states"]["node-1"]["status"]
        'failed'
        """
        func_name = "ExecutionState.mark_failed"
        log_parameter(func_name, node_id=node_id, event_id=event_id, outcome=outcome)
        state = self._ensure_state(node_id)
        log_variable_change(func_name, "state_before", state)
        state.status = NodeStatus.FAILED
        log_variable_change(func_name, "state_status", state.status)
        state.outcome = outcome
        log_variable_change(func_name, "state_outcome", state.outcome)
        state.last_payload = outcome.payload
        log_variable_change(func_name, "state_last_payload", state.last_payload)
        state.visits = state.visits.increment(event_id)
        log_variable_change(func_name, "state_visits", state.visits)

    def reset_for_reentry(self, node_id: str) -> None:
        """Reset a node to pending so it can be scheduled again.

        >>> runtime = ExecutionState()
        >>> runtime.mark_complete("node-1", "evt-1", VisitOutcome.success("ok"))
        >>> before = runtime.snapshot()["states"]["node-1"]["visits"]["count"]
        >>> runtime.reset_for_reentry("node-1")
        >>> snapshot = runtime.snapshot()
        >>> snapshot["states"]["node-1"]["status"]
        'pending'
        >>> snapshot["states"]["node-1"]["upstream_completed"]
        []
        >>> snapshot["states"]["node-1"]["visits"]["count"] == before
        True
        >>> "node-1" in snapshot["completed_nodes"]
        False
        """
        func_name = "ExecutionState.reset_for_reentry"
        log_parameter(func_name, node_id=node_id)
        state = self._ensure_state(node_id)
        log_variable_change(func_name, "state_before", state)
        state.status = NodeStatus.PENDING
        log_variable_change(func_name, "state_status", state.status)
        state.upstream_completed.clear()
        log_variable_change(
            func_name, "state_upstream_completed", state.upstream_completed
        )
        if node_id in self._completed_nodes:
            log_branch(func_name, "remove_from_completed")
            self._completed_nodes.remove(node_id)
        else:
            log_branch(func_name, "not_in_completed")
        log_variable_change(func_name, "self._completed_nodes", self._completed_nodes)
        log_variable_change(func_name, "state_after", state)

    def note_upstream_completion(self, node_id: str, upstream_id: str) -> None:
        """Record that an upstream dependency has completed.

        >>> runtime = ExecutionState()
        >>> runtime.note_upstream_completion("node-1", "up-1")
        >>> runtime.snapshot()["states"]["node-1"]["upstream_completed"]
        ['up-1']
        """
        func_name = "ExecutionState.note_upstream_completion"
        log_parameter(func_name, node_id=node_id, upstream_id=upstream_id)
        state = self._ensure_state(node_id)
        log_variable_change(func_name, "state_before", state)
        state.upstream_completed.add(upstream_id)
        log_variable_change(func_name, "state_after", state)

    def snapshot(self) -> Dict[str, Any]:
        """Produce a JSON-serializable snapshot of execution state.

        >>> ExecutionState().snapshot()["snapshot_format_version"]
        2
        """
        func_name = "ExecutionState.snapshot"
        log_parameter(func_name)
        states_payload: Dict[str, Dict[str, Any]] = {}
        log_variable_change(func_name, "states_payload", states_payload)
        for iteration, (node_id, state) in enumerate(self._states.items()):
            log_loop_iteration(func_name, "states", iteration)
            states_payload[node_id] = state.to_dict()
            log_variable_change(
                func_name, f"states_payload[{node_id!r}]", states_payload[node_id]
            )
        payload = {
            "snapshot_format_version": SNAPSHOT_FORMAT_VERSION,
            "states": states_payload,
            "completed_nodes": sorted(self._completed_nodes),
        }
        log_variable_change(func_name, "payload", payload)
        return payload

    @classmethod
    def restore(cls, payload: Dict[str, Any]) -> "ExecutionState":
        """Restore execution state from a snapshot payload.

        >>> runtime = ExecutionState()
        >>> runtime.mark_complete(
        ...     "node-1",
        ...     event_id="evt-1",
        ...     outcome=VisitOutcome.success(),
        ... )
        >>> snapshot = runtime.snapshot()
        >>> restored = ExecutionState.restore(snapshot)
        >>> restored.snapshot() == snapshot
        True
        """
        func_name = "ExecutionState.restore"
        log_parameter(func_name, payload=payload)
        instance = cls()
        for iteration, (node_id, state_payload) in enumerate(
            payload.get("states", {}).items()
        ):
            log_loop_iteration(func_name, "states", iteration)
            state = NodeRuntimeState.from_dict(state_payload)
            log_variable_change(func_name, "restored_state", state)
            instance._states[node_id] = state
            log_variable_change(
                func_name, f"instance._states[{node_id!r}]", instance._states[node_id]
            )
        instance._completed_nodes = set(payload.get("completed_nodes", []))
        log_variable_change(
            func_name, "instance._completed_nodes", instance._completed_nodes
        )
        return instance
