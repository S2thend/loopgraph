# Research: Scheduler Loop Re-entry

**Feature**: 001-scheduler-loop-reentry
**Date**: 2026-02-20

## Research Questions

### R1: How should the scheduler detect and perform back-edge re-entry?

**Decision**: After `_execute_node` processes downstream edges, check each
selected edge target's state. If the target is COMPLETED and has remaining visits
(or unlimited visits), call `reset_for_reentry` and return the target as a
re-entry candidate. The caller (`run()`) re-adds these targets to the `pending`
set.

**Rationale**: This approach is minimal and localized:
- `_execute_node` already iterates over selected edges and calls
  `note_upstream_completion` (scheduler.py:267-272). Adding re-entry detection
  here is a natural extension.
- Returning re-entry targets (instead of mutating `pending` directly) keeps
  `_execute_node` side-effect-free with respect to the scheduling queue.
- The `run()` method already manages `pending` and can simply `pending.add(target)`
  for each re-entry target.

**Alternatives considered**:
- Passing `pending` into `_execute_node`: Rejected because it couples the
  execution method to the scheduling loop's internal data structure.
- Having `_execute_node` emit an event that `run()` listens to: Over-engineered
  for a synchronous call within the same method.

### R2: What state must be reset during re-entry?

**Decision**: `reset_for_reentry(node_id)` performs three operations:
1. Set `status` to `NodeStatus.PENDING`
2. Clear `upstream_completed` set
3. Remove from `_completed_nodes` set

Visit count (`visits.count`) is NOT reset — it accumulates across all executions
and is how `max_visits` enforces the bound.

**Rationale**: These are exactly the three things that prevent a completed node
from being re-scheduled:
- `is_ready()` rejects non-PENDING status (state.py:196)
- `_completed_nodes` is checked by downstream `is_ready()` calls (state.py:235)
- `upstream_completed` must be cleared so the node re-evaluates its upstream
  dependencies from scratch for the new iteration

The existing test `test_loop_respects_max_visits` (test_integration_workflows.py:
176-186) manually performs exactly these three operations, confirming this is the
correct reset surface.

**Alternatives considered**:
- Also resetting `outcome` and `last_payload`: Rejected. These are informational
  and will be overwritten on the next execution. Keeping them allows inspection
  of the last iteration's result between re-entry and re-execution.

### R3: How should shared-node multi-loop topologies be detected?

**Decision**: Add cycle detection to `Graph.validate()` that finds all cycles in
the graph and checks whether any node appears in more than one cycle. If so,
raise `ValueError` with a descriptive message listing the shared nodes and the
cycles they belong to.

**Rationale**: `Graph.validate()` already performs structural checks (edge
connectivity, handler presence, SWITCH route metadata, AGGREGATE config). Adding
topology validation here is consistent with the existing pattern and ensures
invalid graphs are rejected before `Scheduler.run()`.

Algorithm: Use DFS-based cycle detection via the forward adjacency map. For each
cycle found, record the set of participating nodes. Then check for node
intersection across cycles. This is O(V+E), acceptable for workflow-sized graphs.

**Alternatives considered**:
- Validating at `Scheduler.run()` time: Rejected. Late detection wastes
  execution and is harder to debug. The constitution requires graph construction
  rejection (XIV).
- Using edge metadata to mark back-edges explicitly: Rejected. Back-edges are
  determined by SWITCH routing at runtime, not statically. However, cycles in the
  graph topology can be detected statically regardless of SWITCH behavior.

### R4: What should happen when a back-edge targets a FAILED node?

**Decision**: Allow re-entry for FAILED nodes. `reset_for_reentry` resets status
to PENDING regardless of whether the prior status was COMPLETED or FAILED. The
SWITCH handler made the routing decision, so this is handler-driven re-entry, not
framework-automatic retry.

**Rationale**: This is consistent with Principle IV (handler-owned retries). The
SWITCH handler explicitly chose to route back to the failed node — the framework
respects that decision. The visit count still accumulated on the failed execution
(via `mark_failed`), so `max_visits` still bounds total attempts.

### R5: What should happen when a back-edge targets a PENDING or RUNNING node?

**Decision**: Raise `RuntimeError` immediately (hard stop). This indicates an
invalid concurrent topology that should have been caught at graph validation time.

**Rationale**: In a single-loop topology, a back-edge target is always in a
terminal state (COMPLETED or FAILED) when the SWITCH executes, because the
SWITCH depends on the loop body completing first. A PENDING/RUNNING target
implies either shared-node multi-loop (which should be caught at validation)
or a bug in the scheduler.

### R6: Should `_execute_node` return type change?

**Decision**: Yes. Change from `Any` to `Tuple[Any, List[str]]` where the second
element is the list of node IDs that need re-queuing.

**Rationale**: `_execute_node` is an internal method (underscore-prefixed), so
this is not a public API change. The tuple return cleanly separates the handler
result from the re-entry side-effect without mutating external state.

**Alternatives considered**:
- Using a dataclass/NamedTuple for the return type: Slightly cleaner but
  over-engineered for a two-element internal return value.
