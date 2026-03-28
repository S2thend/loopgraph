from __future__ import annotations

import asyncio

import pytest

from loopgraph import log_parameter, log_variable_change
from loopgraph.bus.eventbus import EventBus
from loopgraph.concurrency.policies import SemaphorePolicy
from loopgraph.core.graph import Edge, Graph, Node
from loopgraph.core.state import SNAPSHOT_FORMAT_VERSION, ExecutionState
from loopgraph.core.types import EventType, NodeKind, NodeStatus, VisitOutcome
from loopgraph.persistence import InMemoryEventLog, InMemorySnapshotStore
from loopgraph.registry.function_registry import FunctionRegistry
from loopgraph.scheduler.scheduler import Scheduler


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


def test_scheduler_resumes_running_node_as_pending() -> None:
    registry = FunctionRegistry()
    executions = {"end": 0}
    registry.register("start", lambda payload: "ready")

    def end_handler(payload: object) -> str:
        executions["end"] += 1
        return f"{payload}-done"

    registry.register("end", end_handler)

    graph = Graph(
        nodes={
            "start": Node(id="start", kind=NodeKind.TASK, handler="start"),
            "end": Node(id="end", kind=NodeKind.TASK, handler="end"),
        },
        edges={"e": Edge(id="e", source="start", target="end")},
    )

    store = InMemorySnapshotStore()
    execution_state = ExecutionState()
    execution_state.mark_complete(
        "start",
        event_id="start-1",
        outcome=VisitOutcome.success("ready"),
    )
    execution_state.note_upstream_completion("end", "start")
    execution_state.mark_running("end")
    store.save("resume", execution_state.snapshot())

    scheduler = Scheduler(
        registry,
        EventBus(),
        SemaphorePolicy(limit=2),
        snapshot_store=store,
        event_log=InMemoryEventLog(),
    )

    results = asyncio.run(_run_scheduler(scheduler, graph))

    assert results["end"] == "ready-done"
    assert executions["end"] == 1
    snapshot = store.load("resume")
    assert snapshot["states"]["end"]["status"] == NodeStatus.COMPLETED.value


def test_scheduler_resume_excludes_never_activated_nodes() -> None:
    registry = FunctionRegistry()
    executed: list[str] = []
    registry.register("start", lambda payload: "ready")
    registry.register("decide", lambda payload: "done")

    def done_handler(payload: object) -> str:
        executed.append("done")
        return "complete"

    def fix_handler(payload: object) -> str:
        executed.append("fix")
        return "repair"

    registry.register("done", done_handler)
    registry.register("fix", fix_handler)

    graph = Graph(
        nodes={
            "start": Node(id="start", kind=NodeKind.TASK, handler="start"),
            "decide": Node(id="decide", kind=NodeKind.SWITCH, handler="decide"),
            "done": Node(id="done", kind=NodeKind.TASK, handler="done"),
            "fix": Node(id="fix", kind=NodeKind.TASK, handler="fix"),
        },
        edges={
            "start->decide": Edge(
                id="start->decide",
                source="start",
                target="decide",
            ),
            "decide->done": Edge(
                id="decide->done",
                source="decide",
                target="done",
                metadata={"route": "done"},
            ),
            "decide->fix": Edge(
                id="decide->fix",
                source="decide",
                target="fix",
                metadata={"route": "fix"},
            ),
        },
    )

    store = InMemorySnapshotStore()
    execution_state = ExecutionState()
    execution_state.mark_complete(
        "start",
        event_id="start-1",
        outcome=VisitOutcome.success("ready"),
    )
    execution_state.note_upstream_completion("decide", "start")
    store.save("resume", execution_state.snapshot())

    results = asyncio.run(
        _run_scheduler(
            Scheduler(
                registry,
                EventBus(),
                SemaphorePolicy(limit=2),
                snapshot_store=store,
            ),
            graph,
        )
    )

    assert results["done"] == "complete"
    assert "fix" not in results
    assert executed == ["done"]
    snapshot = store.load("resume")
    assert "fix" not in snapshot["states"]


@pytest.mark.parametrize("version", [None, SNAPSHOT_FORMAT_VERSION - 1])
def test_scheduler_rejects_missing_or_unsupported_snapshot_versions(
    version: int | None,
) -> None:
    registry = FunctionRegistry()
    executed: list[str] = []

    def start_handler(payload: object) -> str:
        executed.append("start")
        return "ready"

    registry.register("start", start_handler)

    graph = Graph(
        nodes={"start": Node(id="start", kind=NodeKind.TASK, handler="start")},
        edges={},
    )

    snapshot: dict[str, object] = {
        "states": {},
        "completed_nodes": [],
    }
    if version is not None:
        snapshot["snapshot_format_version"] = version

    store = InMemorySnapshotStore()
    store.save("resume", snapshot)
    event_log = InMemoryEventLog()

    scheduler = Scheduler(
        registry,
        EventBus(),
        SemaphorePolicy(limit=2),
        snapshot_store=store,
        event_log=event_log,
    )

    with pytest.raises(ValueError) as excinfo:
        asyncio.run(_run_scheduler(scheduler, graph))

    message = str(excinfo.value)
    assert "Unsupported snapshot format version" in message
    assert repr(version) in message
    assert str(SNAPSHOT_FORMAT_VERSION) in message
    assert "Discard or migrate" in message
    assert executed == []
    assert list(event_log.iter("resume")) == []


def test_persisted_supported_snapshots_include_snapshot_format_version() -> None:
    store = InMemorySnapshotStore()
    state = ExecutionState()
    store.save("resume", state.snapshot())

    snapshot = store.load("resume")

    assert snapshot["snapshot_format_version"] == SNAPSHOT_FORMAT_VERSION
