# Feature Specification: Scheduler Loop Re-entry

**Feature Branch**: `001-scheduler-loop-reentry`
**Created**: 2026-02-20
**Status**: Draft
**Input**: User description: "Allow the scheduler to re-enter completed nodes via SWITCH back-edges by resetting them to PENDING, bounded by max_visits."

## Clarifications

### Session 2026-02-20

- Q: What loop topology must this feature guarantee as in-scope for this iteration? → A: Support loop cycles of arbitrary length and allow multiple disjoint loops; explicitly disallow multiple loops sharing nodes.
- Q: If a SWITCH back-edge targets a node that is not COMPLETED (PENDING/RUNNING/FAILED), what should the scheduler do? → A: Keep re-entry scoped to COMPLETED targets, hard-stop with an error for non-terminal targets (PENDING or RUNNING), and explicitly disallow multiple loops that share nodes.
- Q: Should loop execution continue after a handler exception, or remain fail-fast? → A: Keep current fail-fast behavior in core; handler exceptions emit `NODE_FAILED` and abort `Scheduler.run()`. Error-tolerant flows are implemented by user handlers.
- Q: Where should we enforce the rule that multiple loops sharing nodes are disallowed? → A: Enforce during graph construction/validation, before `Scheduler.run()`.
- Q: Should the graph allow multiple loops when they are disjoint? → A: Allow multiple disjoint loops; reject only loops that share nodes.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Bounded Loop Execution (Priority: P1)

A workflow author defines a graph with a SWITCH node that routes back to a previously completed node (back-edge) to implement iterative processing. The loop body node declares `max_visits` to guarantee termination. The scheduler automatically re-enters the loop body on each back-edge activation and exits via an alternate route once the visit limit is reached.

**Why this priority**: This is the core capability. Without it, loops cannot be expressed natively in the graph — users must manually reset internal state or wrap the scheduler in external retry logic, both of which are fragile and violate the graph-driven execution model.

**Independent Test**: Can be fully tested by constructing a graph with a SWITCH back-edge targeting a node with `max_visits=N`, running `Scheduler.run()`, and asserting the loop body executes exactly N times before the exit route is taken.

**Acceptance Scenarios**:

1. **Given** a graph where a SWITCH node routes back to a loop body node with `max_visits=3`, **When** the scheduler runs the graph, **Then** the loop body node executes exactly 3 times and the exit route node executes exactly once.
2. **Given** a graph where the SWITCH handler returns the back-edge route while the target node still has remaining visits, **When** the scheduler processes the SWITCH result, **Then** the target node is reset to schedulable state and re-added to the scheduling queue.
3. **Given** a graph where the SWITCH handler returns the back-edge route but the target node has exhausted its `max_visits`, **When** the scheduler processes the SWITCH result, **Then** the exit route edge is selected instead and the loop terminates.

---

### User Story 2 - Unbounded Loop with Handler-Controlled Exit (Priority: P2)

A workflow author defines a loop where the loop body node has no `max_visits` limit (`max_visits=None`). The SWITCH handler itself decides when to exit the loop by returning a different route (e.g., "done" instead of "continue"). The scheduler continues re-entering the loop body indefinitely until the handler signals completion.

**Why this priority**: Some workflows require dynamic termination conditions that cannot be expressed as a fixed visit count (e.g., "keep polling until a resource becomes available"). This scenario builds on P1 and requires no additional scheduler logic beyond what P1 delivers — the same re-entry mechanism works, just without a visit ceiling.

**Independent Test**: Can be tested by constructing a graph where the SWITCH handler returns "continue" for a variable number of iterations and then returns "done", asserting the loop body runs the expected number of times.

**Acceptance Scenarios**:

1. **Given** a graph where the loop body has `max_visits=None` and the SWITCH handler returns "continue" 5 times then "done", **When** the scheduler runs the graph, **Then** the loop body executes exactly 5 times and the exit node executes once.

---

### User Story 3 - Visit Count Observability (Priority: P3)

A workflow operator monitors loop progress through the event log. Each time a loop body node completes a visit, the emitted `NODE_COMPLETED` event carries an accurate `visit_count` reflecting the cumulative number of times the node has executed, including across re-entries.

**Why this priority**: Observability is essential for debugging and operational monitoring of looping workflows, but it builds on the re-entry mechanism from P1/P2 rather than enabling new behavior.

**Independent Test**: Can be tested by subscribing to the event bus, running a looping graph, and asserting that `visit_count` on successive `NODE_COMPLETED` events for the loop body node increments from 1 to N.

**Acceptance Scenarios**:

1. **Given** a graph with a loop body node that executes 3 times via back-edge re-entry, **When** the scheduler emits `NODE_COMPLETED` events for the loop body, **Then** the `visit_count` field on those events is 1, 2, and 3 respectively.
2. **Given** a resumed execution where the loop body had already completed 2 visits in a prior run, **When** the scheduler re-enters the loop body and it completes again, **Then** the `visit_count` on the new `NODE_COMPLETED` event is 3.

---

### Edge Cases

- What happens when a node fails during loop execution? Existing fail-fast behavior remains: the scheduler emits `NODE_FAILED` and raises, so no automatic back-edge re-entry is attempted for FAILED nodes in the same run.
- What happens when a back-edge targets a node with `max_visits=1`? The node executes once during its initial scheduling; when the back-edge fires, the node has already exhausted its visits so the exit route is taken immediately.
- What happens when a SWITCH node has a back-edge to itself? This is a degenerate case. The SWITCH node would need `allow_partial_upstream=True` and its own `max_visits` to avoid infinite self-recursion.
- What happens when a back-edge targets a node currently in PENDING or RUNNING? The scheduler raises an error immediately (hard stop) because non-terminal re-entry indicates an invalid concurrent loop topology.
- What happens when multiple loops share one or more nodes? This topology is out of scope and must be rejected during graph construction/validation before execution begins.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The scheduler MUST reset a completed node to a schedulable state when a SWITCH back-edge selects it and the node has remaining visits (`visit_count < max_visits` or `max_visits` is unset).
- **FR-002**: The scheduler MUST re-add the reset node to the active scheduling queue so it is picked up in a subsequent iteration of the scheduling loop.
- **FR-003**: The scheduler MUST NOT reset a node's cumulative visit count during re-entry. The visit count MUST continue to accumulate across all executions of the node.
- **FR-004**: The scheduler MUST NOT reset a completed node when the node has reached its `max_visits` limit. In this case, the existing exit-route fallback behavior MUST apply.
- **FR-005**: The scheduler MUST clear the target node's upstream-completion tracking during re-entry so that readiness is re-evaluated from scratch for the new iteration.
- **FR-006**: The execution state MUST provide a dedicated method to perform re-entry reset (status to PENDING, clear upstream tracking, remove from completed set) as a single atomic operation.
- **FR-007**: The re-entry reset MUST preserve snapshot/restore compatibility. A snapshot taken after a re-entry reset MUST correctly restore to the reset state.
- **FR-008**: `NODE_COMPLETED` events emitted after re-entry executions MUST carry the correct cumulative `visit_count`.
- **FR-009**: Re-entry behavior MUST support loop cycles of arbitrary length formed by SWITCH back-edges (not only self-loops or two-node loops), including multiple disjoint loops, while preserving `max_visits` and route-based exit semantics.
- **FR-010**: If a selected back-edge target is non-terminal (`PENDING` or `RUNNING`), the scheduler MUST raise an explicit runtime error and stop execution.
- **FR-011**: Graph topologies containing multiple loops that share one or more nodes MUST be rejected during graph construction/validation (before `Scheduler.run()`).
- **FR-012**: Handler failure behavior MUST remain fail-fast for this feature: on handler exception, the scheduler emits `NODE_FAILED`, persists state, and re-raises without introducing new core-level failure-mode switches.

### Key Entities

- **NodeRuntimeState**: Per-node mutable state tracking status, visit count, upstream completion, and last payload. Re-entry resets status to PENDING and clears upstream tracking without modifying visit count.
- **ExecutionState**: Container for all node runtime states and the completed-nodes set. Gains a new `reset_for_reentry` operation that atomically resets a node for re-scheduling.
- **Back-edge**: A directed edge from a SWITCH node back to an earlier node in the graph, identified by the SWITCH handler returning a route that matches the edge's route metadata.

## Constitution Alignment *(mandatory)*

- **Core Boundary**: This feature modifies `ExecutionState` (adding `reset_for_reentry`) and `Scheduler` (re-entry logic after downstream edge selection). These changes are justified because re-entry is a scheduling primitive — it determines when a node becomes eligible for execution — which is squarely within the scheduler's responsibility for "dependency resolution, handler dispatch, and state/event persistence" (Principle I). The behavior cannot be composed outside core without duplicating internal scheduling state management.

- **Execution Semantics Impact**: Node readiness semantics change: a `COMPLETED` node can now transition back to `PENDING` via `reset_for_reentry`, making it eligible for `is_ready()` again. The existing `max_visits` check in `is_ready()` and `_has_remaining_visits()` continues to enforce the upper bound. If a selected back-edge target is already `PENDING` or `RUNNING`, the scheduler hard-stops with an explicit error. SWITCH routing, AGGREGATE readiness, and default edge selection are otherwise unaffected.

- **Failure and Retry Strategy**: Existing fail-fast behavior remains unchanged: when a handler raises, the scheduler emits `NODE_FAILED` and re-raises the exception. This preserves Principle IV by keeping retry/error-tolerance policies in user handlers and workflow logic rather than adding new core-level failure strategy switches.

- **Concurrency Policy**: No change to `ConcurrencyManager` behavior. Re-entered nodes acquire concurrency slots through the same `slot(key, priority)` mechanism as initial executions (Principle V).

- **Recovery and Persistence**: `reset_for_reentry` produces a state that is fully snapshot-compatible. The reset sets `status=PENDING`, clears `upstream_completed`, and removes from `_completed_nodes` — all of which are serialized fields. `snapshot()` / `restore()` round-trips remain correct (Principle VI).

- **Debug & Logging Plan**: The new `reset_for_reentry` method MUST use `eventflow._debug` helpers (`log_parameter`, `log_variable_change`, `log_branch`) to trace the reset operation. The re-entry detection logic in the scheduler MUST log which nodes are being re-queued. All debug logging follows existing gating via `logging.getLogger` (Principle VIII).

- **Typing & Compatibility Plan**: `reset_for_reentry` is a new public method on `ExecutionState` — additive, no breaking change. The `_execute_node` return type changes from `Any` to `Tuple[Any, List[str]]` — this is an internal method (underscore-prefixed), so no public API impact. Type annotations MUST be complete and pass mypy (Principle IX).

- **Abstraction & Dependency Plan**: No new interfaces or protocols are introduced. The change stays within the existing `ExecutionState` / `Scheduler` boundary. No circular dependencies are created (Principle XII).

- **Validation Plan**:
  - Unit test: `reset_for_reentry` correctly resets status, clears upstream tracking, removes from completed set, and preserves visit count.
  - Integration test (bounded): `Scheduler.run()` with a back-edge graph and `max_visits=N` executes the loop body exactly N times.
  - Integration test (unbounded): `Scheduler.run()` with `max_visits=None` and handler-controlled exit executes the expected number of iterations.
  - Regression test (failure path): handler exceptions still emit `NODE_FAILED`, persist snapshot, and abort `Scheduler.run()` (unchanged fail-fast behavior).
  - Integration test (hard stop): selecting a back-edge to a `PENDING` or `RUNNING` target raises an explicit runtime error.
  - Topology validation test: graph construction/validation rejects graphs with multiple loops sharing one or more nodes before `Scheduler.run()`.
  - Topology validation test: graph construction/validation accepts graphs containing multiple disjoint loops.
  - Event observability test: `visit_count` on `NODE_COMPLETED` events is correct across re-entries.
  - Doctest: `reset_for_reentry` includes a docstring with executable example.
  - Doctest gate: `python -m pytest --doctest-modules eventflow/core/state.py` passes.
  - Type check: `mypy` passes with repository configuration.
  - Lint: `ruff check` passes.
  - Snapshot round-trip test: `snapshot()` after re-entry correctly `restore()`s.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A bounded loop graph with `max_visits=N` completes with the loop body executing exactly N times, verified by event log inspection — no manual state resets required.
- **SC-002**: An unbounded loop graph with `max_visits=None` completes with the loop body executing exactly the number of times the handler signals "continue", verified by event log inspection.
- **SC-003**: All existing scheduler tests continue to pass without modification, confirming backward compatibility.
- **SC-004**: `visit_count` on `NODE_COMPLETED` events accurately reflects cumulative executions across re-entries, verified by event bus subscription in tests.
- **SC-005**: Snapshot taken mid-loop correctly restores and resumes execution from the interrupted iteration, verified by a snapshot round-trip test.
- **SC-006**: Failure-path behavior remains unchanged: on handler exception the scheduler emits `NODE_FAILED` and aborts execution.
- **SC-007**: A graph containing multiple loops that share nodes is rejected at graph construction/validation with an explicit topology error.
- **SC-008**: A graph containing multiple disjoint loops passes graph validation and executes without loop-topology errors.
