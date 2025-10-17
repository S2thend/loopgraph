from __future__ import annotations

import asyncio

from eventflow.bus.eventbus import EventBus
from eventflow.concurrency import PrioritySemaphorePolicy
from eventflow.core.graph import Edge, Graph, Node
from eventflow.core.state import ExecutionState
from eventflow.core.types import EventType, NodeKind, NodeStatus, VisitOutcome
from eventflow.persistence import InMemoryEventLog, InMemorySnapshotStore
from eventflow.registry.function_registry import FunctionRegistry
from eventflow.scheduler.scheduler import Scheduler


def test_complex_workflow_with_switch_and_merge() -> None:
    registry = FunctionRegistry()

    def start_handler(_: object) -> dict[str, object]:
        return {"items": [1, 2, 3], "route": "process"}

    def switch_handler(payload: dict[str, object]) -> str:
        return payload.get("route", "skip")  # type: ignore[return-value]

    def process_handler(payload: dict[str, object]) -> dict[str, object]:
        items = payload.get("items", [])
        return {"processed": [item * 2 for item in items]}

    def audit_handler(_: dict[str, object]) -> dict[str, object]:
        return {"audit": "ok"}

    def merge_handler(payload: list[dict[str, object]]) -> dict[str, object]:
        combined: dict[str, object] = {}
        for entry in payload:
            combined.update(entry)
        return combined

    def final_handler(payload: dict[str, object]) -> str:
        processed = payload.get("processed")
        audit = payload.get("audit")
        return f"processed={processed} audit={audit}"

    registry.register("start", start_handler)
    registry.register("switch", switch_handler)
    registry.register("process", process_handler)
    registry.register("audit", audit_handler)
    registry.register("merge", merge_handler)
    registry.register("final", final_handler)

    graph = Graph(
        nodes={
            "start": Node(
                id="start",
                kind=NodeKind.TASK,
                handler="start",
                priority=0,
            ),
            "switch": Node(
                id="switch",
                kind=NodeKind.SWITCH,
                handler="switch",
                priority=0,
            ),
            "process": Node(
                id="process",
                kind=NodeKind.TASK,
                handler="process",
                priority=-5,
            ),
            "audit": Node(
                id="audit",
                kind=NodeKind.TASK,
                handler="audit",
                priority=5,
            ),
            "merge": Node(
                id="merge",
                kind=NodeKind.AGGREGATE,
                handler="merge",
                config={"required": 2},
                priority=0,
            ),
            "final": Node(
                id="final",
                kind=NodeKind.TASK,
                handler="final",
                priority=0,
            ),
        },
        edges={
            "start->switch": Edge(id="start->switch", source="start", target="switch"),
            "start->audit": Edge(id="start->audit", source="start", target="audit"),
            "start->process": Edge(id="start->process", source="start", target="process"),
            "switch->process": Edge(
                id="switch->process",
                source="switch",
                target="process",
                metadata={"route": "process"},
            ),
            "process->merge": Edge(id="process->merge", source="process", target="merge"),
            "audit->merge": Edge(id="audit->merge", source="audit", target="merge"),
            "merge->final": Edge(id="merge->final", source="merge", target="final"),
        },
    )

    bus = EventBus()
    concurrency_manager = PrioritySemaphorePolicy(limit=1)
    snapshot_store = InMemorySnapshotStore()
    event_log = InMemoryEventLog()

    scheduler = Scheduler(
        registry,
        bus,
        concurrency_manager,
        snapshot_store=snapshot_store,
        event_log=event_log,
    )

    results = asyncio.run(
        scheduler.run(graph, graph_id="integration", initial_payload=None)
    )

    assert results["start"] == {"items": [1, 2, 3], "route": "process"}
    assert results["process"] == {"processed": [2, 4, 6]}
    assert results["merge"] == {"processed": [2, 4, 6], "audit": "ok"}
    assert results["final"] == "processed=[2, 4, 6] audit=ok"

    snapshot = snapshot_store.load("integration")
    assert set(snapshot["completed_nodes"]) == {
        "start",
        "switch",
        "process",
        "audit",
        "merge",
        "final",
    }

    event_types = [event.type for event in event_log.iter("integration")]
    assert event_types.count(EventType.NODE_SCHEDULED) == 6
    assert event_types.count(EventType.NODE_COMPLETED) == 6


def test_loop_respects_max_visits() -> None:
    graph = Graph(
        nodes={
            "start": Node(id="start", kind=NodeKind.TASK, handler="start"),
            "loop": Node(
                id="loop",
                kind=NodeKind.TASK,
                handler="loop",
                max_visits=2,
                allow_partial_upstream=True,
            ),
            "switch": Node(id="switch", kind=NodeKind.SWITCH, handler="switch"),
            "exit": Node(id="exit", kind=NodeKind.TASK, handler="exit"),
        },
        edges={
            "switch->loop": Edge(
                id="switch->loop",
                source="switch",
                target="loop",
                metadata={"route": "loop"},
            ),
            "switch->exit": Edge(
                id="switch->exit",
                source="switch",
                target="exit",
                metadata={"route": "exit"},
            ),
        },
    )

    state = ExecutionState()
    for iteration in range(2):
        state.mark_running("loop")
        state.mark_complete(
            "loop", f"loop-{iteration}", VisitOutcome.success(iteration)
        )
        state.note_upstream_completion("switch", "loop")
        loop_state = state._ensure_state("loop")
        loop_state.status = NodeStatus.PENDING
        state._completed_nodes.discard("loop")

    assert not state.is_ready(graph, "loop")

    scheduler = Scheduler(FunctionRegistry(), EventBus(), PrioritySemaphorePolicy(1))
    selected = scheduler._determine_downstream_edges(
        graph=graph,
        node=graph.nodes["switch"],
        handler_result="loop",
        execution_state=state,
    )
    assert selected and selected[0].target == "exit"
