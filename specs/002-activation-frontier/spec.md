# Feature Specification: Activation Frontier Pending Set

**Feature Branch**: `002-activation-frontier`
**Created**: 2026-03-28
**Status**: Draft
**Input**: User description: "Seed pending from entry nodes and grow it only as edges are actually activated, so unselected SWITCH branches never enter the set."

## Clarifications

### Session 2026-03-28

- Q: How should nodes in RUNNING state in a snapshot be handled on resume? → A: Treat RUNNING nodes as PENDING (reset to PENDING and add to the activation frontier), since a RUNNING node in a snapshot means it never finished.

### Session 2026-03-29

- Q: How should resume behave for snapshots created by the old scheduler, which may contain legacy `PENDING` state for nodes that were never truly activated? → A: Reject unsupported legacy snapshots at resume time using an explicit `snapshot_format_version` check and a clear `ValueError`; this feature does not attempt in-place migration.
- Q: On a fresh run, if the graph has no entry nodes at all, what should the scheduler do? → A: Fail fast with a new `ValueError` that explicitly says the graph has no entry nodes.
- Q: Should this feature change the runtime meaning of `NodeKind.TERMINAL`, or keep it out of scope? → A: Do not change `NodeKind.TERMINAL` semantics in this feature; it remains behaviorally equivalent to `TASK` for scheduling purposes.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - SWITCH to terminal leaf completes without deadlock (Priority: P1)

A workflow author builds a graph where a SWITCH node routes to one of two leaf branches (e.g. `decide → done` vs `decide → fix`). When the SWITCH selects `done`, the workflow completes successfully. The unselected branch (`fix`) never blocks completion.

**Why this priority**: This is the exact bug reported in issue #5. Without this fix, any graph with a SWITCH that leaves an unselected leaf branch causes a `RuntimeError("Scheduler could not make progress")`.

**Independent Test**: Build a graph with `[input] → [decide(SWITCH)] → [done]` and `[decide] → [fix]`. Route to `done`. Verify the scheduler returns results without raising.

**Acceptance Scenarios**:

1. **Given** a graph where a SWITCH node has two downstream branches, **When** the SWITCH handler returns a route that selects only one branch, **Then** the scheduler completes successfully and returns results for all executed nodes.
2. **Given** the same graph, **When** the SWITCH selects the other branch instead, **Then** the scheduler also completes successfully with results for that path.
3. **Given** a graph where a SWITCH has three or more downstream branches, **When** only one is selected, **Then** the remaining branches do not block completion.

---

### User Story 2 - Loop re-entry with SWITCH still works (Priority: P1)

A workflow author builds a loop where a SWITCH routes back to an earlier node (`continue`) or exits (`done`). The SWITCH selects `continue` on early iterations and `done` on the final iteration. The unselected branch on each iteration does not block progress, and the loop completes after the expected number of visits.

**Why this priority**: Equal to P1 because this is the existing loop/re-entry behavior that must not regress. The fix must not eagerly skip unselected branches in a way that prevents them from being selected on a later loop iteration.

**Independent Test**: Use the existing loop graph pattern (`start → loop → switch → loop` / `switch → out`). Verify `loop` executes the expected number of times and `out` receives the final result.

**Acceptance Scenarios**:

1. **Given** a loop graph with `max_visits=3` on the loop body, **When** the SWITCH returns `continue` twice then `done`, **Then** the loop body executes 3 times and the exit node receives the final payload.
2. **Given** the same loop graph, **When** the SWITCH returns `done` on the first iteration, **Then** the loop body executes once and the exit node completes.

---

### User Story 3 - Resume from snapshot with activated pending nodes (Priority: P2)

A workflow is interrupted mid-execution and a supported snapshot is persisted. On resume, nodes that were already activated (status PENDING with upstream_completed entries) are correctly placed back into the pending set. Nodes that were never activated are not. Snapshots that do not carry the supported activation-frontier snapshot version are rejected explicitly instead of being resumed heuristically.

**Why this priority**: Resume correctness is critical for production use but is a secondary scenario to the primary deadlock fix.

**Independent Test**: Create a supported snapshot where some nodes are COMPLETED, some are PENDING with upstream_completed entries, and some have no state. Resume and verify only the correct nodes enter pending.

**Acceptance Scenarios**:

1. **Given** a supported persisted snapshot where node A is COMPLETED and node B is PENDING with upstream_completed={A}, **When** the scheduler resumes, **Then** node B is in the pending set and can execute.
2. **Given** a supported persisted snapshot where node C has no state entry (never activated), **When** the scheduler resumes, **Then** node C is not in the pending set unless it is an entry node.
3. **Given** a persisted snapshot whose `snapshot_format_version` is missing or unsupported, **When** the scheduler resumes, **Then** it raises a `ValueError` and does not attempt execution from that snapshot.

---

### User Story 4 - Merge/aggregate nodes wait in pending until enough upstreams complete (Priority: P2)

A workflow contains an AGGREGATE node that requires multiple upstream completions. The AGGREGATE node enters the pending set when its first upstream activates it, but does not become ready until the required number of upstreams have completed.

**Why this priority**: Aggregate behavior must remain correct under the new activation model but is not directly affected by the SWITCH bug.

**Independent Test**: Build a fan-out/fan-in graph with two TASK nodes feeding an AGGREGATE. Verify the AGGREGATE waits for both before executing.

**Acceptance Scenarios**:

1. **Given** an AGGREGATE node with `required=2` and two upstream TASK nodes, **When** only one upstream completes, **Then** the AGGREGATE is in pending but not ready.
2. **Given** the same graph, **When** both upstreams complete, **Then** the AGGREGATE becomes ready and executes.

---

### Edge Cases

- What happens when a SWITCH returns a route that matches no downstream edge? The scheduler MUST raise a `ValueError` identifying the unmatched route and the SWITCH node.
- What happens when all downstream branches of a SWITCH are exhausted (`max_visits` reached)? The exit/fallback edge logic should still apply.
- What happens when a graph has no entry nodes (all nodes have upstream edges)? The scheduler fails fast with a `ValueError` that explicitly reports the graph has no entry nodes.
- What happens when a resumed snapshot contains a node in RUNNING state? The scheduler resets it to PENDING and adds it to the activation frontier, since RUNNING in a snapshot means the node never finished.
- What happens when a resumed snapshot is missing `snapshot_format_version` or carries an unsupported version? The scheduler rejects it with a `ValueError` that identifies the unsupported version boundary and recommends discard or migration.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: On a fresh run, the scheduler MUST seed the pending set with only entry nodes (nodes that have no upstream edges in the graph).
- **FR-002**: When a node completes, the scheduler MUST add to the pending set only the downstream targets that were actually activated via `_determine_downstream_edges`.
- **FR-003**: For non-SWITCH nodes, all downstream edge targets MUST be activated (added to pending if not already present or completed).
- **FR-004**: For SWITCH nodes, only the selected route's target (or fallback exit target) MUST be activated. Unselected branch targets MUST NOT be added to pending.
- **FR-005**: For re-entry targets (already-completed nodes reset via `reset_for_reentry`), the scheduler MUST re-add them to pending as it does today.
- **FR-006**: On resume from a supported snapshot, the scheduler MUST seed pending with: (a) entry nodes that are not yet completed, (b) nodes persisted with PENDING status in the snapshot, and (c) nodes persisted with RUNNING status in the snapshot (reset to PENDING, since RUNNING in a snapshot means the node never finished).
- **FR-007**: Nodes that were never activated (no state entry in the snapshot and not an entry node) MUST NOT appear in the pending set on resume.
- **FR-008**: The `is_ready()` gate MUST continue to govern when a pending node is actually scheduled for execution. Being in pending means "activated", not "ready".
- **FR-009**: The existing deadlock detection (`RuntimeError("Scheduler could not make progress")`) MUST remain as a safety net for genuinely stuck graphs.
- **FR-010**: Snapshots produced by scheduler versions that implement activation-frontier semantics MUST include an explicit `snapshot_format_version` in the persisted payload.
- **FR-011**: On resume, if the persisted snapshot is missing `snapshot_format_version` or carries an unsupported version, the scheduler MUST raise a `ValueError` identifying the unsupported version boundary and recommending discard or migration. It MUST NOT attempt execution from that snapshot.
- **FR-012**: On a fresh run, if the graph has zero entry nodes, the scheduler MUST fail fast with a `ValueError` that explicitly reports the graph has no entry nodes.
- **FR-013**: This feature MUST NOT change the runtime semantics of `NodeKind.TERMINAL`; terminal nodes continue to follow the same scheduling behavior as task nodes.
- **FR-014**: When a SWITCH node's handler returns a route that matches no downstream edge and no exit/fallback edge exists, the scheduler MUST raise a `ValueError` identifying the unmatched route and the SWITCH node. Silent no-op completion of a SWITCH with zero activated downstream is not allowed.

### Non-Functional Requirements

- **NFR-001**: After initial pending-set seeding, the activation-frontier implementation MUST NOT add any iteration over all graph nodes or all snapshot states inside the `while pending` loop. Pending growth within the loop MUST be driven only by the current node, activated downstream targets, and re-entry targets.

### Key Entities

- **Pending Set**: The set of node IDs that have been activated and are candidates for scheduling. Changed from "all non-completed nodes" to "activation frontier" — only nodes reachable via actually-taken edges.
- **Entry Node**: A node with no upstream edges in the graph. These are the initial seeds of the pending set.
- **Activated Node**: A node that has been added to pending because an upstream edge was traversed to it, or because it is an entry node.
- **Snapshot Format Version**: An explicit metadata field in persisted snapshots used to determine whether resume semantics are supported by the current scheduler implementation.

## Constitution Alignment *(mandatory)*

- **Core Boundary**: This change stays within core graph-execution modules: `loopgraph/core/graph.py` adds `entry_nodes()`, `loopgraph/core/state.py` carries snapshot format metadata, and `loopgraph/scheduler/scheduler.py` handles supported resume and pending-set growth. It fixes correctness and recovery semantics that are explicit core-engine responsibilities. No handler or adapter changes are needed.
- **Execution Semantics Impact**: Node readiness (`is_ready`) is unchanged. Switch routing (`_determine_downstream_edges`) is unchanged apart from explicit unmatched-route failure. `NodeKind.TERMINAL` semantics are unchanged. The execution-model changes are: (a) pending becomes an activation frontier rather than "all non-completed nodes", and (b) resume is allowed only from supported snapshot versions identified by `snapshot_format_version`. `max_visits` enforcement is unaffected. Aggregate nodes that are activated but not yet ready will correctly sit in pending until enough upstreams complete.
- **Failure and Retry Strategy**: No change to handler-owned retries. The scheduler adds explicit validation failures for unsupported snapshot versions, fresh runs with zero entry nodes, and unmatched SWITCH routes with no exit edge. The existing deadlock `RuntimeError` remains as a defensive fallback for genuinely stuck graphs after scheduling begins.
- **Concurrency Policy**: No change. `ConcurrencyManager.slot()` continues to gate every node execution. The pending set change does not affect concurrency semantics.
- **Recovery and Persistence**: Supported snapshots now carry an explicit `snapshot_format_version`. The resume path seeds pending from supported snapshot state (PENDING nodes + uncompleted entry nodes) rather than all non-completed nodes. Snapshots missing the supported version boundary are rejected explicitly with discard-or-migrate guidance instead of being resumed heuristically.
- **Debug & Logging Plan**: The pending-set initialization and growth points must emit `log_variable_change` traces for the new pending set contents. Existing debug logging in `_execute_node` and `_determine_downstream_edges` remains unchanged.
- **Typing & Compatibility Plan**: No public API changes. The `Scheduler.run` signature and return type are unchanged. `NodeKind.TERMINAL` remains behaviorally unchanged. Persisted snapshot compatibility is version-gated via `snapshot_format_version`; unsupported versions are rejected explicitly with discard-or-migrate guidance. Internal pending-set logic is private.
- **Abstraction & Dependency Plan**: No new interfaces or protocols. No new dependencies. No circular dependency risk.
- **Validation Plan**:
  - New test: SWITCH selects one leaf branch, other leaf does not block completion.
  - New test: SWITCH with 3+ branches, only selected one executes.
  - Existing tests: all loop/re-entry switch tests must pass unchanged.
  - New test: resume from snapshot with already-activated pending node.
  - New test: resume with missing or unsupported `snapshot_format_version` raises `ValueError` with clear operator guidance.
  - New test: merge/aggregate nodes sit in pending until enough upstreams complete.
  - New test: fresh run with zero entry nodes raises `ValueError` with an explicit no-entry-nodes message.
  - New test: genuinely stuck graph (activated node that can never become ready) still raises `RuntimeError`.
  - New test: TERMINAL node used as SWITCH leaf schedules like TASK under activation-frontier.
  - New test: SWITCH with no matching route raises `ValueError`.
  - New test: exhausted SWITCH branches fall back to exit edge under activation-frontier.
  - Validation: inspect `Scheduler.run()` / `_execute_node()` to confirm no added full-graph scan occurs inside the `while pending` loop.
  - `README.md` updated to document the scheduler/state semantic changes introduced by activation-frontier behavior.
  - `ruff check` must pass.
  - Type checking must pass.
  - `tests/test_doctests.py` must pass.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A graph where a SWITCH routes to one of N leaf branches completes successfully without raising `RuntimeError`, for any N >= 2.
- **SC-002**: All existing loop/re-entry tests pass without modification.
- **SC-003**: A resumed workflow from a supported snapshot with a mix of completed, activated-pending, and never-activated nodes correctly executes only the activated-pending and entry nodes.
- **SC-004**: Aggregate nodes in fan-out/fan-in graphs continue to wait for the required number of upstream completions before executing.
- **SC-005**: The scheduler's deadlock detection still raises `RuntimeError` for genuinely stuck graphs (e.g., circular dependencies with no entry point).
- **SC-006**: A fresh run on a graph with zero entry nodes fails immediately with a `ValueError` that explicitly identifies the missing-entry-node condition.
- **SC-007**: A SWITCH node returning a route that matches no downstream edge raises a `ValueError` instead of silently completing with no activation.
- **SC-008**: A resume attempt against a snapshot with a missing or unsupported `snapshot_format_version` fails immediately with a `ValueError` that identifies the unsupported version boundary and recommends discard or migration.
- **SC-009**: Code inspection of `Scheduler.run()` confirms the activation-frontier change introduces no new full-graph scan inside the `while pending` loop after initial pending-set seeding.
