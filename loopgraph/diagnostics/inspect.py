"""Diagnostics helpers for inspecting graphs and execution state."""

from __future__ import annotations

from typing import Dict

from .._debug import log_loop_iteration, log_parameter, log_variable_change
from ..core.graph import Graph
from ..core.state import ExecutionState


def describe_graph(graph: Graph) -> Dict[str, object]:
    """Return a summary of the graph structure.

    >>> from loopgraph.core.graph import Edge, Node
    >>> from loopgraph.core.types import NodeKind
    >>> graph = Graph(
    ...     nodes={
    ...         "start": Node(id="start", kind=NodeKind.TASK, handler="start_handler"),
    ...         "end": Node(id="end", kind=NodeKind.TERMINAL, handler="end_handler"),
    ...     },
    ...     edges={"e": Edge(id="e", source="start", target="end")},
    ... )
    >>> describe_graph(graph)["node_count"]
    2
    """
    func_name = "describe_graph"
    log_parameter(func_name, graph=graph)
    summary = {
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "nodes": list(graph.nodes.keys()),
    }
    log_variable_change(func_name, "summary", summary)
    return summary


def describe_execution_state(state: ExecutionState) -> Dict[str, object]:
    """Summarise execution state snapshot data.

    >>> from loopgraph.core.types import VisitOutcome, NodeStatus
    >>> execution = ExecutionState()
    >>> execution.mark_complete(
    ...     "node-1",
    ...     event_id="evt-1",
    ...     outcome=VisitOutcome.success(),
    ... )
    >>> describe_execution_state(execution)["completed"]
    ['node-1']
    """
    func_name = "describe_execution_state"
    log_parameter(func_name, state=state)
    snapshot = state.snapshot()
    log_variable_change(func_name, "snapshot", snapshot)
    completed_nodes = list(snapshot["completed_nodes"])
    log_variable_change(func_name, "completed_nodes", completed_nodes)
    statuses: Dict[str, str] = {}
    log_variable_change(func_name, "statuses", statuses)
    for iteration, (node_id, node_state) in enumerate(snapshot["states"].items()):
        log_loop_iteration(func_name, "states", iteration)
        status = str(node_state["status"])
        log_variable_change(func_name, "status", status)
        statuses[node_id] = status
        log_variable_change(func_name, f"statuses[{node_id!r}]", statuses[node_id])
    summary: Dict[str, object] = {
        "completed": completed_nodes,
        "statuses": statuses,
    }
    log_variable_change(func_name, "summary", summary)
    return summary
