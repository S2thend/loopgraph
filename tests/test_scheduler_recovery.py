from __future__ import annotations

import asyncio

from eventflow import log_parameter, log_variable_change
from eventflow.bus.eventbus import EventBus
from eventflow.concurrency.policies import SemaphorePolicy
from eventflow.core.graph import Edge, Graph, Node
from eventflow.core.state import ExecutionState
from eventflow.core.types import EventType, NodeKind, VisitOutcome
from eventflow.persistence import InMemoryEventLog, InMemorySnapshotStore
from eventflow.registry.function_registry import FunctionRegistry
from eventflow.scheduler.scheduler import Scheduler


async def _run_scheduler(scheduler: Scheduler, graph: Graph) -> dict[str, object]:
    func_name = "_run_scheduler"
    log_parameter(func_name, scheduler=scheduler, graph=graph)
    results = await scheduler.run(graph, graph_id="resume")
    log_variable_change(func_name, "results", results)
    return results


def test_scheduler_resumes_from_snapshot() -> None:
    func_name = "test_scheduler_resumes_from_snapshot"
    log_parameter(func_name)
    registry = FunctionRegistry()
    registry.register("start", lambda payload: "ready")
    registry.register("end", lambda payload: f"{payload}-done")

    graph = Graph(
        nodes={
            "start": Node(id="start", kind=NodeKind.TASK, handler="start"),
            "end": Node(id="end", kind=NodeKind.TASK, handler="end"),
        },
        edges={"e": Edge(id="e", source="start", target="end")},
    )

    store = InMemorySnapshotStore()
    event_log = InMemoryEventLog()

    execution_state = ExecutionState()
    execution_state.mark_complete(
        "start",
        event_id="start-1",
        outcome=VisitOutcome.success("ready"),
    )
    execution_state.note_upstream_completion("end", "start")
    store.save("resume", execution_state.snapshot())

    bus = EventBus()
    policy = SemaphorePolicy(limit=2)
    scheduler = Scheduler(
        registry,
        bus,
        policy,
        snapshot_store=store,
        event_log=event_log,
    )

    results = asyncio.run(_run_scheduler(scheduler, graph))
    log_variable_change(func_name, "results", results)
    assert results["end"] == "ready-done"

    snapshot = store.load("resume")
    completed = snapshot["completed_nodes"]
    log_variable_change(func_name, "completed", completed)
    assert "end" in completed

    logged_events = list(event_log.iter("resume"))
    log_variable_change(func_name, "logged_events", logged_events)
    assert [event.type for event in logged_events] == [
        EventType.NODE_SCHEDULED,
        EventType.NODE_COMPLETED,
    ]
