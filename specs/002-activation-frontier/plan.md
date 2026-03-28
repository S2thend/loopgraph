# Implementation Plan: Activation Frontier Pending Set

**Branch**: `002-activation-frontier` | **Date**: 2026-03-28 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/002-activation-frontier/spec.md`

## Summary

Fix the scheduler deadlock caused by seeding `pending` with all graph nodes. Add
`Graph.entry_nodes()`, version supported recovery snapshots with
`snapshot_format_version`, teach `Scheduler.run()` to seed `pending` from entry
nodes or supported snapshot state, and grow it dynamically as edges are actually
activated after node completion. Update `_execute_node()` to return activated
targets and change `_determine_downstream_edges()` to raise `ValueError` for
unmatched SWITCH routes. This ensures unselected SWITCH branches never enter the
pending set, unsupported legacy snapshots fail fast with explicit guidance, and
graphs with zero entry nodes raise `ValueError`.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: None (zero runtime dependencies)
**Storage**: N/A (in-memory state + optional pluggable snapshot/event stores)
**Testing**: pytest + pytest-asyncio
**Target Platform**: Any Python 3.10+ runtime
**Project Type**: Single Python package (`loopgraph`)
**Performance Goals**: Preserve steady-state scheduler complexity by adding no full-graph scan inside the `while pending` loop after initial seeding
**Constraints**: Zero runtime deps, async-first API, PEP 561 typing
**Scale/Scope**: `Graph.entry_nodes()`, `ExecutionState` snapshot metadata, `Scheduler.run()` / `_execute_node()` / `_determine_downstream_edges()`, README updates, and new tests

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **Compact Core**: Change stays within `Graph`, `ExecutionState`, and
      `Scheduler` core execution helpers — dependency resolution and recovery
      semantics are explicit engine responsibilities. No domain-specific behavior
      is introduced. `Graph` gains a trivial `entry_nodes()` query and
      `ExecutionState` gains explicit snapshot format metadata.
- [x] **Edge-Heavy Work**: No long-running or distributed work added. Pending-set
      growth is O(out-degree) per completed node, fully within the async loop.
- [x] **Flexible Aggregation Semantics**: `is_ready()` semantics unchanged.
      Aggregate nodes enter pending when first upstream activates them, wait for
      `required` count. `allow_partial_upstream` and `max_visits` unaffected.
- [x] **Handler-Owned Error Strategy**: No automatic retries introduced. The new
      `ValueError` for zero entry nodes is a graph validation error, not a retry
      policy.
- [x] **Pluggable Concurrency**: No change to `ConcurrencyManager`. Activated
      nodes acquire slots via the same path.
- [x] **Snapshot-First Recovery**: Supported recovery snapshots now carry an
      explicit `snapshot_format_version`. Resume seeds pending from
      PENDING/RUNNING nodes in supported snapshots + uncompleted entry nodes.
      RUNNING nodes are reset to PENDING. Unsupported or missing snapshot
      versions are rejected explicitly with discard-or-migrate guidance.
- [x] **Docstring Doctest Coverage**: Existing doctests in `Scheduler` and
      `ExecutionState` must stay green after the pending/recovery payload changes.
      New `entry_nodes()` gets a doctest. `tests/test_doctests.py` must pass.
- [x] **Debug Traceability**: New pending-set initialization and growth points
      emit `log_variable_change` traces. Existing debug logging unchanged.
- [x] **Typing-First Contract**: No public API changes. `Scheduler.run()`
      signature unchanged. New `entry_nodes()` is typed. All changes pass mypy.
- [x] **Observability & Telemetry**: Event payloads and append-only chronology
      unchanged. Nodes that never enter pending simply emit no events.
- [x] **Abstraction & Decoupling**: No new interfaces. Changes stay within
      existing `Scheduler`/`Graph`/`ExecutionState` boundary.
- [x] **Compatibility First**: No public API breakage. No new runtime deps.
      Persisted-state compatibility is handled through explicit snapshot
      versioning and rejection guidance for unsupported versions.
- [x] **Bounded Loop Semantics**: `max_visits` enforcement preserved. Re-entry
      targets are re-added to pending via existing `reentry_targets` path.
- [x] **Explicit Error Propagation**: New `ValueError` for zero entry nodes is
      explicit. Deadlock `RuntimeError` preserved. No silent suppression.
- [x] **Quality Gates**: Plan includes pytest, ruff check, mypy, doctest gate,
      performance-constraint validation, and README/docs sync.

## Project Structure

### Documentation (this feature)

```text
README.md                # MODIFY: document activation-frontier semantics and recovery boundary
specs/002-activation-frontier/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
loopgraph/
├── core/
│   ├── graph.py         # MODIFY: add entry_nodes() helper
│   └── state.py         # MODIFY: add snapshot format version metadata
├── scheduler/
│   └── scheduler.py     # MODIFY: supported resume, pending growth, route errors
tests/
├── test_integration_workflows.py  # MODIFY: add activation-frontier tests
├── test_scheduler_recovery.py     # MODIFY: add supported/unsupported resume tests
└── test_doctests.py               # VERIFY: passes with new doctests
```

**Structure Decision**: Single Python package. All changes are within existing
modules — no new files needed. `entry_nodes()` is added to `Graph` as a query
helper (consistent with existing `downstream_nodes()`, `upstream_nodes()`), and
snapshot format metadata is added to `ExecutionState` to make supported recovery
boundaries explicit.

## Complexity Tracking

No constitution violations to justify.

## Design

### Change 1: `Graph.entry_nodes()` helper

Add a method to `Graph` that returns nodes with no upstream edges. This is a
simple query over `_reverse_adj` — a node is an entry node if its reverse
adjacency list is empty.

```python
def entry_nodes(self) -> List[Node]:
    """Return nodes with no upstream edges (graph entry points)."""
    return [
        self.nodes[node_id]
        for node_id in self.nodes
        if not self._reverse_adj.get(node_id, [])
    ]
```

Include a doctest. Emit debug logging.

### Change 2: Snapshot format versioning for supported recovery

Supported activation-frontier snapshots carry an explicit
`snapshot_format_version`. This makes the recovery boundary machine-checkable and
allows the scheduler to reject legacy snapshots from older semantics instead of
guessing whether historical `PENDING` state was truly activated.

```python
SNAPSHOT_FORMAT_VERSION = 2

payload = {
    "snapshot_format_version": SNAPSHOT_FORMAT_VERSION,
    "states": states_payload,
    "completed_nodes": sorted(self._completed_nodes),
}
```

Unsupported snapshots are rejected by `Scheduler` before restore. Supported
snapshots remain JSON-serializable and continue to restore completed nodes
without re-executing them.

### Change 3: `Scheduler.run()` pending-set initialization and supported resume

Replace line 190:
```python
# OLD
pending = {node_id for node_id in graph.nodes if node_id not in completed_nodes}
```

With activation-frontier seeding:

**Fresh run** (no snapshot / empty snapshot):
```python
entry_ids = {n.id for n in graph.entry_nodes()}
if not entry_ids and graph.nodes:
    raise ValueError("Graph has no entry nodes (nodes with no upstream edges)")
pending = set(entry_ids)
```

**Resume** (snapshot has state):
```python
version = snapshot_data.get("snapshot_format_version")
if version != SUPPORTED_SNAPSHOT_FORMAT_VERSION:
    raise ValueError(
        "Unsupported snapshot format version "
        f"{version!r}; supported version is "
        f"{SUPPORTED_SNAPSHOT_FORMAT_VERSION}. "
        "Discard or migrate the snapshot before resuming."
    )

entry_ids = {n.id for n in graph.entry_nodes()}
pending = set()
# Add uncompleted entry nodes
for eid in entry_ids:
    if eid not in completed_nodes:
        pending.add(eid)
# Add nodes that were activated (PENDING or RUNNING in snapshot)
for node_id, node_state in snapshot_data.get("states", {}).items():
    status = node_state.get("status")
    if status in (NodeStatus.PENDING.value, NodeStatus.RUNNING.value):
        if node_id not in completed_nodes:
            pending.add(node_id)
```

For RUNNING nodes on resume: reset them to PENDING in the execution state so
`is_ready()` can evaluate them.

The full snapshot scan stays outside the `while pending` loop. After the loop
starts, pending growth must be driven only by activated targets and re-entry
targets so the run-loop complexity does not add a new graph-wide scan.

### Change 4: `Scheduler.run()` pending-set growth on node completion

After `_execute_node` returns, the current code does:
```python
pending.remove(node_id)
for reentry_target in reentry_targets:
    pending.add(reentry_target)
```

Add activation of newly-reachable downstream nodes. The selected edges from
`_execute_node` already determine which downstream targets were activated
(via `note_upstream_completion`). We need to also add those targets to `pending`
if they aren't already there and aren't completed.

This requires `_execute_node` to return the list of activated (non-reentry)
downstream targets in addition to reentry targets. Modify the return type from
`Tuple[Any, List[str]]` to `Tuple[Any, List[str], List[str]]` — result,
reentry_targets, activated_targets.

In `_execute_node`, collect the targets from `selected_edges` that are in
`initial_pending_target` branch (line 365-366) into `activated_targets`.

In `run()`, after removing the completed node:
```python
for target in activated_targets:
    if target not in completed_nodes:
        pending.add(target)
for reentry_target in reentry_targets:
    pending.add(reentry_target)
```

### Change 5: Zero entry nodes guard

Before the `while pending` loop, if the graph has nodes but `pending` is empty
(and no snapshot state), raise `ValueError`.

### Change 6: RUNNING node reset on resume

When seeding pending from snapshot, if a node has RUNNING status, call
`execution_state.mark_running()` is already done — but we need to reset it back
to PENDING. Use the existing `_ensure_state` to get the state and set status
to PENDING directly, or add a small reset path in the resume logic.

Simplest approach: after restoring execution state, iterate over states and
reset any RUNNING nodes to PENDING:
```python
for node_id, node_state in snapshot_data.get("states", {}).items():
    if node_state.get("status") == NodeStatus.RUNNING.value:
        state = execution_state._ensure_state(node_id)
        state.status = NodeStatus.PENDING
```

### Change 7: SWITCH no-match route raises ValueError

In `_determine_downstream_edges`, the current code returns `[]` when no route
matches and no exit edge exists (scheduler.py:476-477). Change this to raise
`ValueError` identifying the unmatched route and the SWITCH node:

```python
# Replace the silent return []
raise ValueError(
    f"Switch node '{node.id}' returned route '{route}' "
    f"which matches no downstream edge"
)
```

This ensures SWITCH nodes always activate at least one downstream target or
explicitly fail. Silent no-op completion is no longer allowed.

### Change 8: Documentation sync and operator guidance

Update `README.md` to describe the activation-frontier pending model, the new
zero-entry-node validation error, unmatched SWITCH route failure, and the
explicit rejection of unsupported snapshot versions. The README is the minimum
required runtime-facing documentation update for this scheduler/state semantic
change.
