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
from ..concurrency.policies import SemaphorePolicy
from ..core.graph import Edge, Graph, Node
from ..core.state import ExecutionState
from ..core.types import EventType, NodeKind, NodeStatus, VisitOutcome
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
    """

    def __init__(
        self,
        registry: FunctionRegistry,
        event_bus: EventBus,
        concurrency_policy: SemaphorePolicy,
    ) -> None:
        func_name = "Scheduler.__init__"
        log_parameter(func_name, registry=registry, event_bus=event_bus)
        self._registry = registry
        log_variable_change(func_name, "self._registry", self._registry)
        self._event_bus = event_bus
        log_variable_change(func_name, "self._event_bus", self._event_bus)
        self._concurrency_policy = concurrency_policy
        log_variable_change(
            func_name, "self._concurrency_policy", self._concurrency_policy
        )
        self._event_counter = 0
        log_variable_change(func_name, "self._event_counter", self._event_counter)

    async def run(
        self,
        graph: Graph,
        initial_payload: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Execute nodes in the graph until completion."""
        func_name = "Scheduler.run"
        log_parameter(func_name, graph=graph, initial_payload=initial_payload)
        execution_state = ExecutionState()
        log_variable_change(func_name, "execution_state", execution_state)
        pending = set(graph.nodes.keys())
        log_variable_change(func_name, "pending", pending)
        results: Dict[str, Any] = {}
        log_variable_change(func_name, "results", results)
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
                await self._event_bus.emit(
                    Event(
                        id=event_id,
                        graph_id="graph",
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
        upstream_payload: Optional[Any],
    ) -> Any:
        """Execute a single node handler."""
        func_name = "Scheduler._execute_node"
        log_parameter(
            func_name, node=node, graph=graph, upstream_payload=upstream_payload
        )
        async with self._concurrency_policy.slot():
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
                await self._event_bus.emit(
                    Event(
                        id=event_id,
                        graph_id="graph",
                        node_id=node.id,
                        type=EventType.NODE_FAILED,
                        payload={"error": str(exc)},
                        status=NodeStatus.FAILED,
                    )
                )
                raise
            outcome = VisitOutcome.success(result)
            log_variable_change(func_name, "outcome", outcome)
            event_id = self._next_event_id(node.id)
            log_variable_change(func_name, "event_id", event_id)
            execution_state.mark_complete(node.id, event_id, outcome)
            await self._event_bus.emit(
                Event(
                    id=event_id,
                    graph_id="graph",
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
