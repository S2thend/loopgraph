"""Snapshot persistence interfaces with in-memory reference implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Protocol

from .._debug import log_branch, log_parameter, log_variable_change

SnapshotPayload = Mapping[str, object]


class SnapshotStore(Protocol):
    """Protocol defining snapshot persistence operations.

    >>> store = InMemorySnapshotStore()
    >>> store.save("graph-1", {"state": 1})
    >>> store.load("graph-1")["state"]
    1
    """

    def save(self, graph_id: str, snapshot: SnapshotPayload) -> None:
        """Persist a snapshot for a graph."""
        ...

    def load(self, graph_id: str) -> SnapshotPayload:
        """Load the latest snapshot for a graph."""
        ...


@dataclass
class InMemorySnapshotStore(SnapshotStore):
    """Keep snapshots in memory for testing and examples."""

    _snapshots: Dict[str, SnapshotPayload] = field(default_factory=dict)

    def save(self, graph_id: str, snapshot: SnapshotPayload) -> None:
        func_name = "InMemorySnapshotStore.save"
        log_parameter(func_name, graph_id=graph_id, snapshot=snapshot)
        self._snapshots[graph_id] = snapshot
        log_variable_change(func_name, f"self._snapshots[{graph_id!r}]", snapshot)

    def load(self, graph_id: str) -> SnapshotPayload:
        func_name = "InMemorySnapshotStore.load"
        log_parameter(func_name, graph_id=graph_id)
        if graph_id not in self._snapshots:
            log_branch(func_name, "missing_snapshot")
            raise KeyError(f"Snapshot for graph '{graph_id}' not found")
        log_branch(func_name, "snapshot_found")
        snapshot = self._snapshots[graph_id]
        log_variable_change(func_name, "snapshot", snapshot)
        return snapshot
