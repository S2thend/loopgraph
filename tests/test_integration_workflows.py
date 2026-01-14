from __future__ import annotations

import asyncio
from typing import Iterable, cast

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
        values = payload.get("items", [])
        items = values if isinstance(values, list) else []
        doubled = [int(item) * 2 for item in items]
        return {"processed": doubled}

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
    completed = set(cast(Iterable[str], snapshot.get("completed_nodes", [])))
    assert completed == {
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


def test_global_concurrency_across_schedulers() -> None:
    policy = PrioritySemaphorePolicy(limit=1)
    bus = EventBus()

    registry_a = FunctionRegistry()
    registry_b = FunctionRegistry()

    order: list[str] = []

    async def worker(name: str) -> str:
        order.append(f"start-{name}")
        await asyncio.sleep(0.01)
        order.append(f"end-{name}")
        return name

    registry_a.register("task", lambda _: worker("A"))
    registry_b.register("task", lambda _: worker("B"))

    graph = Graph(
        nodes={"task": Node(id="task", kind=NodeKind.TASK, handler="task")},
        edges={},
    )

    scheduler_a = Scheduler(registry_a, bus, policy)
    scheduler_b = Scheduler(registry_b, bus, policy)

    async def run_all() -> None:
        await asyncio.gather(
            scheduler_a.run(graph, graph_id="A"),
            scheduler_b.run(graph, graph_id="B"),
        )

    asyncio.run(run_all())

    assert order == ["start-A", "end-A", "start-B", "end-B"] or order == [
        "start-B",
        "end-B",
        "start-A",
        "end-A",
    ]


def test_payload_propagation_between_nodes() -> None:
    registry = FunctionRegistry()

    def start_handler(_: object) -> dict[str, object]:
        return {"numbers": [1, 2], "meta": {"source": "start"}}

    def transform_handler(payload: dict[str, object]) -> dict[str, object]:
        numbers = payload.get("numbers", [])
        items = numbers if isinstance(numbers, list) else []
        doubled = [int(value) * 2 for value in items]
        meta = payload.get("meta", {})
        meta_copy = dict(cast(dict[str, object], meta))
        meta_copy["transformed"] = True
        return {"numbers": doubled, "meta": meta_copy}

    def final_handler(payload: dict[str, object]) -> list[int]:
        numbers = payload.get("numbers", [])
        return cast(list[int], numbers)

    registry.register("start", start_handler)
    registry.register("transform", transform_handler)
    registry.register("final", final_handler)

    graph = Graph(
        nodes={
            "start": Node(id="start", kind=NodeKind.TASK, handler="start"),
            "transform": Node(id="transform", kind=NodeKind.TASK, handler="transform"),
            "final": Node(id="final", kind=NodeKind.TASK, handler="final"),
        },
        edges={
            "start->transform": Edge(id="start->transform", source="start", target="transform"),
            "transform->final": Edge(id="transform->final", source="transform", target="final"),
        },
    )

    scheduler = Scheduler(registry, EventBus(), PrioritySemaphorePolicy(limit=1))
    results = asyncio.run(scheduler.run(graph, initial_payload=None))

    assert results["final"] == [2, 4]
