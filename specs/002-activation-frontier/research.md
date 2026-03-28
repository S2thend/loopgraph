# Research: Activation Frontier Pending Set

**Feature**: 002-activation-frontier
**Date**: 2026-03-28

## Research Questions

### R1: How should pending be seeded on a fresh run?

**Decision**: Seed with entry nodes only — nodes that have no upstream edges in the graph. Use a new `Graph.entry_nodes()` helper that queries the existing `_reverse_adj` index.

**Rationale**: Entry nodes are the only nodes that can be ready without any upstream completion. All other nodes must be activated by an upstream node completing and traversing an edge to them. This is the minimal correct seed set.

**Alternatives considered**:
- Keep seeding with all nodes and prune unreachable ones at deadlock time: Rejected per issue #5 discussion — reactive pruning is harder to reason about and makes the scheduler less predictable.
- Compute reachability from entry nodes upfront: Over-engineered. Dynamic activation during execution naturally achieves the same result and handles SWITCH routing correctly.

### R2: How should pending be seeded on resume from snapshot?

**Decision**: Seed with the union of: (a) uncompleted entry nodes, (b) nodes with PENDING status in the snapshot, (c) nodes with RUNNING status in the snapshot (reset to PENDING).

**Rationale**:
- Uncompleted entry nodes: These may not have a state entry yet if the scheduler crashed before reaching them.
- PENDING nodes in snapshot: These were already activated by a prior edge traversal but hadn't executed yet.
- RUNNING nodes in snapshot: These were mid-execution when the scheduler stopped. Since we can't know if the handler completed, we must re-execute them. Resetting to PENDING lets `is_ready()` re-evaluate them.
- Nodes with no state entry and no upstream edges: These are entry nodes covered by (a).
- Nodes with no state entry and upstream edges: These were never activated and must NOT enter pending.

**Alternatives considered**:
- Treating RUNNING as FAILED on resume: Rejected. The handler may be idempotent and the user expects re-execution. PENDING is the safer default per spec clarification.

### R3: How should activated downstream targets be added to pending?

**Decision**: Modify `_execute_node` to return activated (non-reentry) downstream targets alongside reentry targets. The `run()` loop adds these to `pending`.

**Rationale**: `_execute_node` already iterates over `selected_edges` and categorizes each target (initial pending, reentry, failed, exhausted). The `initial_pending_target` branch (scheduler.py:365-366) identifies exactly the nodes that should be newly added to pending. Returning them is a natural extension of the existing return value.

The return type changes from `Tuple[Any, List[str]]` to `Tuple[Any, List[str], List[str]]` (result, reentry_targets, activated_targets). This is an internal method, so no public API impact.

**Alternatives considered**:
- Passing `pending` into `_execute_node` and mutating it directly: Rejected for the same reason as in 001-scheduler-loop-reentry research — it couples execution to the scheduling loop's internal data structure.
- Using a dataclass for the return: Slightly cleaner but over-engineered for a three-element internal return.

### R4: Should `Graph.entry_nodes()` be a new method or inline logic?

**Decision**: New method on `Graph`, consistent with existing `downstream_nodes()` and `upstream_nodes()`.

**Rationale**: Entry node identification is a graph-structural query that may be useful beyond the scheduler (e.g., validation, visualization). It's a one-liner over existing `_reverse_adj` data. Adding it to `Graph` follows the established pattern and keeps the scheduler focused on orchestration.

### R5: What about old snapshots created before activation-frontier semantics?

**Decision**: Out of scope per FR-010. Old snapshots may contain PENDING state for nodes that were never truly activated (because the old scheduler seeded all nodes as pending). The new resume logic would incorrectly treat these as activated. Users must discard or manually migrate old snapshots.

**Rationale**: Attempting backward compatibility with old snapshots would require heuristics to distinguish "truly activated PENDING" from "seeded-as-pending-but-never-activated" — there's no reliable way to do this from the snapshot alone. Clean break is simpler and safer.

### R6: Does the existing `test_complex_workflow_with_switch_and_merge` test need changes?

**Decision**: No. That test's graph has `start` as the sole entry node, and all other nodes are reachable via edges from `start`. The SWITCH in that test selects the `process` route, and `process` is also directly downstream of `start` (via `start->process` edge). Under activation-frontier semantics, all nodes will still be activated and the test passes unchanged.

**Rationale**: Reviewed the graph structure — `start` fans out to `switch`, `audit`, and `process`. The SWITCH selects `process` (which is already activated by `start->process`). `audit` is activated by `start->audit`. `merge` is activated by `process->merge` and `audit->merge`. `final` is activated by `merge->final`. All paths are covered.
