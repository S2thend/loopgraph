"""Persistence interfaces for snapshots and event logs."""

from .event_log import EventLog, InMemoryEventLog
from .snapshot import InMemorySnapshotStore, SnapshotStore

__all__ = ["EventLog", "InMemoryEventLog", "SnapshotStore", "InMemorySnapshotStore"]
