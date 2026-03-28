# Data Model: Activation Frontier Pending Set

**Feature**: 002-activation-frontier
**Date**: 2026-03-28

## Entities

No new entities are introduced. This feature modifies the runtime semantics of an
existing internal data structure (the `pending` set in `Scheduler.run()`).

### Modified: Pending Set (internal to `Scheduler.run()`)

**Before**: `Set[str]` — all graph node IDs minus completed node IDs.

**After**: `Set[str]` — activation frontier. Contains only node IDs that have been
explicitly activated via one of:
1. Being an entry node (no upstream edges) at run start
2. Being downstream of a completed node via a traversed edge
3. Being a re-entry target reset by `reset_for_reentry`
4. Being persisted as PENDING or RUNNING in a resumed snapshot

### Unchanged: `ExecutionState`

No schema changes. The snapshot format (`states`, `completed_nodes`) is unchanged.
RUNNING nodes in snapshots are reset to PENDING status in-memory during resume but
the snapshot itself is not rewritten.

### Unchanged: `Graph`

No structural changes. A new query method `entry_nodes()` is added but it reads
existing `_reverse_adj` data — no new fields or indices.

## State Transitions

The node lifecycle remains unchanged:

```
PENDING → RUNNING → COMPLETED
                  → FAILED
COMPLETED → PENDING (via reset_for_reentry, for loop re-entry)
RUNNING → PENDING (on resume from snapshot only)
```

The only change is *when* a node enters the PENDING state for the first time:
- **Before**: All nodes start as PENDING implicitly (by being in the `pending` set)
- **After**: Nodes enter PENDING only when activated (entry node, downstream of
  traversed edge, or restored from snapshot)

## Validation Rules

- **FR-011**: If `graph.entry_nodes()` returns empty and `graph.nodes` is non-empty,
  raise `ValueError` before the scheduling loop.
