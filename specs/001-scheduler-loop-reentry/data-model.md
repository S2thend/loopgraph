# Data Model: Scheduler Loop Re-entry

**Feature**: 001-scheduler-loop-reentry
**Date**: 2026-02-20

## State Transitions

### Node Status Lifecycle (updated)

```
                    ┌─────────────────────────────┐
                    │                             │
                    ▼                             │
PENDING ──► RUNNING ──► COMPLETED ──► PENDING    │ (reset_for_reentry)
                    │                             │
                    └──► FAILED ──────► PENDING ──┘ (reset_for_reentry)
```

**New transition**: COMPLETED → PENDING and FAILED → PENDING via
`reset_for_reentry()`. This transition:
- Preserves `visits.count` (cumulative, never reset)
- Clears `upstream_completed` (fresh dependency evaluation)
- Removes node from `_completed_nodes` set
- Does NOT modify `outcome` or `last_payload` (overwritten on next execution)

### Visit Count Accumulation

```
Visit 1:  PENDING → RUNNING → COMPLETED  (visits.count: 0 → 1)
          ↓ reset_for_reentry
Visit 2:  PENDING → RUNNING → COMPLETED  (visits.count: 1 → 2)
          ↓ reset_for_reentry
Visit 3:  PENDING → RUNNING → COMPLETED  (visits.count: 2 → 3)
          ↓ max_visits=3 reached → exit route taken
```

## Entity Changes

### ExecutionState (modified)

New method:

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `reset_for_reentry` | `node_id: str` | `None` | Reset COMPLETED/FAILED node to PENDING for re-scheduling. Preserves visit count. |

### Scheduler._execute_node (modified)

| Before | After |
|--------|-------|
| Returns `Any` (handler result) | Returns `Tuple[Any, List[str]]` (handler result + re-entry target node IDs) |

### Graph.validate (modified)

New validation rule:

| Check | Condition | Error |
|-------|-----------|-------|
| Shared-node multi-loop | Any node appears in more than one cycle | `ValueError` listing shared nodes |

## Snapshot Schema

No schema changes. The `reset_for_reentry` operation modifies existing fields
(`status`, `upstream_completed`, `_completed_nodes`) that are already serialized
by `snapshot()` and restored by `restore()`.

Example snapshot after re-entry reset (node "loop_body" reset for visit 2):

```json
{
  "states": {
    "loop_body": {
      "status": "pending",
      "outcome": {"status": "completed", "detail": null, "payload": "result_v1"},
      "visits": {"count": 1, "last_event_id": "loop_body-2"},
      "upstream_completed": [],
      "last_payload": "result_v1"
    }
  },
  "completed_nodes": []
}
```

## Event Model

No event schema changes. `NODE_COMPLETED` events already carry `visit_count`.
After re-entry, the next `NODE_COMPLETED` for the same node will have an
incremented `visit_count`:

| Event # | node_id | type | visit_count |
|---------|---------|------|-------------|
| 1 | loop_body | NODE_COMPLETED | 1 |
| 2 | loop_body | NODE_COMPLETED | 2 |
| 3 | loop_body | NODE_COMPLETED | 3 |
