from __future__ import annotations

import asyncio
from typing import Any, Iterable, Mapping, cast

import pytest

from loopgraph.bus.eventbus import EventBus
from loopgraph.concurrency import PrioritySemaphorePolicy
from loopgraph.core.graph import Edge, Graph, Node
from loopgraph.core.state import ExecutionState
from loopgraph.core.types import EventType, NodeKind, NodeStatus, VisitOutcome
from loopgraph.persistence import InMemoryEventLog, InMemorySnapshotStore
from loopgraph.registry.function_registry import FunctionRegistry
from loopgraph.scheduler.scheduler import Scheduler


def _run_switch_leaf_workflow(
    *,
    route: str,
    branches: list[str],
    terminal_branches: set[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    registry = FunctionRegistry()
    executed: list[str] = []
    terminal_branches = terminal_branches or set()

    registry.register("input", lambda payload: None)
    registry.register("decide", lambda payload: route)

    nodes = {
        "input": Node(id="input", kind=NodeKind.TASK, handler="input"),
        "decide": Node(id="decide", kind=NodeKind.SWITCH, handler="decide"),
    }
    edges = {
        "input->decide": Edge(
            id="input->decide",
            source="input",
            target="decide",
        )
    }

    for branch in branches:
        branch_kind = (
            NodeKind.TERMINAL if branch in terminal_branches else NodeKind.TASK
        )

        def branch_handler(payload: object, *, branch: str = branch) -> str:
            executed.append(branch)
            return branch

        registry.register(branch, branch_handler)
        nodes[branch] = Node(id=branch, kind=branch_kind, handler=branch)
        edges[f"decide->{branch}"] = Edge(
            id=f"decide->{branch}",
            source="decide",
            target=branch,
            metadata={"route": branch},
        )

    graph = Graph(nodes=nodes, edges=edges)
    scheduler = Scheduler(registry, EventBus(), PrioritySemaphorePolicy(limit=1))
    results = asyncio.run(scheduler.run(graph))
    return results, executed


def test_switch_selected_leaf_completes_without_deadlock() -> None:
    results, executed = _run_switch_leaf_workflow(
        route="done",
        branches=["done", "fix"],
    )

    assert results["done"] == "done"
    assert "fix" not in results
    assert executed == ["done"]


def test_switch_with_three_leaf_branches_executes_only_selected_route() -> None:
    results, executed = _run_switch_leaf_workflow(
        route="review",
        branches=["done", "fix", "review"],
    )

    assert results["review"] == "review"
    assert "done" not in results
    assert "fix" not in results
    assert executed == ["review"]


@pytest.mark.parametrize("route", ["done", "fix"])
def test_switch_can_select_each_leaf_branch_across_runs(route: str) -> None:
    results, executed = _run_switch_leaf_workflow(
        route=route,
        branches=["done", "fix"],
    )

    assert results[route] == route
    assert executed == [route]


def test_issue_5_switch_to_terminal_path_does_not_leave_fix_branch_pending() -> None:
    registry = FunctionRegistry()
    executed: list[str] = []

    def step(name: str):
        def handler(payload: object) -> str:
            executed.append(name)
            return name

        return handler

    def decide_handler(payload: object) -> str:
        executed.append("decide")
        return "done"

    registry.register("input", step("input"))
    registry.register("prompt_build", step("prompt_build"))
    registry.register("research", step("research"))
    registry.register("extract", step("extract"))
    registry.register("repair", step("repair"))
    registry.register("validate", step("validate"))
    registry.register("decide", decide_handler)
    registry.register("done", step("done"))
    registry.register("fix", step("fix"))

    graph = Graph(
        nodes={
            "input": Node(id="input", kind=NodeKind.TASK, handler="input"),
            "prompt_build": Node(
                id="prompt_build",
                kind=NodeKind.TASK,
                handler="prompt_build",
            ),
            "research": Node(id="research", kind=NodeKind.TASK, handler="research"),
            "extract": Node(id="extract", kind=NodeKind.TASK, handler="extract"),
            "repair": Node(
                id="repair",
                kind=NodeKind.TASK,
                handler="repair",
                allow_partial_upstream=True,
            ),
            "validate": Node(id="validate", kind=NodeKind.TASK, handler="validate"),
            "decide": Node(id="decide", kind=NodeKind.SWITCH, handler="decide"),
            "done": Node(id="done", kind=NodeKind.TERMINAL, handler="done"),
            "fix": Node(id="fix", kind=NodeKind.TASK, handler="fix"),
        },
        edges={
            "input->prompt_build": Edge(
                id="input->prompt_build",
                source="input",
                target="prompt_build",
            ),
            "prompt_build->research": Edge(
                id="prompt_build->research",
                source="prompt_build",
                target="research",
            ),
            "research->extract": Edge(
                id="research->extract",
                source="research",
                target="extract",
            ),
            "extract->repair": Edge(
                id="extract->repair",
                source="extract",
                target="repair",
            ),
            "repair->validate": Edge(
                id="repair->validate",
                source="repair",
                target="validate",
            ),
            "validate->decide": Edge(
                id="validate->decide",
                source="validate",
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
            "fix->repair": Edge(
                id="fix->repair",
                source="fix",
                target="repair",
            ),
        },
    )

    scheduler = Scheduler(registry, EventBus(), PrioritySemaphorePolicy(limit=1))
    results = asyncio.run(scheduler.run(graph))

    assert results["done"] == "done"
    assert "fix" not in results
    assert executed == [
        "input",
        "prompt_build",
        "research",
        "extract",
        "repair",
        "validate",
        "decide",
        "done",
    ]


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
            "start->process": Edge(
                id="start->process", source="start", target="process"
            ),
            "switch->process": Edge(
                id="switch->process",
                source="switch",
                target="process",
                metadata={"route": "process"},
            ),
            "process->merge": Edge(
                id="process->merge", source="process", target="merge"
            ),
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
        state.reset_for_reentry("loop")

    assert not state.is_ready(graph, "loop")

    scheduler = Scheduler(FunctionRegistry(), EventBus(), PrioritySemaphorePolicy(1))
    selected = scheduler._determine_downstream_edges(
        graph=graph,
        node=graph.nodes["switch"],
        handler_result="loop",
        execution_state=state,
    )
    assert selected and selected[0].target == "exit"


def test_reset_for_reentry_preserves_visits_and_snapshot_round_trip() -> None:
    state = ExecutionState()
    state.mark_running("loop")
    state.mark_complete("loop", "loop-1", VisitOutcome.success({"value": 1}))
    state.note_upstream_completion("loop", "upstream-a")

    before = state.snapshot()["states"]["loop"]["visits"]["count"]
    state.reset_for_reentry("loop")
    snapshot = state.snapshot()

    assert snapshot["states"]["loop"]["status"] == NodeStatus.PENDING.value
    assert snapshot["states"]["loop"]["upstream_completed"] == []
    assert snapshot["states"]["loop"]["visits"]["count"] == before
    assert "loop" not in snapshot["completed_nodes"]

    restored = ExecutionState.restore(snapshot)
    assert restored.snapshot() == snapshot


def test_graph_validate_rejects_shared_node_multi_loop() -> None:
    graph = Graph(
        nodes={
            "a": Node(id="a", kind=NodeKind.TASK, handler="a"),
            "b": Node(id="b", kind=NodeKind.TASK, handler="b"),
            "c": Node(id="c", kind=NodeKind.TASK, handler="c"),
        },
        edges={
            "a->b": Edge(id="a->b", source="a", target="b"),
            "b->a": Edge(id="b->a", source="b", target="a"),
            "b->c": Edge(id="b->c", source="b", target="c"),
            "c->b": Edge(id="c->b", source="c", target="b"),
        },
    )

    with pytest.raises(ValueError, match="multi-loop shared nodes"):
        graph.validate()


def test_graph_validate_allows_multiple_disjoint_loops() -> None:
    graph = Graph(
        nodes={
            "a": Node(id="a", kind=NodeKind.TASK, handler="a"),
            "b": Node(id="b", kind=NodeKind.TASK, handler="b"),
            "c": Node(id="c", kind=NodeKind.TASK, handler="c"),
            "d": Node(id="d", kind=NodeKind.TASK, handler="d"),
        },
        edges={
            "a->b": Edge(id="a->b", source="a", target="b"),
            "b->a": Edge(id="b->a", source="b", target="a"),
            "c->d": Edge(id="c->d", source="c", target="d"),
            "d->c": Edge(id="d->c", source="d", target="c"),
        },
    )

    graph.validate()


def test_graph_validate_allows_single_long_loop() -> None:
    graph = Graph(
        nodes={
            "a": Node(id="a", kind=NodeKind.TASK, handler="a"),
            "b": Node(id="b", kind=NodeKind.TASK, handler="b"),
            "c": Node(id="c", kind=NodeKind.TASK, handler="c"),
        },
        edges={
            "a->b": Edge(id="a->b", source="a", target="b"),
            "b->c": Edge(id="b->c", source="b", target="c"),
            "c->a": Edge(id="c->a", source="c", target="a"),
        },
    )

    graph.validate()


def test_graph_validate_rejects_switch_self_loop() -> None:
    graph = Graph(
        nodes={
            "s": Node(id="s", kind=NodeKind.SWITCH, handler="switch"),
        },
        edges={
            "s->s": Edge(
                id="s->s",
                source="s",
                target="s",
                metadata={"route": "loop"},
            )
        },
    )

    with pytest.raises(ValueError, match="cannot have a self-loop"):
        graph.validate()


def test_graph_validate_allows_non_switch_self_loop() -> None:
    graph = Graph(
        nodes={
            "t": Node(id="t", kind=NodeKind.TASK, handler="task"),
        },
        edges={
            "t->t": Edge(id="t->t", source="t", target="t"),
        },
    )

    graph.validate()


def test_scheduler_bounded_loop_reentry() -> None:
    registry = FunctionRegistry()
    counter = {"loop": 0, "output": 0}

    def start_handler(_: object) -> None:
        return None

    def loop_handler(_: object) -> dict[str, int]:
        counter["loop"] += 1
        return {"iteration": counter["loop"]}

    def switch_handler(payload: dict[str, int]) -> str:
        return "continue" if payload["iteration"] < 3 else "done"

    def output_handler(payload: str) -> str:
        counter["output"] += 1
        return payload

    registry.register("start", start_handler)
    registry.register("loop", loop_handler)
    registry.register("switch", switch_handler)
    registry.register("output", output_handler)

    graph = Graph(
        nodes={
            "start": Node(id="start", kind=NodeKind.TASK, handler="start"),
            "loop": Node(
                id="loop",
                kind=NodeKind.TASK,
                handler="loop",
                max_visits=3,
                allow_partial_upstream=True,
            ),
            "switch": Node(id="switch", kind=NodeKind.SWITCH, handler="switch"),
            "output": Node(id="output", kind=NodeKind.TASK, handler="output"),
        },
        edges={
            "start->loop": Edge(id="start->loop", source="start", target="loop"),
            "loop->switch": Edge(id="loop->switch", source="loop", target="switch"),
            "switch->loop": Edge(
                id="switch->loop",
                source="switch",
                target="loop",
                metadata={"route": "continue"},
            ),
            "switch->output": Edge(
                id="switch->output",
                source="switch",
                target="output",
                metadata={"route": "done"},
            ),
        },
    )

    scheduler = Scheduler(registry, EventBus(), PrioritySemaphorePolicy(1))
    results = asyncio.run(scheduler.run(graph))

    assert counter["loop"] == 3
    assert counter["output"] == 1
    assert results["output"] == "done"


def test_activation_frontier_aggregate_waits_for_all_upstreams() -> None:
    registry = FunctionRegistry()
    event_log = InMemoryEventLog()

    registry.register("start", lambda payload: None)
    registry.register("left", lambda payload: "left")
    registry.register("right", lambda payload: "right")
    registry.register("merge", lambda payload: tuple(cast(list[str], payload)))

    graph = Graph(
        nodes={
            "start": Node(id="start", kind=NodeKind.TASK, handler="start"),
            "left": Node(id="left", kind=NodeKind.TASK, handler="left"),
            "right": Node(id="right", kind=NodeKind.TASK, handler="right"),
            "merge": Node(
                id="merge",
                kind=NodeKind.AGGREGATE,
                handler="merge",
                config={"required": 2},
            ),
        },
        edges={
            "start->left": Edge(id="start->left", source="start", target="left"),
            "start->right": Edge(id="start->right", source="start", target="right"),
            "left->merge": Edge(id="left->merge", source="left", target="merge"),
            "right->merge": Edge(id="right->merge", source="right", target="merge"),
        },
    )

    scheduler = Scheduler(
        registry,
        EventBus(),
        PrioritySemaphorePolicy(1),
        event_log=event_log,
    )
    results = asyncio.run(scheduler.run(graph, graph_id="aggregate-frontier"))

    events = [
        (event.type, event.node_id) for event in event_log.iter("aggregate-frontier")
    ]
    merge_scheduled_index = next(
        index
        for index, event in enumerate(events)
        if event == (EventType.NODE_SCHEDULED, "merge")
    )
    left_completed_index = next(
        index
        for index, event in enumerate(events)
        if event == (EventType.NODE_COMPLETED, "left")
    )
    right_completed_index = next(
        index
        for index, event in enumerate(events)
        if event == (EventType.NODE_COMPLETED, "right")
    )

    assert left_completed_index < merge_scheduled_index
    assert right_completed_index < merge_scheduled_index
    assert set(results["merge"]) == {"left", "right"}


def test_scheduler_loop_max_visits_1() -> None:
    registry = FunctionRegistry()
    counter = {"loop": 0, "output": 0}

    def start_handler(_: object) -> None:
        return None

    def loop_handler(_: object) -> dict[str, int]:
        counter["loop"] += 1
        return {"iteration": counter["loop"]}

    def switch_handler(_: dict[str, int]) -> str:
        return "continue"

    def output_handler(payload: str) -> str:
        counter["output"] += 1
        return payload

    registry.register("start", start_handler)
    registry.register("loop", loop_handler)
    registry.register("switch", switch_handler)
    registry.register("output", output_handler)

    graph = Graph(
        nodes={
            "start": Node(id="start", kind=NodeKind.TASK, handler="start"),
            "loop": Node(
                id="loop",
                kind=NodeKind.TASK,
                handler="loop",
                max_visits=1,
                allow_partial_upstream=True,
            ),
            "switch": Node(id="switch", kind=NodeKind.SWITCH, handler="switch"),
            "output": Node(id="output", kind=NodeKind.TASK, handler="output"),
        },
        edges={
            "start->loop": Edge(id="start->loop", source="start", target="loop"),
            "loop->switch": Edge(id="loop->switch", source="loop", target="switch"),
            "switch->loop": Edge(
                id="switch->loop",
                source="switch",
                target="loop",
                metadata={"route": "continue"},
            ),
            "switch->output": Edge(
                id="switch->output",
                source="switch",
                target="output",
                metadata={"route": "exit"},
            ),
        },
    )

    scheduler = Scheduler(registry, EventBus(), PrioritySemaphorePolicy(1))
    results = asyncio.run(scheduler.run(graph))

    assert counter["loop"] == 1
    assert counter["output"] == 1
    assert results["output"] == "continue"


def test_activation_frontier_loop_reentry_preserves_max_visits_and_visit_counts() -> (
    None
):
    registry = FunctionRegistry()
    counter = {"loop": 0}

    def start_handler(_: object) -> None:
        return None

    def loop_handler(_: object) -> dict[str, int]:
        counter["loop"] += 1
        return {"iteration": counter["loop"]}

    def switch_handler(_: dict[str, int]) -> str:
        return "continue"

    def output_handler(payload: str) -> str:
        return payload

    registry.register("start", start_handler)
    registry.register("loop", loop_handler)
    registry.register("switch", switch_handler)
    registry.register("output", output_handler)

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
            "output": Node(id="output", kind=NodeKind.TASK, handler="output"),
        },
        edges={
            "start->loop": Edge(id="start->loop", source="start", target="loop"),
            "loop->switch": Edge(id="loop->switch", source="loop", target="switch"),
            "switch->loop": Edge(
                id="switch->loop",
                source="switch",
                target="loop",
                metadata={"route": "continue"},
            ),
            "switch->output": Edge(
                id="switch->output",
                source="switch",
                target="output",
                metadata={"route": "exit"},
            ),
        },
    )

    event_log = InMemoryEventLog()
    scheduler = Scheduler(
        registry,
        EventBus(),
        PrioritySemaphorePolicy(1),
        event_log=event_log,
    )
    results = asyncio.run(scheduler.run(graph, graph_id="activation-frontier-loop"))

    visit_counts = [
        event.visit_count
        for event in event_log.iter("activation-frontier-loop")
        if event.type is EventType.NODE_COMPLETED and event.node_id == "loop"
    ]

    assert counter["loop"] == 2
    assert visit_counts == [1, 2]
    assert results["output"] == "continue"


def test_scheduler_disjoint_loops_execute() -> None:
    registry = FunctionRegistry()
    counters = {"loop_a": 0, "loop_b": 0}

    def start_handler(_: object) -> None:
        return None

    def loop_a_handler(_: object) -> dict[str, int]:
        counters["loop_a"] += 1
        return {"n": counters["loop_a"]}

    def loop_b_handler(_: object) -> dict[str, int]:
        counters["loop_b"] += 1
        return {"n": counters["loop_b"]}

    def switch_a_handler(payload: dict[str, int]) -> str:
        return "continue_a" if payload["n"] < 2 else "done_a"

    def switch_b_handler(payload: dict[str, int]) -> str:
        return "continue_b" if payload["n"] < 2 else "done_b"

    def output_handler(payload: str) -> str:
        return payload

    registry.register("start", start_handler)
    registry.register("loop_a", loop_a_handler)
    registry.register("switch_a", switch_a_handler)
    registry.register("loop_b", loop_b_handler)
    registry.register("switch_b", switch_b_handler)
    registry.register("out_a", output_handler)
    registry.register("out_b", output_handler)

    graph = Graph(
        nodes={
            "start": Node(id="start", kind=NodeKind.TASK, handler="start"),
            "loop_a": Node(
                id="loop_a",
                kind=NodeKind.TASK,
                handler="loop_a",
                max_visits=2,
                allow_partial_upstream=True,
            ),
            "switch_a": Node(id="switch_a", kind=NodeKind.SWITCH, handler="switch_a"),
            "out_a": Node(id="out_a", kind=NodeKind.TASK, handler="out_a"),
            "loop_b": Node(
                id="loop_b",
                kind=NodeKind.TASK,
                handler="loop_b",
                max_visits=2,
                allow_partial_upstream=True,
            ),
            "switch_b": Node(id="switch_b", kind=NodeKind.SWITCH, handler="switch_b"),
            "out_b": Node(id="out_b", kind=NodeKind.TASK, handler="out_b"),
        },
        edges={
            "start->loop_a": Edge(id="start->loop_a", source="start", target="loop_a"),
            "start->loop_b": Edge(id="start->loop_b", source="start", target="loop_b"),
            "loop_a->switch_a": Edge(
                id="loop_a->switch_a", source="loop_a", target="switch_a"
            ),
            "switch_a->loop_a": Edge(
                id="switch_a->loop_a",
                source="switch_a",
                target="loop_a",
                metadata={"route": "continue_a"},
            ),
            "switch_a->out_a": Edge(
                id="switch_a->out_a",
                source="switch_a",
                target="out_a",
                metadata={"route": "done_a"},
            ),
            "loop_b->switch_b": Edge(
                id="loop_b->switch_b", source="loop_b", target="switch_b"
            ),
            "switch_b->loop_b": Edge(
                id="switch_b->loop_b",
                source="switch_b",
                target="loop_b",
                metadata={"route": "continue_b"},
            ),
            "switch_b->out_b": Edge(
                id="switch_b->out_b",
                source="switch_b",
                target="out_b",
                metadata={"route": "done_b"},
            ),
        },
    )
    graph.validate()

    scheduler = Scheduler(registry, EventBus(), PrioritySemaphorePolicy(1))
    results = asyncio.run(scheduler.run(graph))

    assert counters["loop_a"] == 2
    assert counters["loop_b"] == 2
    assert results["out_a"] == "done_a"
    assert results["out_b"] == "done_b"


def test_scheduler_zero_entry_nodes_fail_fast() -> None:
    registry = FunctionRegistry()
    registry.register("a", lambda payload: "a")
    registry.register("b", lambda payload: "b")

    graph = Graph(
        nodes={
            "a": Node(id="a", kind=NodeKind.TASK, handler="a"),
            "b": Node(id="b", kind=NodeKind.TASK, handler="b"),
        },
        edges={
            "a->b": Edge(id="a->b", source="a", target="b"),
            "b->a": Edge(id="b->a", source="b", target="a"),
        },
    )

    scheduler = Scheduler(registry, EventBus(), PrioritySemaphorePolicy(1))

    with pytest.raises(ValueError, match="no entry nodes"):
        asyncio.run(scheduler.run(graph))


def test_scheduler_stuck_activated_node_still_raises_runtime_error() -> None:
    registry = FunctionRegistry()
    registry.register("start", lambda payload: None)
    registry.register("gate", lambda payload: "gate")
    registry.register("blocker", lambda payload: "blocker")

    graph = Graph(
        nodes={
            "start": Node(id="start", kind=NodeKind.TASK, handler="start"),
            "gate": Node(id="gate", kind=NodeKind.TASK, handler="gate"),
            "blocker": Node(id="blocker", kind=NodeKind.TASK, handler="blocker"),
        },
        edges={
            "start->gate": Edge(id="start->gate", source="start", target="gate"),
            "blocker->gate": Edge(
                id="blocker->gate",
                source="blocker",
                target="gate",
            ),
            "blocker->blocker": Edge(
                id="blocker->blocker",
                source="blocker",
                target="blocker",
            ),
        },
    )

    scheduler = Scheduler(registry, EventBus(), PrioritySemaphorePolicy(1))

    with pytest.raises(RuntimeError, match="could not make progress"):
        asyncio.run(scheduler.run(graph))


def test_scheduler_reentry_pending_running_hard_stop() -> None:
    registry = FunctionRegistry()
    registry.register("switch", lambda _: "loop")

    graph = Graph(
        nodes={
            "switch": Node(id="switch", kind=NodeKind.SWITCH, handler="switch"),
            "loop": Node(
                id="loop",
                kind=NodeKind.TASK,
                handler="noop",
                allow_partial_upstream=True,
            ),
        },
        edges={
            "switch->loop": Edge(
                id="switch->loop",
                source="switch",
                target="loop",
                metadata={"route": "loop"},
            )
        },
    )
    registry.register("noop", lambda _: None)
    state = ExecutionState()
    state.mark_running("loop")
    scheduler = Scheduler(registry, EventBus(), PrioritySemaphorePolicy(1))

    with pytest.raises(RuntimeError, match="non-terminal"):
        asyncio.run(
            scheduler._execute_node(
                node=graph.nodes["switch"],
                graph=graph,
                execution_state=state,
                graph_id="graph",
                upstream_payload=None,
            )
        )


def test_terminal_leaf_branch_schedules_like_task_under_activation_frontier() -> None:
    results, executed = _run_switch_leaf_workflow(
        route="done",
        branches=["done", "fix"],
        terminal_branches={"done"},
    )

    assert results["done"] == "done"
    assert "fix" not in results
    assert executed == ["done"]


def test_scheduler_raises_for_switch_route_with_no_matching_edge() -> None:
    registry = FunctionRegistry()
    registry.register("start", lambda payload: None)
    registry.register("switch", lambda payload: "missing")
    registry.register("done", lambda payload: "done")

    graph = Graph(
        nodes={
            "start": Node(id="start", kind=NodeKind.TASK, handler="start"),
            "switch": Node(id="switch", kind=NodeKind.SWITCH, handler="switch"),
            "done": Node(id="done", kind=NodeKind.TASK, handler="done"),
        },
        edges={
            "start->switch": Edge(
                id="start->switch",
                source="start",
                target="switch",
            ),
            "switch->done": Edge(
                id="switch->done",
                source="switch",
                target="done",
                metadata={"route": "done"},
            ),
        },
    )

    scheduler = Scheduler(registry, EventBus(), PrioritySemaphorePolicy(1))

    with pytest.raises(ValueError, match="switch'.*'missing'"):
        asyncio.run(scheduler.run(graph))


def test_scheduler_unbounded_loop_handler_exit() -> None:
    registry = FunctionRegistry()
    counter = {"loop": 0, "output": 0}

    def start_handler(_: object) -> None:
        return None

    def loop_handler(_: object) -> dict[str, int]:
        counter["loop"] += 1
        return {"iteration": counter["loop"]}

    def switch_handler(payload: dict[str, int]) -> str:
        return "continue" if payload["iteration"] < 5 else "done"

    def output_handler(payload: str) -> str:
        counter["output"] += 1
        return payload

    registry.register("start", start_handler)
    registry.register("loop", loop_handler)
    registry.register("switch", switch_handler)
    registry.register("output", output_handler)

    graph = Graph(
        nodes={
            "start": Node(id="start", kind=NodeKind.TASK, handler="start"),
            "loop": Node(
                id="loop",
                kind=NodeKind.TASK,
                handler="loop",
                allow_partial_upstream=True,
            ),
            "switch": Node(id="switch", kind=NodeKind.SWITCH, handler="switch"),
            "output": Node(id="output", kind=NodeKind.TASK, handler="output"),
        },
        edges={
            "start->loop": Edge(id="start->loop", source="start", target="loop"),
            "loop->switch": Edge(id="loop->switch", source="loop", target="switch"),
            "switch->loop": Edge(
                id="switch->loop",
                source="switch",
                target="loop",
                metadata={"route": "continue"},
            ),
            "switch->output": Edge(
                id="switch->output",
                source="switch",
                target="output",
                metadata={"route": "done"},
            ),
        },
    )

    scheduler = Scheduler(registry, EventBus(), PrioritySemaphorePolicy(1))
    results = asyncio.run(scheduler.run(graph))

    assert counter["loop"] == 5
    assert counter["output"] == 1
    assert results["output"] == "done"


def test_loop_visit_count_observability() -> None:
    registry = FunctionRegistry()
    counter = {"loop": 0}

    def start_handler(_: object) -> None:
        return None

    def loop_handler(_: object) -> dict[str, int]:
        counter["loop"] += 1
        return {"iteration": counter["loop"]}

    def switch_handler(payload: dict[str, int]) -> str:
        return "continue" if payload["iteration"] < 3 else "done"

    def output_handler(payload: str) -> str:
        return payload

    registry.register("start", start_handler)
    registry.register("loop", loop_handler)
    registry.register("switch", switch_handler)
    registry.register("output", output_handler)

    graph = Graph(
        nodes={
            "start": Node(id="start", kind=NodeKind.TASK, handler="start"),
            "loop": Node(
                id="loop",
                kind=NodeKind.TASK,
                handler="loop",
                max_visits=3,
                allow_partial_upstream=True,
            ),
            "switch": Node(id="switch", kind=NodeKind.SWITCH, handler="switch"),
            "output": Node(id="output", kind=NodeKind.TASK, handler="output"),
        },
        edges={
            "start->loop": Edge(id="start->loop", source="start", target="loop"),
            "loop->switch": Edge(id="loop->switch", source="loop", target="switch"),
            "switch->loop": Edge(
                id="switch->loop",
                source="switch",
                target="loop",
                metadata={"route": "continue"},
            ),
            "switch->output": Edge(
                id="switch->output",
                source="switch",
                target="output",
                metadata={"route": "done"},
            ),
        },
    )

    event_log = InMemoryEventLog()
    scheduler = Scheduler(
        registry,
        EventBus(),
        PrioritySemaphorePolicy(1),
        event_log=event_log,
    )
    asyncio.run(scheduler.run(graph, graph_id="visit-observability"))

    counts = [
        event.visit_count
        for event in event_log.iter("visit-observability")
        if event.type is EventType.NODE_COMPLETED and event.node_id == "loop"
    ]
    assert counts == [1, 2, 3]


def test_loop_snapshot_resume_visit_count() -> None:
    class FailingOnceSnapshotStore(InMemorySnapshotStore):
        def __init__(self, fail_on_save: int) -> None:
            super().__init__()
            self._save_calls = 0
            self._fail_on_save = fail_on_save
            self._failed = False

        def save(self, graph_id: str, snapshot: Mapping[str, object]) -> None:
            self._save_calls += 1
            if not self._failed and self._save_calls == self._fail_on_save:
                self._failed = True
                raise RuntimeError("simulated stop")
            super().save(graph_id, snapshot)

    registry = FunctionRegistry()
    counter = {"loop": 0}

    def start_handler(_: object) -> None:
        return None

    def loop_handler(_: object) -> dict[str, int]:
        counter["loop"] += 1
        return {"iteration": counter["loop"]}

    def switch_handler(payload: dict[str, int]) -> str:
        return "continue" if payload["iteration"] < 3 else "done"

    def output_handler(payload: str) -> str:
        return payload

    registry.register("start", start_handler)
    registry.register("loop", loop_handler)
    registry.register("switch", switch_handler)
    registry.register("output", output_handler)

    graph = Graph(
        nodes={
            "start": Node(id="start", kind=NodeKind.TASK, handler="start"),
            "loop": Node(
                id="loop",
                kind=NodeKind.TASK,
                handler="loop",
                max_visits=3,
                allow_partial_upstream=True,
            ),
            "switch": Node(id="switch", kind=NodeKind.SWITCH, handler="switch"),
            "output": Node(id="output", kind=NodeKind.TASK, handler="output"),
        },
        edges={
            "start->loop": Edge(id="start->loop", source="start", target="loop"),
            "loop->switch": Edge(id="loop->switch", source="loop", target="switch"),
            "switch->loop": Edge(
                id="switch->loop",
                source="switch",
                target="loop",
                metadata={"route": "continue"},
            ),
            "switch->output": Edge(
                id="switch->output",
                source="switch",
                target="output",
                metadata={"route": "done"},
            ),
        },
    )

    snapshot_store = FailingOnceSnapshotStore(fail_on_save=5)
    with pytest.raises(RuntimeError, match="simulated stop"):
        asyncio.run(
            Scheduler(
                registry,
                EventBus(),
                PrioritySemaphorePolicy(1),
                snapshot_store=snapshot_store,
            ).run(graph, graph_id="resume-loop")
        )

    resumed_log = InMemoryEventLog()
    resumed_results = asyncio.run(
        Scheduler(
            registry,
            EventBus(),
            PrioritySemaphorePolicy(1),
            snapshot_store=snapshot_store,
            event_log=resumed_log,
        ).run(graph, graph_id="resume-loop")
    )

    resumed_counts = [
        event.visit_count
        for event in resumed_log.iter("resume-loop")
        if event.type is EventType.NODE_COMPLETED and event.node_id == "loop"
    ]

    assert resumed_counts == [3]
    assert resumed_results["output"] == "done"


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
            "start->transform": Edge(
                id="start->transform", source="start", target="transform"
            ),
            "transform->final": Edge(
                id="transform->final", source="transform", target="final"
            ),
        },
    )

    scheduler = Scheduler(registry, EventBus(), PrioritySemaphorePolicy(limit=1))
    results = asyncio.run(scheduler.run(graph, initial_payload=None))

    assert results["final"] == [2, 4]
