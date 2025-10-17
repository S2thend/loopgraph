"""Core scheduler for executing workflow graphs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .._debug import (
    log_branch,
    log_loop_iteration,
    log_parameter,
    log_variable_change,
)
from ..bus.eventbus import Event, EventBus
from ..concurrency import ConcurrencyManager, SemaphorePolicy
from ..core.graph import Edge, Graph, Node
from ..core.state import ExecutionState
from ..core.types import EventType, NodeKind, NodeStatus, VisitOutcome
from ..persistence import EventLog, SnapshotStore
from ..registry.function_registry import FunctionRegistry


class Scheduler:
    """Execute graphs by dispatching node handlers.

    >>> import asyncio
    >>> from eventflow.core.graph import Edge, Node, NodeKind
    >>> registry = FunctionRegistry()
    >>> registry.register("start", lambda payload: payload + ["start"])
    >>> registry.register("end", lambda payload: f"{payload}-done")
    >>> registry.register("branch", lambda payload: "right")
    >>> graph = Graph(
    ...     nodes={
    ...         "start": Node(id="start", kind=NodeKind.TASK, handler="start"),
    ...         "branch": Node(id="branch", kind=NodeKind.SWITCH, handler="branch"),
    ...         "end": Node(id="end", kind=NodeKind.TASK, handler="end"),
    ...     },
    ...     edges={
    ...         "e1": Edge(id="e1", source="start", target="branch"),
    ...         "e2": Edge(id="e2", source="branch", target="end", metadata={"route": "right"}),
    ...     },
    ... )
    >>> async def run() -> Dict[str, Any]:
    ...     bus = EventBus()
    ...     policy = SemaphorePolicy(limit=2)
    ...     scheduler = Scheduler(registry, bus, policy)
    ...     results = await scheduler.run(graph, initial_payload=[])
    ...     return results
    >>> asyncio.run(run())
    {'start': ['start'], 'branch': 'right', 'end': 'right-done'}
    >>> from eventflow.core.types import EventType
    >>> from eventflow.persistence import InMemoryEventLog, InMemorySnapshotStore
    >>> async def run_with_persistence() -> Dict[str, Any]:
    ...     bus = EventBus()
    ...     policy = SemaphorePolicy(limit=2)
    ...     store = InMemorySnapshotStore()
    ...     event_log = InMemoryEventLog()
    ...     scheduler = Scheduler(
    ...         registry,
    ...         bus,
    ...         policy,
    ...         snapshot_store=store,
    ...         event_log=event_log,
    ...     )
    ...     await scheduler.run(graph, graph_id="demo", initial_payload=[])
    ...     snapshot = store.load("demo")
    ...     event_types = [evt.type.name for evt in event_log.iter("demo")]
    ...     return {
    ...         "completed": snapshot["completed_nodes"],
    ...         "events": event_types,
    ...     }
    >>> asyncio.run(run_with_persistence())
    {'completed': ['branch', 'end', 'start'], 'events': ['NODE_SCHEDULED', 'NODE_COMPLETED', 'NODE_SCHEDULED', 'NODE_COMPLETED', 'NODE_SCHEDULED', 'NODE_COMPLETED']}
    """

    def __init__(
        self,
        registry: FunctionRegistry,
        event_bus: EventBus,
        concurrency_manager: ConcurrencyManager,
        *,
        snapshot_store: Optional[SnapshotStore] = None,
        event_log: Optional[EventLog] = None,
    ) -> None:
        func_name = "Scheduler.__init__"
        log_parameter(
            func_name,
            registry=registry,
            event_bus=event_bus,
            snapshot_store=snapshot_store,
            event_log=event_log,
        )
        self._registry = registry
        log_variable_change(func_name, "self._registry", self._registry)
        self._event_bus = event_bus
        log_variable_change(func_name, "self._event_bus", self._event_bus)
        self._concurrency_manager = concurrency_manager
        log_variable_change(
            func_name, "self._concurrency_manager", self._concurrency_manager
        )
        self._uses_default_semaphore = isinstance(
            self._concurrency_manager, SemaphorePolicy
        )
        log_variable_change(
            func_name, "self._uses_default_semaphore", self._uses_default_semaphore
        )
        self._event_counter = 0
        log_variable_change(func_name, "self._event_counter", self._event_counter)
        self._snapshot_store = snapshot_store
        log_variable_change(func_name, "self._snapshot_store", self._snapshot_store)
        self._event_log = event_log
        log_variable_change(func_name, "self._event_log", self._event_log)

    async def run(
        self,
        graph: Graph,
        *,
        graph_id: str = "graph",
        initial_payload: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Execute nodes in the graph until completion."""
        func_name = "Scheduler.run"
        log_parameter(
            func_name,
            graph=graph,
            graph_id=graph_id,
            initial_payload=initial_payload,
        )
        execution_state = self._load_or_create_state(graph_id)
        log_variable_change(func_name, "execution_state", execution_state)
        snapshot_data = execution_state.snapshot()
        log_variable_change(func_name, "snapshot_data", snapshot_data)
        results = self._initial_results_from_snapshot(snapshot_data)
        log_variable_change(func_name, "results", results)
        completed_nodes = set(snapshot_data["completed_nodes"])
        log_variable_change(func_name, "completed_nodes", completed_nodes)
        pending = {node_id for node_id in graph.nodes if node_id not in completed_nodes}
        log_variable_change(func_name, "pending", pending)
        loop_iteration = 0
        while pending:
            log_loop_iteration(func_name, "pending_loop", loop_iteration)
            loop_iteration += 1
            progressed = False
            log_variable_change(func_name, "progressed", progressed)
            for iteration, node_id in enumerate(list(pending)):
                log_loop_iteration(func_name, "pending_nodes", iteration)
                if not execution_state.is_ready(graph, node_id):
                    log_branch(func_name, "node_not_ready")
                    continue
                log_branch(func_name, "node_ready")
                progressed = True
                log_variable_change(func_name, "progressed", progressed)
                node = graph.nodes[node_id]
                log_variable_change(func_name, "node", node)
                execution_state.mark_running(node_id)
                event_id = self._next_event_id(node_id)
                log_variable_change(func_name, "event_id", event_id)
                input_payload = self._build_input_payload(
                    graph=graph,
                    node=node,
                    results=results,
                    initial_payload=initial_payload,
                )
                log_variable_change(func_name, "input_payload", input_payload)
                await self._dispatch_event(
                    Event(
                        id=event_id,
                        graph_id=graph_id,
                        node_id=node_id,
                        type=EventType.NODE_SCHEDULED,
                        payload=input_payload,
                        status=NodeStatus.RUNNING,
                    )
                )
                handler_result = await self._execute_node(
                    node=node,
                    graph=graph,
                    execution_state=execution_state,
                    graph_id=graph_id,
                    upstream_payload=input_payload,
                )
                log_variable_change(func_name, "handler_result", handler_result)
                results[node_id] = handler_result
                log_variable_change(func_name, "results", results)
                pending.remove(node_id)
                log_variable_change(func_name, "pending", pending)
            if not progressed:
                log_branch(func_name, "no_progress")
                raise RuntimeError("Scheduler could not make progress")
        log_branch(func_name, "completed")
        self._persist_snapshot(execution_state, graph_id)
        return results

    def _next_event_id(self, node_id: str) -> str:
        """Produce a unique event identifier."""
        func_name = "Scheduler._next_event_id"
        log_parameter(func_name, node_id=node_id)
        self._event_counter += 1
        log_variable_change(func_name, "self._event_counter", self._event_counter)
        event_id = f"{node_id}-{self._event_counter}"
        log_variable_change(func_name, "event_id", event_id)
        return event_id

    async def _execute_node(
        self,
        node: Node,
        graph: Graph,
        execution_state: ExecutionState,
        graph_id: str,
        upstream_payload: Optional[Any],
    ) -> Any:
        """Execute a single node handler."""
        func_name = "Scheduler._execute_node"
        log_parameter(
            func_name, node=node, graph=graph, upstream_payload=upstream_payload
        )
        priority = node.priority
        log_variable_change(func_name, "priority", priority)
        async with self._concurrency_manager.slot(node.id, priority=priority):
            log_branch(func_name, "acquired_slot")
            try:
                result = await self._registry.execute(node.handler, upstream_payload)
                log_variable_change(func_name, "result", result)
            except Exception as exc:  # pragma: no cover - explicit failure path
                log_branch(func_name, "handler_failed")
                outcome = VisitOutcome.failure(str(exc))
                log_variable_change(func_name, "outcome", outcome)
                event_id = self._next_event_id(node.id)
                log_variable_change(func_name, "event_id", event_id)
                execution_state.mark_failed(node.id, event_id, outcome)
                await self._dispatch_event(
                    Event(
                        id=event_id,
                        graph_id=graph_id,
                        node_id=node.id,
                        type=EventType.NODE_FAILED,
                        payload={"error": str(exc)},
                        status=NodeStatus.FAILED,
                    )
                )
                self._persist_snapshot(execution_state, graph_id)
                raise
            outcome = VisitOutcome.success(result)
            log_variable_change(func_name, "outcome", outcome)
            event_id = self._next_event_id(node.id)
            log_variable_change(func_name, "event_id", event_id)
            execution_state.mark_complete(node.id, event_id, outcome)
            await self._dispatch_event(
                Event(
                    id=event_id,
                    graph_id=graph_id,
                    node_id=node.id,
                    type=EventType.NODE_COMPLETED,
                    payload=result,
                    status=NodeStatus.COMPLETED,
                    visit_count=execution_state.snapshot()["states"][node.id]["visits"][
                        "count"
                    ],
                )
            )
            selected_edges = self._determine_downstream_edges(
                graph=graph,
                node=node,
                handler_result=result,
            )
            log_variable_change(func_name, "selected_edges", selected_edges)
            for iteration, edge in enumerate(selected_edges):
                log_loop_iteration(func_name, "downstream_edges", iteration)
                log_variable_change(func_name, "edge", edge)
                downstream = graph.nodes[edge.target]
                log_variable_change(func_name, "downstream", downstream)
                execution_state.note_upstream_completion(downstream.id, node.id)
            self._persist_snapshot(execution_state, graph_id)
            return result

    def _build_input_payload(
        self,
        graph: Graph,
        node: Node,
        results: Dict[str, Any],
        initial_payload: Optional[Any],
    ) -> Optional[Any]:
        """Determine the payload supplied to a handler based on upstream results."""

        func_name = "Scheduler._build_input_payload"
        log_parameter(
            func_name,
            graph=graph,
            node=node,
            results=results,
            initial_payload=initial_payload,
        )
        upstream_nodes = graph.upstream_nodes(node.id)
        log_variable_change(func_name, "upstream_nodes", upstream_nodes)
        if not upstream_nodes:
            log_branch(func_name, "no_upstream")
            log_variable_change(func_name, "payload", initial_payload)
            return initial_payload

        if node.kind is NodeKind.AGGREGATE:
            log_branch(func_name, "aggregate_payload")
            aggregated: List[Any] = []
            log_variable_change(func_name, "aggregated", aggregated)
            for iteration, upstream in enumerate(upstream_nodes):
                log_loop_iteration(func_name, "aggregate_upstream", iteration)
                if upstream.id in results:
                    aggregated.append(results[upstream.id])
                    log_variable_change(
                        func_name, "aggregated", list(aggregated)
                    )
            log_variable_change(func_name, "payload", aggregated)
            return aggregated

        upstream_id = upstream_nodes[0].id
        log_variable_change(func_name, "upstream_id", upstream_id)
        payload = results.get(upstream_id)
        log_variable_change(func_name, "payload", payload)
        return payload

    def _determine_downstream_edges(
        self,
        graph: Graph,
        node: Node,
        handler_result: Any,
    ) -> List[Edge]:
        """Select downstream edges to activate after a node completes."""

        func_name = "Scheduler._determine_downstream_edges"
        log_parameter(
            func_name,
            graph=graph,
            node=node,
            handler_result=handler_result,
        )
        edges = graph.downstream_edges(node.id)
        log_variable_change(func_name, "edges", edges)
        if node.kind is not NodeKind.SWITCH:
            log_branch(func_name, "non_switch")
            return edges

        log_branch(func_name, "switch_node")
        if not isinstance(handler_result, str):
            log_branch(func_name, "invalid_route_type")
            raise ValueError(
                f"Switch handler for node '{node.id}' must return a string route"
            )
        route = handler_result
        log_variable_change(func_name, "route", route)
        selected: List[Edge] = []
        log_variable_change(func_name, "selected", selected)
        for iteration, edge in enumerate(edges):
            log_loop_iteration(func_name, "switch_edges", iteration)
            metadata_route = edge.metadata.get("route")
            log_variable_change(func_name, "metadata_route", metadata_route)
            if metadata_route == route:
                selected.append(edge)
                log_variable_change(func_name, "selected", list(selected))
        log_variable_change(func_name, "selected_final", selected)
        return selected

    def _load_or_create_state(self, graph_id: str) -> ExecutionState:
        """Retrieve execution state from snapshots if available."""

        func_name = "Scheduler._load_or_create_state"
        log_parameter(func_name, graph_id=graph_id)
        if not self._snapshot_store:
            log_branch(func_name, "no_snapshot_store")
            state = ExecutionState()
            log_variable_change(func_name, "state", state)
            return state

        try:
            snapshot_payload = self._snapshot_store.load(graph_id)
        except KeyError:
            log_branch(func_name, "snapshot_missing")
            state = ExecutionState()
        else:
            log_branch(func_name, "snapshot_loaded")
            state = ExecutionState.restore(dict(snapshot_payload))
        log_variable_change(func_name, "state", state)
        return state

    def _initial_results_from_snapshot(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """Extract node results from a snapshot payload."""

        func_name = "Scheduler._initial_results_from_snapshot"
        log_parameter(func_name, snapshot=snapshot)
        results: Dict[str, Any] = {}
        log_variable_change(func_name, "results", results)
        states = snapshot.get("states", {})
        log_variable_change(func_name, "states", states)
        for iteration, (node_id, node_state) in enumerate(states.items()):
            log_loop_iteration(func_name, "states", iteration)
            status_value = node_state.get("status")
            log_variable_change(func_name, "status_value", status_value)
            if status_value == NodeStatus.COMPLETED.value:
                payload = node_state.get("last_payload")
                log_variable_change(func_name, "payload", payload)
                if payload is not None:
                    results[node_id] = payload
                    log_variable_change(
                        func_name, f"results[{node_id!r}]", results[node_id]
                    )
        log_variable_change(func_name, "results_final", results)
        return results

    def _persist_snapshot(
        self, execution_state: ExecutionState, graph_id: str
    ) -> None:
        """Persist execution state snapshot if a store is configured."""

        func_name = "Scheduler._persist_snapshot"
        log_parameter(func_name, graph_id=graph_id)
        if not self._snapshot_store:
            log_branch(func_name, "no_snapshot_store")
            return
        snapshot = execution_state.snapshot()
        log_variable_change(func_name, "snapshot", snapshot)
        self._snapshot_store.save(graph_id, snapshot)
        log_branch(func_name, "snapshot_saved")

    async def _dispatch_event(self, event: Event) -> None:
        """Append an event to the log and publish it on the bus."""

        func_name = "Scheduler._dispatch_event"
        log_parameter(func_name, event=event)
        if self._event_log:
            self._event_log.append(event)
            log_branch(func_name, "event_logged")
        else:
            log_branch(func_name, "no_event_log")
        await self._event_bus.emit(event)
