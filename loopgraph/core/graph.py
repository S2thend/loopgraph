"""Graph primitives describing workflow structure."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple, cast

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

            if node.kind is NodeKind.SWITCH:
                log_branch(func_name, "switch_node_check")
                switch_edges = self._forward_adj.get(node.id, [])
                log_variable_change(func_name, "switch_edges", switch_edges)
                has_self_loop = any(
                    edge.source == edge.target == node.id for edge in switch_edges
                )
                log_variable_change(func_name, "has_self_loop", has_self_loop)
                if has_self_loop:
                    log_branch(func_name, "switch_self_loop")
                    raise ValueError(
                        f"Switch node '{node.id}' cannot have a self-loop edge"
                    )
                missing_route = [
                    edge.id for edge in switch_edges if "route" not in edge.metadata
                ]
                log_variable_change(func_name, "missing_route", missing_route)
                if missing_route:
                    log_branch(func_name, "switch_missing_route")
                    raise ValueError(
                        f"Switch node '{node.id}' requires route metadata on edges: {missing_route}"
                    )
            elif node.kind is NodeKind.AGGREGATE:
                log_branch(func_name, "aggregate_node_check")
                required_raw = node.config.get("required")
                log_variable_change(func_name, "required_raw", required_raw)
                if required_raw is not None:
                    if not isinstance(required_raw, int):
                        log_branch(func_name, "aggregate_required_not_int")
                        raise ValueError(
                            f"Aggregate node '{node.id}' requires integer 'required' config"
                        )
                    if required_raw <= 0:
                        log_branch(func_name, "aggregate_required_non_positive")
                        raise ValueError(
                            f"Aggregate node '{node.id}' requires 'required' > 0"
                        )
                    upstream_count = len(self.upstream_nodes(node.id))
                    log_variable_change(
                        func_name, "upstream_count", upstream_count
                    )
                    if required_raw > upstream_count:
                        log_branch(func_name, "aggregate_required_exceeds_upstream")
                        raise ValueError(
                            f"Aggregate node '{node.id}' requires {required_raw} upstream nodes but only has {upstream_count}"
                        )

        if invalid_handlers:
            log_branch(func_name, "invalid_handlers_error")
            raise ValueError(f"Nodes missing handlers: {invalid_handlers}")
        log_branch(func_name, "handlers_valid")
        cycles = self._find_cycles()
        log_variable_change(func_name, "cycles", cycles)
        cycle_node_sets = [set(cycle) for cycle in cycles]
        log_variable_change(func_name, "cycle_node_sets", cycle_node_sets)
        shared_nodes: Set[str] = set()
        log_variable_change(func_name, "shared_nodes", shared_nodes)
        for left_idx, left in enumerate(cycle_node_sets):
            log_loop_iteration(func_name, "left_cycle", left_idx)
            for right_idx in range(left_idx + 1, len(cycle_node_sets)):
                overlap = left & cycle_node_sets[right_idx]
                log_variable_change(func_name, "overlap", overlap)
                if overlap:
                    log_branch(func_name, "shared_nodes_detected")
                    shared_nodes.update(overlap)
                    log_variable_change(func_name, "shared_nodes", shared_nodes)
        if shared_nodes:
            log_branch(func_name, "shared_node_multi_loop_error")
            shared_list = sorted(shared_nodes)
            log_variable_change(func_name, "shared_list", shared_list)
            raise ValueError(
                f"Graph has multi-loop shared nodes: {shared_list}"
            )
        log_branch(func_name, "cycle_validation_passed")

    @staticmethod
    def _canonical_cycle(cycle: List[str]) -> Tuple[str, ...]:
        """Normalize a cycle so equivalent rotations share one representation."""
        cycle_len = len(cycle)
        rotations = [
            tuple(cycle[index:] + cycle[:index]) for index in range(cycle_len)
        ]
        return min(rotations)

    def _find_cycles(self) -> List[Tuple[str, ...]]:
        """Find directed simple cycles in the graph."""
        func_name = "Graph._find_cycles"
        log_parameter(func_name)
        adjacency: Dict[str, List[str]] = {
            node_id: [edge.target for edge in self._forward_adj.get(node_id, [])]
            for node_id in self.nodes
        }
        log_variable_change(func_name, "adjacency", adjacency)
        seen: Set[Tuple[str, ...]] = set()
        log_variable_change(func_name, "seen", seen)

        def dfs(
            start: str,
            current: str,
            path: List[str],
            in_path: Set[str],
        ) -> None:
            for neighbor in adjacency.get(current, []):
                if neighbor == start and len(path) > 1:
                    canonical = self._canonical_cycle(path)
                    seen.add(canonical)
                    continue
                if neighbor in in_path:
                    continue
                path.append(neighbor)
                in_path.add(neighbor)
                dfs(start, neighbor, path, in_path)
                in_path.remove(neighbor)
                path.pop()

        for iteration, start in enumerate(sorted(self.nodes)):
            log_loop_iteration(func_name, "cycle_start_nodes", iteration)
            dfs(start, start, [start], {start})

        cycles = sorted(seen)
        log_variable_change(func_name, "cycles", cycles)
        return cycles

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

    def downstream_edges(self, node_id: str) -> List[Edge]:
        """Return edges originating from the given node.

        >>> graph = Graph(
        ...     nodes={
        ...         "a": Node(id="a", kind=NodeKind.TASK, handler="A"),
        ...         "b": Node(id="b", kind=NodeKind.TASK, handler="B"),
        ...     },
        ...     edges={"e": Edge(id="e", source="a", target="b")},
        ... )
        >>> [edge.id for edge in graph.downstream_edges("a")]
        ['e']
        """

        func_name = "Graph.downstream_edges"
        log_parameter(func_name, node_id=node_id)
        if node_id not in self.nodes:
            log_branch(func_name, "missing_node")
            raise KeyError(f"Node '{node_id}' not found")
        log_branch(func_name, "node_present")
        edges = list(self._forward_adj.get(node_id, []))
        log_variable_change(func_name, "edges", edges)
        return edges

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
    def from_dict(cls, payload: Mapping[str, Iterable[Mapping[str, object]]]) -> "Graph":
        """Deserialize a graph from a dictionary payload."""
        func_name = "Graph.from_dict"
        log_parameter(func_name, payload=payload)
        empty_nodes: Iterable[Mapping[str, object]] = []
        node_entries = payload.get("nodes", empty_nodes)
        log_variable_change(func_name, "node_entries", node_entries)
        nodes: Dict[str, Node] = {}
        log_variable_change(func_name, "nodes", nodes)
        for iteration, entry in enumerate(node_entries):
            log_loop_iteration(func_name, "nodes", iteration)
            config_entry = entry.get("config", {})
            config = (
                dict(cast(Mapping[str, Any], config_entry))
                if isinstance(config_entry, Mapping)
                else {}
            )
            log_variable_change(func_name, "config", config)
            max_visits_value = entry.get("max_visits")
            max_visits = cast(Optional[int], max_visits_value)
            log_variable_change(func_name, "max_visits", max_visits)
            priority_value = cast(Optional[int], entry.get("priority"))
            priority = priority_value if priority_value is not None else 0
            log_variable_change(func_name, "priority", priority)
            allow_partial_value = entry.get("allow_partial_upstream", False)
            log_variable_change(func_name, "allow_partial_value", allow_partial_value)
            node = Node(
                id=str(entry["id"]),
                kind=NodeKind(entry["kind"]),
                handler=str(entry["handler"]),
                config=config,
                max_visits=max_visits,
                priority=priority,
                allow_partial_upstream=bool(allow_partial_value),
            )
            nodes[node.id] = node
            log_variable_change(func_name, f"nodes[{node.id}]", nodes[node.id])

        empty_edges: Iterable[Mapping[str, object]] = []
        edge_entries = payload.get("edges", empty_edges)
        log_variable_change(func_name, "edge_entries", edge_entries)
        edges: Dict[str, Edge] = {}
        log_variable_change(func_name, "edges", edges)
        for iteration, entry in enumerate(edge_entries):
            log_loop_iteration(func_name, "edges", iteration)
            metadata_entry = entry.get("metadata", {})
            metadata = (
                dict(cast(Mapping[str, Any], metadata_entry))
                if isinstance(metadata_entry, Mapping)
                else {}
            )
            log_variable_change(func_name, "metadata", metadata)
            edge = Edge(
                id=str(entry["id"]),
                source=str(entry["source"]),
                target=str(entry["target"]),
                metadata=metadata,
            )
            edges[edge.id] = edge
            log_variable_change(func_name, f"edges[{edge.id}]", edges[edge.id])

        graph = cls(nodes=nodes, edges=edges)
        log_variable_change(func_name, "graph", graph)
        return graph
