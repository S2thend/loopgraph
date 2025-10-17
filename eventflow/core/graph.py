"""Graph primitives describing workflow structure."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from .._debug import (
    log_branch,
    log_loop_iteration,
    log_parameter,
    log_variable_change,
)
from .types import NodeKind


@dataclass(frozen=True)
class Node:
    """Immutable graph node definition."""

    id: str
    kind: NodeKind
    handler: str
    config: Dict[str, object] = field(default_factory=dict)
    max_visits: Optional[int] = None
    priority: int = 0
    allow_partial_upstream: bool = False


@dataclass(frozen=True)
class Edge:
    """Directed edge linking nodes."""

    id: str
    source: str
    target: str
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class Graph:
    """Graph container maintaining adjacency helpers.

    >>> nodes = {
    ...     "start": Node(id="start", kind=NodeKind.TASK, handler="start_handler"),
    ...     "end": Node(id="end", kind=NodeKind.TERMINAL, handler="end_handler"),
    ... }
    >>> edges = {
    ...     "edge-1": Edge(id="edge-1", source="start", target="end"),
    ... }
    >>> graph = Graph(nodes=nodes, edges=edges)
    >>> graph.validate()
    >>> [node.id for node in graph.downstream_nodes("start")]
    ['end']
    """

    nodes: Dict[str, Node] = field(default_factory=dict)
    edges: Dict[str, Edge] = field(default_factory=dict)

    def __post_init__(self) -> None:
        func_name = "Graph.__post_init__"
        log_parameter(func_name, nodes=self.nodes, edges=self.edges)
        self._forward_adj: Dict[str, List[Edge]] = {}
        log_variable_change(func_name, "self._forward_adj", self._forward_adj)
        self._reverse_adj: Dict[str, List[Edge]] = {}
        log_variable_change(func_name, "self._reverse_adj", self._reverse_adj)
        self._rebuild_indices()

    def _rebuild_indices(self) -> None:
        """Rebuild adjacency maps when graph structure changes."""
        func_name = "Graph._rebuild_indices"
        log_parameter(func_name)
        forward: Dict[str, List[Edge]] = {node_id: [] for node_id in self.nodes}
        log_variable_change(func_name, "forward", forward)
        reverse: Dict[str, List[Edge]] = {node_id: [] for node_id in self.nodes}
        log_variable_change(func_name, "reverse", reverse)
        for iteration, edge in enumerate(self.edges.values()):
            log_loop_iteration(func_name, "edges", iteration)
            forward.setdefault(edge.source, []).append(edge)
            log_variable_change(
                func_name,
                f"forward[{edge.source}]",
                forward.get(edge.source),
            )
            reverse.setdefault(edge.target, []).append(edge)
            log_variable_change(
                func_name,
                f"reverse[{edge.target}]",
                reverse.get(edge.target),
            )
        self._forward_adj = forward
        log_variable_change(func_name, "self._forward_adj", self._forward_adj)
        self._reverse_adj = reverse
        log_variable_change(func_name, "self._reverse_adj", self._reverse_adj)

    def validate(self) -> None:
        """Validate node handlers and edge connectivity."""
        func_name = "Graph.validate"
        log_parameter(func_name)
        missing_nodes: List[str] = []
        log_variable_change(func_name, "missing_nodes", missing_nodes)
        for iteration, edge in enumerate(self.edges.values()):
            log_loop_iteration(func_name, "edges", iteration)
            if edge.source not in self.nodes:
                log_branch(func_name, "missing_source")
                missing_nodes.append(edge.source)
                log_variable_change(func_name, "missing_nodes", missing_nodes)
            else:
                log_branch(func_name, "existing_source")
            if edge.target not in self.nodes:
                log_branch(func_name, "missing_target")
                missing_nodes.append(edge.target)
                log_variable_change(func_name, "missing_nodes", missing_nodes)
            else:
                log_branch(func_name, "existing_target")

        if missing_nodes:
            log_branch(func_name, "missing_nodes_error")
            raise ValueError(f"Edges reference unknown nodes: {missing_nodes}")
        log_branch(func_name, "all_edges_valid")

        invalid_handlers: List[str] = []
        log_variable_change(func_name, "invalid_handlers", invalid_handlers)
        for iteration, node in enumerate(self.nodes.values()):
            log_loop_iteration(func_name, "nodes", iteration)
            if not node.handler:
                log_branch(func_name, "missing_handler")
                invalid_handlers.append(node.id)
                log_variable_change(func_name, "invalid_handlers", invalid_handlers)
            else:
                log_branch(func_name, "handler_present")

        if invalid_handlers:
            log_branch(func_name, "invalid_handlers_error")
            raise ValueError(f"Nodes missing handlers: {invalid_handlers}")
        log_branch(func_name, "handlers_valid")

    def downstream_nodes(self, node_id: str) -> List[Node]:
        """Return nodes that can be visited after the given node.

        >>> graph = Graph(
        ...     nodes={
        ...         "a": Node(id="a", kind=NodeKind.TASK, handler="A"),
        ...         "b": Node(id="b", kind=NodeKind.TERMINAL, handler="B"),
        ...     },
        ...     edges={"e": Edge(id="e", source="a", target="b")},
        ... )
        >>> [node.id for node in graph.downstream_nodes("a")]
        ['b']
        """
        func_name = "Graph.downstream_nodes"
        log_parameter(func_name, node_id=node_id)
        if node_id not in self.nodes:
            log_branch(func_name, "missing_node")
            raise KeyError(f"Node '{node_id}' not found")
        log_branch(func_name, "node_present")
        edges = self._forward_adj.get(node_id, [])
        log_variable_change(func_name, "edges", edges)
        targets = [self.nodes[edge.target] for edge in edges]
        log_variable_change(func_name, "targets", targets)
        return targets

    def upstream_nodes(self, node_id: str) -> List[Node]:
        """Return nodes that must complete before the given node.

        >>> graph = Graph(
        ...     nodes={
        ...         "a": Node(id="a", kind=NodeKind.TASK, handler="A"),
        ...         "b": Node(id="b", kind=NodeKind.TASK, handler="B"),
        ...     },
        ...     edges={"e": Edge(id="e", source="a", target="b")},
        ... )
        >>> [node.id for node in graph.upstream_nodes("b")]
        ['a']
        """
        func_name = "Graph.upstream_nodes"
        log_parameter(func_name, node_id=node_id)
        if node_id not in self.nodes:
            log_branch(func_name, "missing_node")
            raise KeyError(f"Node '{node_id}' not found")
        log_branch(func_name, "node_present")
        edges = self._reverse_adj.get(node_id, [])
        log_variable_change(func_name, "edges", edges)
        sources = [self.nodes[edge.source] for edge in edges]
        log_variable_change(func_name, "sources", sources)
        return sources

    def to_dict(self) -> Dict[str, object]:
        """Serialize the graph to a dictionary."""
        func_name = "Graph.to_dict"
        log_parameter(func_name)
        node_list = [
            {
                "id": node.id,
                "kind": node.kind.value,
                "handler": node.handler,
                "config": node.config,
                "max_visits": node.max_visits,
                "priority": node.priority,
                "allow_partial_upstream": node.allow_partial_upstream,
            }
            for node in self.nodes.values()
        ]
        log_variable_change(func_name, "node_list", node_list)
        edge_list = [
            {
                "id": edge.id,
                "source": edge.source,
                "target": edge.target,
                "metadata": edge.metadata,
            }
            for edge in self.edges.values()
        ]
        log_variable_change(func_name, "edge_list", edge_list)
        payload = {"nodes": node_list, "edges": edge_list}
        log_variable_change(func_name, "payload", payload)
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Iterable[Dict[str, object]]]) -> "Graph":
        """Deserialize a graph from a dictionary payload."""
        func_name = "Graph.from_dict"
        log_parameter(func_name, payload=payload)
        node_entries = payload.get("nodes", [])
        log_variable_change(func_name, "node_entries", node_entries)
        nodes: Dict[str, Node] = {}
        log_variable_change(func_name, "nodes", nodes)
        for iteration, entry in enumerate(node_entries):
            log_loop_iteration(func_name, "nodes", iteration)
            node = Node(
                id=str(entry["id"]),
                kind=NodeKind(entry["kind"]),
                handler=str(entry["handler"]),
                config=dict(entry.get("config", {})),
                max_visits=entry.get("max_visits"),
                priority=int(entry.get("priority", 0)),
                allow_partial_upstream=bool(entry.get("allow_partial_upstream", False)),
            )
            nodes[node.id] = node
            log_variable_change(func_name, f"nodes[{node.id}]", nodes[node.id])

        edge_entries = payload.get("edges", [])
        log_variable_change(func_name, "edge_entries", edge_entries)
        edges: Dict[str, Edge] = {}
        log_variable_change(func_name, "edges", edges)
        for iteration, entry in enumerate(edge_entries):
            log_loop_iteration(func_name, "edges", iteration)
            edge = Edge(
                id=str(entry["id"]),
                source=str(entry["source"]),
                target=str(entry["target"]),
                metadata=dict(entry.get("metadata", {})),
            )
            edges[edge.id] = edge
            log_variable_change(func_name, f"edges[{edge.id}]", edges[edge.id])

        graph = cls(nodes=nodes, edges=edges)
        log_variable_change(func_name, "graph", graph)
        return graph
