"""Core scheduler for executing workflow graphs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .._debug import (
    log_branch,
    log_loop_iteration,
    log_parameter,
    log_variable_change,
)
from ..bus.eventbus import Event, EventBus
from ..concurrency import ConcurrencyManager, SemaphorePolicy
from ..core.graph import Edge, Graph, Node
from ..core.state import SNAPSHOT_FORMAT_VERSION, ExecutionState
from ..core.types import EventType, NodeKind, NodeStatus, VisitOutcome
from ..persistence import EventLog, SnapshotStore
from ..registry.function_registry import FunctionRegistry

SUPPORTED_SNAPSHOT_FORMAT_VERSION = SNAPSHOT_FORMAT_VERSION


class Scheduler:
    """Execute graphs by dispatching node handlers.

    >>> import asyncio
    >>> from loopgraph.core.graph import Edge, Node, NodeKind
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
    >>> from loopgraph.core.types import EventType
    >>> from loopgraph.persistence import InMemoryEventLog, InMemorySnapshotStore
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

    Loop re-entry is supported when a SWITCH routes to an already-completed node
    that still has visit capacity.

    >>> loop_registry = FunctionRegistry()
    >>> loop_counter = {"count": 0}
    >>> def loop_handler(_: object) -> dict[str, int]:
    ...     loop_counter["count"] += 1
    ...     return {"iteration": loop_counter["count"]}
    >>> def switch_handler(payload: dict[str, int]) -> str:
    ...     if payload["iteration"] < 2:
    ...         return "continue"
    ...     return "done"
    >>> loop_registry.register("start", lambda _: None)
    >>> loop_registry.register("loop", loop_handler)
    >>> loop_registry.register("switch", switch_handler)
    >>> loop_registry.register("out", lambda payload: payload)
    >>> loop_graph = Graph(
    ...     nodes={
    ...         "start": Node(id="start", kind=NodeKind.TASK, handler="start"),
    ...         "loop": Node(
    ...             id="loop",
    ...             kind=NodeKind.TASK,
    ...             handler="loop",
    ...             max_visits=2,
    ...             allow_partial_upstream=True,
    ...         ),
    ...         "switch": Node(id="switch", kind=NodeKind.SWITCH, handler="switch"),
    ...         "out": Node(id="out", kind=NodeKind.TASK, handler="out"),
    ...     },
    ...     edges={
    ...         "start->loop": Edge(id="start->loop", source="start", target="loop"),
    ...         "loop->switch": Edge(id="loop->switch", source="loop", target="switch"),
    ...         "switch->loop": Edge(
    ...             id="switch->loop",
    ...             source="switch",
    ...             target="loop",
    ...             metadata={"route": "continue"},
    ...         ),
    ...         "switch->out": Edge(
    ...             id="switch->out",
    ...             source="switch",
    ...             target="out",
    ...             metadata={"route": "done"},
    ...         ),
    ...     },
    ... )
    >>> async def run_loop() -> Dict[str, Any]:
    ...     scheduler = Scheduler(loop_registry, EventBus(), SemaphorePolicy(limit=1))
    ...     return await scheduler.run(loop_graph)
    >>> asyncio.run(run_loop())["out"]
    'done'
    >>> loop_counter["count"]
    2
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
        execution_state, resumed_from_snapshot = self._load_or_create_state(graph_id)
        log_variable_change(func_name, "execution_state", execution_state)
        log_variable_change(func_name, "resumed_from_snapshot", resumed_from_snapshot)
        snapshot_data = execution_state.snapshot()
        log_variable_change(func_name, "snapshot_data", snapshot_data)
        results = self._initial_results_from_snapshot(snapshot_data)
        log_variable_change(func_name, "results", results)
        completed_nodes = set(snapshot_data["completed_nodes"])
        log_variable_change(func_name, "completed_nodes", completed_nodes)
        if resumed_from_snapshot:
            log_branch(func_name, "supported_snapshot_resume")
            pending = self._seed_pending_from_supported_snapshot(
                graph=graph,
                snapshot_data=snapshot_data,
                completed_nodes=completed_nodes,
            )
        else:
            log_branch(func_name, "fresh_run")
            pending = self._seed_pending_from_entry_nodes(
                graph=graph,
                completed_nodes=completed_nodes,
            )
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
                (
                    handler_result,
                    reentry_targets,
                    activated_targets,
                ) = await self._execute_node(
                    node=node,
                    graph=graph,
                    execution_state=execution_state,
                    graph_id=graph_id,
                    upstream_payload=input_payload,
                )
                log_variable_change(func_name, "handler_result", handler_result)
                log_variable_change(func_name, "reentry_targets", reentry_targets)
                log_variable_change(func_name, "activated_targets", activated_targets)
                results[node_id] = handler_result
                log_variable_change(func_name, "results", results)
                completed_nodes.add(node_id)
                log_variable_change(func_name, "completed_nodes", completed_nodes)
                pending.remove(node_id)
                log_variable_change(func_name, "pending", pending)
                for (
                    activated_iteration,
                    activated_target,
                ) in enumerate(activated_targets):
                    log_loop_iteration(
                        func_name, "activated_targets", activated_iteration
                    )
                    if activated_target in completed_nodes:
                        log_branch(func_name, "activated_target_completed")
                        continue
                    log_branch(func_name, "activated_target_pending")
                    pending.add(activated_target)
                    log_variable_change(
                        func_name,
                        f"pending_with_activated_{activated_target}",
                        pending,
                    )
                for reentry_iteration, reentry_target in enumerate(reentry_targets):
                    log_loop_iteration(func_name, "reentry_targets", reentry_iteration)
                    completed_nodes.discard(reentry_target)
                    log_variable_change(func_name, "completed_nodes", completed_nodes)
                    pending.add(reentry_target)
                    log_variable_change(
                        func_name,
                        f"pending_with_reentry_{reentry_target}",
                        pending,
                    )
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
    ) -> Tuple[Any, List[str], List[str]]:
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
                execution_state=execution_state,
            )
            log_variable_change(func_name, "selected_edges", selected_edges)
            reentry_targets: List[str] = []
            log_variable_change(func_name, "reentry_targets", reentry_targets)
            activated_targets: List[str] = []
            log_variable_change(func_name, "activated_targets", activated_targets)
            for iteration, edge in enumerate(selected_edges):
                log_loop_iteration(func_name, "downstream_edges", iteration)
                log_variable_change(func_name, "edge", edge)
                downstream = graph.nodes[edge.target]
                log_variable_change(func_name, "downstream", downstream)
                downstream_state = execution_state._ensure_state(downstream.id)
                log_variable_change(func_name, "downstream_state", downstream_state)
                downstream_status = downstream_state.status
                log_variable_change(func_name, "downstream_status", downstream_status)
                downstream_visits = downstream_state.visits.count
                log_variable_change(func_name, "downstream_visits", downstream_visits)
                if downstream_status is NodeStatus.COMPLETED:
                    has_remaining_visits = self._has_remaining_visits(
                        graph=graph,
                        execution_state=execution_state,
                        node_id=downstream.id,
                    )
                    log_variable_change(
                        func_name, "has_remaining_visits", has_remaining_visits
                    )
                    if has_remaining_visits:
                        log_branch(func_name, "reentry_reset_completed")
                        execution_state.reset_for_reentry(downstream.id)
                        reentry_targets.append(downstream.id)
                        log_variable_change(
                            func_name,
                            "reentry_targets",
                            list(reentry_targets),
                        )
                    else:
                        log_branch(func_name, "reentry_completed_exhausted")
                elif downstream_status is NodeStatus.FAILED:
                    log_branch(func_name, "reentry_failed_skip")
                elif downstream_visits == 0 and downstream_status is NodeStatus.PENDING:
                    log_branch(func_name, "initial_pending_target")
                    activated_targets.append(downstream.id)
                    log_variable_change(
                        func_name,
                        "activated_targets",
                        list(activated_targets),
                    )
                else:
                    log_branch(func_name, "reentry_non_terminal_error")
                    raise RuntimeError(
                        "Encountered non-terminal re-entry target "
                        f"'{downstream.id}' in state '{downstream_status.value}'"
                    )
                execution_state.note_upstream_completion(downstream.id, node.id)
            self._persist_snapshot(execution_state, graph_id)
            return result, reentry_targets, activated_targets

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
                    log_variable_change(func_name, "aggregated", list(aggregated))
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
        execution_state: ExecutionState,
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
        exit_edges: List[Edge] = []
        log_variable_change(func_name, "selected", selected)
        for iteration, edge in enumerate(edges):
            log_loop_iteration(func_name, "switch_edges", iteration)
            metadata_route = edge.metadata.get("route")
            log_variable_change(func_name, "metadata_route", metadata_route)
            if metadata_route == route:
                has_capacity = self._has_remaining_visits(
                    graph, execution_state, edge.target
                )
                log_variable_change(func_name, "has_capacity", has_capacity)
                if has_capacity:
                    selected.append(edge)
                    log_variable_change(func_name, "selected", list(selected))
                else:
                    log_branch(func_name, "target_exhausted")
            if metadata_route == "exit":
                exit_edges.append(edge)
                log_variable_change(func_name, "exit_edges", list(exit_edges))

        if selected:
            log_variable_change(func_name, "selected_final", selected)
            return selected
        if exit_edges:
            log_branch(func_name, "fallback_exit")
            return exit_edges
        log_branch(func_name, "no_matching_edge")
        raise ValueError(
            f"Switch node '{node.id}' returned unmatched route {route!r} with no fallback edge"
        )

    def _has_remaining_visits(
        self, graph: Graph, execution_state: ExecutionState, node_id: str
    ) -> bool:
        func_name = "Scheduler._has_remaining_visits"
        log_parameter(func_name, node_id=node_id)
        node = graph.nodes[node_id]
        log_variable_change(func_name, "node", node)
        if node.max_visits is None:
            log_branch(func_name, "no_visit_limit")
            return True
        state = execution_state._ensure_state(node_id)
        visits = state.visits.count
        log_variable_change(func_name, "visits", visits)
        has_capacity = visits < node.max_visits
        log_variable_change(func_name, "has_capacity", has_capacity)
        return has_capacity

    def _load_or_create_state(self, graph_id: str) -> Tuple[ExecutionState, bool]:
        """Retrieve execution state from snapshots if available."""

        func_name = "Scheduler._load_or_create_state"
        log_parameter(func_name, graph_id=graph_id)
        if not self._snapshot_store:
            log_branch(func_name, "no_snapshot_store")
            state = ExecutionState()
            log_variable_change(func_name, "state", state)
            return state, False

        try:
            snapshot_payload = self._snapshot_store.load(graph_id)
        except KeyError:
            log_branch(func_name, "snapshot_missing")
            state = ExecutionState()
            resumed_from_snapshot = False
        else:
            log_branch(func_name, "snapshot_loaded")
            log_variable_change(func_name, "snapshot_payload", snapshot_payload)
            snapshot_dict = dict(snapshot_payload)
            log_variable_change(func_name, "snapshot_dict", snapshot_dict)
            self._validate_snapshot_format(snapshot_dict)
            state = ExecutionState.restore(snapshot_dict)
            self._reset_running_nodes_for_resume(
                execution_state=state,
                snapshot_data=snapshot_dict,
            )
            resumed_from_snapshot = True
        log_variable_change(func_name, "state", state)
        log_variable_change(
            func_name, "resumed_from_snapshot", resumed_from_snapshot
        )
        return state, resumed_from_snapshot

    def _validate_snapshot_format(self, snapshot_data: Dict[str, Any]) -> None:
        """Reject unsupported snapshot payloads before restore."""

        func_name = "Scheduler._validate_snapshot_format"
        log_parameter(func_name, snapshot_data=snapshot_data)
        version = snapshot_data.get("snapshot_format_version")
        log_variable_change(func_name, "version", version)
        log_variable_change(
            func_name,
            "supported_version",
            SUPPORTED_SNAPSHOT_FORMAT_VERSION,
        )
        if version == SUPPORTED_SNAPSHOT_FORMAT_VERSION:
            log_branch(func_name, "supported_version")
            return
        log_branch(func_name, "unsupported_version")
        raise ValueError(
            "Unsupported snapshot format version "
            f"{version!r}; supported version is "
            f"{SUPPORTED_SNAPSHOT_FORMAT_VERSION}. "
            "Discard or migrate the snapshot before resuming."
        )

    def _reset_running_nodes_for_resume(
        self,
        *,
        execution_state: ExecutionState,
        snapshot_data: Dict[str, Any],
    ) -> None:
        """Reset RUNNING snapshot nodes to PENDING before scheduling."""

        func_name = "Scheduler._reset_running_nodes_for_resume"
        log_parameter(
            func_name,
            execution_state=execution_state,
            snapshot_data=snapshot_data,
        )
        for iteration, (node_id, node_state) in enumerate(
            snapshot_data.get("states", {}).items()
        ):
            log_loop_iteration(func_name, "states", iteration)
            status_value = node_state.get("status")
            log_variable_change(func_name, "status_value", status_value)
            if status_value != NodeStatus.RUNNING.value:
                log_branch(func_name, "state_not_running")
                continue
            log_branch(func_name, "reset_running_to_pending")
            state = execution_state._ensure_state(node_id)
            log_variable_change(func_name, "state_before", state)
            state.status = NodeStatus.PENDING
            log_variable_change(func_name, "state_after", state)

    def _seed_pending_from_entry_nodes(
        self,
        *,
        graph: Graph,
        completed_nodes: set[str],
    ) -> set[str]:
        """Seed a fresh run from entry nodes only."""

        func_name = "Scheduler._seed_pending_from_entry_nodes"
        log_parameter(func_name, graph=graph, completed_nodes=completed_nodes)
        entry_nodes = graph.entry_nodes()
        log_variable_change(func_name, "entry_nodes", entry_nodes)
        entry_ids = {node.id for node in entry_nodes}
        log_variable_change(func_name, "entry_ids", entry_ids)
        if graph.nodes and not entry_ids:
            log_branch(func_name, "no_entry_nodes")
            raise ValueError("Graph has no entry nodes (nodes with no upstream edges)")
        log_branch(func_name, "seed_from_entries")
        pending = {node_id for node_id in entry_ids if node_id not in completed_nodes}
        log_variable_change(func_name, "pending", pending)
        return pending

    def _seed_pending_from_supported_snapshot(
        self,
        *,
        graph: Graph,
        snapshot_data: Dict[str, Any],
        completed_nodes: set[str],
    ) -> set[str]:
        """Seed a resumed run from supported snapshot state plus entry nodes."""

        func_name = "Scheduler._seed_pending_from_supported_snapshot"
        log_parameter(
            func_name,
            graph=graph,
            snapshot_data=snapshot_data,
            completed_nodes=completed_nodes,
        )
        pending: set[str] = set()
        log_variable_change(func_name, "pending", pending)
        for iteration, node in enumerate(graph.entry_nodes()):
            log_loop_iteration(func_name, "entry_nodes", iteration)
            if node.id in completed_nodes:
                log_branch(func_name, "entry_completed")
                continue
            log_branch(func_name, "entry_pending")
            pending.add(node.id)
            log_variable_change(func_name, "pending", pending)
        for iteration, (node_id, node_state) in enumerate(
            snapshot_data.get("states", {}).items()
        ):
            log_loop_iteration(func_name, "snapshot_states", iteration)
            status_value = node_state.get("status")
            log_variable_change(func_name, "status_value", status_value)
            if node_id in completed_nodes:
                log_branch(func_name, "snapshot_node_completed")
                continue
            if status_value not in (
                NodeStatus.PENDING.value,
                NodeStatus.RUNNING.value,
            ):
                log_branch(func_name, "snapshot_node_not_activated")
                continue
            log_branch(func_name, "snapshot_node_pending")
            pending.add(node_id)
            log_variable_change(func_name, "pending", pending)
        return pending

    def _initial_results_from_snapshot(
        self, snapshot: Dict[str, Any]
    ) -> Dict[str, Any]:
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

    def _persist_snapshot(self, execution_state: ExecutionState, graph_id: str) -> None:
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
