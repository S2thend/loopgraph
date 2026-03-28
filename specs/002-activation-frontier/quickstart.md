# Quickstart: Activation Frontier Pending Set

**Feature**: 002-activation-frontier
**Date**: 2026-03-28

## What Changed

The scheduler no longer seeds its internal `pending` set with every node in the
graph. Instead, it starts with only entry nodes (nodes with no upstream edges) and
grows the set dynamically as edges are traversed during execution.

This fixes the deadlock where a SWITCH node routing to one branch left unselected
branch nodes stuck in `pending` forever.

## Before (broken)

```python
# Graph: input → decide(SWITCH) → done
#                                → fix
# When decide routes to "done", fix stays in pending forever.
# Scheduler raises: RuntimeError("Scheduler could not make progress")
```

## After (fixed)

```python
# Same graph works correctly.
# Only "input" starts in pending (it's the entry node).
# When "input" completes, "decide" is activated.
# When "decide" completes and routes to "done", only "done" is activated.
# "fix" is never activated → never in pending → no deadlock.
```

## Impact on Existing Code

- **No public API changes.** `Scheduler.run()` signature and return type unchanged.
- **Existing tests pass unchanged.** All loop/re-entry, aggregate, and recovery
  tests continue to work.
- **Snapshot format unchanged.** But resume correctness is only guaranteed for
  snapshots created by this version or later. Old snapshots may need to be
  discarded.
- **New `Graph.entry_nodes()` method** available for querying graph entry points.
- **SWITCH no-match route now raises.** Previously, a SWITCH returning a route
  that matched no downstream edge silently completed with no activation. Now it
  raises `ValueError`.

## Migration: Old Snapshots

Snapshots created by scheduler versions before activation-frontier semantics may
contain PENDING state for nodes that were never truly activated. The new resume
logic cannot distinguish these from genuinely activated nodes. If you have
persisted snapshots from the old scheduler, discard them or migrate manually
before resuming with the new version.

## New Behavior: Zero Entry Nodes

If a graph has nodes but none of them are entry nodes (all have upstream edges),
the scheduler now raises `ValueError` immediately instead of silently deadlocking.

## Resume Behavior

On resume from snapshot:
- Entry nodes not yet completed are added to pending
- Nodes with PENDING status in the snapshot are added to pending
- Nodes with RUNNING status are reset to PENDING and added to pending
- Nodes with no snapshot state and upstream edges are NOT added (never activated)
