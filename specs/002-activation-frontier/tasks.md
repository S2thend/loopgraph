# Tasks: Activation Frontier Pending Set

**Input**: Design documents from `/specs/002-activation-frontier/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md

**Tests**: Test tasks are REQUIRED for every feature and bug fix. Include
coverage that proves behavior changes and keeps doctest examples valid when
documentation examples are touched.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `loopgraph/`, `tests/` at repository root

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add the `entry_nodes()` helper to `Graph` — prerequisite for all scheduler changes

- [X] T001 Add `entry_nodes()` method with doctest and debug logging to loopgraph/core/graph.py

**Checkpoint**: `Graph.entry_nodes()` is available and `tests/test_doctests.py` passes

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core scheduler changes that MUST be complete before any user story can be validated

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T002 Change `Scheduler.run()` pending-set initialization to seed from entry nodes only (fresh run) in loopgraph/scheduler/scheduler.py — replace line 190 `pending = {node_id for node_id in graph.nodes if node_id not in completed_nodes}` with `pending = {n.id for n in graph.entry_nodes()}` guarded by the zero-entry-nodes `ValueError` (FR-012)
- [X] T003 Change `Scheduler._execute_node()` return type from `Tuple[Any, List[str]]` to `Tuple[Any, List[str], List[str]]` (result, reentry_targets, activated_targets) in loopgraph/scheduler/scheduler.py — collect targets from the `initial_pending_target` branch into `activated_targets` and return them
- [X] T004 Update `Scheduler.run()` loop to add activated targets to `pending` after each node completion in loopgraph/scheduler/scheduler.py — iterate `activated_targets` from T003 and `pending.add(target)` for targets not already completed
- [X] T005 Add `snapshot_format_version` metadata for supported activation-frontier snapshots in loopgraph/core/state.py and keep `ExecutionState.snapshot()` / `restore()` aligned for supported versions (FR-010)
- [X] T005b Add supported-snapshot resume seeding and explicit legacy snapshot rejection in loopgraph/scheduler/scheduler.py — reject missing or unsupported `snapshot_format_version` with `ValueError`, then seed pending from (a) uncompleted entry nodes, (b) PENDING nodes in snapshot, (c) RUNNING nodes reset to PENDING (FR-006, FR-011)
- [X] T006 Add `log_variable_change` / `log_branch` debug traces for fresh-run seeding, supported snapshot seeding, legacy snapshot rejection, and pending growth points in loopgraph/scheduler/scheduler.py
- [X] T006b Change `_determine_downstream_edges` to raise `ValueError` when a SWITCH node's route matches no downstream edge and no exit/fallback edge exists (FR-014) in loopgraph/scheduler/scheduler.py — replace the `return []` at line 477 with a `ValueError`

**Checkpoint**: Scheduler uses activation-frontier semantics for fresh runs and supported snapshots. Unsupported snapshots fail fast. Existing doctests in `Scheduler` class still pass.

---

## Phase 3: User Story 1 — SWITCH to terminal leaf completes without deadlock (Priority: P1) 🎯 MVP

**Goal**: A SWITCH node routing to one of N leaf branches completes without deadlock; unselected branches never block.

**Independent Test**: Build a graph with `[input] → [decide(SWITCH)] → [done]` and `[decide] → [fix]`. Route to `done`. Verify no `RuntimeError`.

### Tests for User Story 1 (REQUIRED) ✅

- [X] T007 [P] [US1] Test SWITCH with two leaf branches — selected branch completes, unselected does not block — in tests/test_integration_workflows.py
- [X] T008 [P] [US1] Test SWITCH with three downstream branches — only selected one executes — in tests/test_integration_workflows.py
- [X] T009 [P] [US1] Test SWITCH selecting each branch in separate runs — both complete successfully — in tests/test_integration_workflows.py

### Validation for User Story 1

- [X] T010 [US1] Run an interim full regression checkpoint immediately after US1 to confirm the activation-frontier baseline introduces no broad regressions — `pytest tests/`

**Checkpoint**: SWITCH-to-leaf-branch deadlock is fixed. Issue #5 scenario passes.

---

## Phase 4: User Story 2 — Loop re-entry with SWITCH still works (Priority: P1)

**Goal**: Existing loop/re-entry behavior is preserved — SWITCH can route back to an earlier node on some iterations and exit on the final iteration, while activation-frontier pending updates still re-add eligible re-entry targets.

**Independent Test**: Run existing loop tests (`test_scheduler_bounded_loop_reentry`, `test_scheduler_loop_max_visits_1`, `test_scheduler_unbounded_loop_handler_exit`, `test_scheduler_disjoint_loops_execute`).

### Tests for User Story 2 (REQUIRED) ✅

- [X] T011 [US2] Verify all existing loop/re-entry tests pass unchanged — `pytest tests/test_integration_workflows.py -k "loop"`

### Validation for User Story 2

- [X] T012 [US2] Audit and update activation-frontier re-entry handling in loopgraph/scheduler/scheduler.py so eligible re-entry targets are always re-added to `pending` and the loop regression suite in T011 passes without changing existing loop test expectations

**Checkpoint**: All loop/re-entry tests pass. No regression.

---

## Phase 5: User Story 3 — Resume from snapshot with activated pending nodes (Priority: P2)

**Goal**: On resume from a supported snapshot, only activated nodes (PENDING/RUNNING in snapshot + uncompleted entry nodes) enter pending. Never-activated nodes are excluded, and unsupported snapshot versions are rejected explicitly.

**Independent Test**: Create a supported snapshot with COMPLETED, PENDING, RUNNING, and absent nodes. Resume and verify correct pending set. Also verify unsupported versions fail fast.

### Tests for User Story 3 (REQUIRED) ✅

- [X] T013 [P] [US3] Test resume with PENDING node in snapshot — node enters pending and executes — in tests/test_scheduler_recovery.py
- [X] T014 [P] [US3] Test resume with RUNNING node in snapshot — node is reset to PENDING and executes — in tests/test_scheduler_recovery.py
- [X] T015 [P] [US3] Test resume with never-activated node (no state entry, has upstream edges) — node does NOT enter pending — in tests/test_scheduler_recovery.py
- [X] T015b [P] [US3] Test resume with missing or unsupported `snapshot_format_version` — scheduler raises `ValueError`, does not execute nodes, and the error text includes the actual version, the supported version, and discard-or-migrate guidance — in tests/test_scheduler_recovery.py
- [X] T015c [P] [US3] Test persisted supported snapshots include `snapshot_format_version` with the expected supported value — in tests/test_scheduler_recovery.py

### Validation for User Story 3

- [X] T016 [US3] Run existing recovery test `test_scheduler_resumes_from_snapshot` to confirm no regression — `pytest tests/test_scheduler_recovery.py`

**Checkpoint**: Resume correctly distinguishes activated vs never-activated nodes.

---

## Phase 6: User Story 4 — Merge/aggregate nodes wait in pending until enough upstreams complete (Priority: P2)

**Goal**: AGGREGATE nodes enter pending when first upstream activates them but wait for `required` count before executing.

**Independent Test**: Fan-out/fan-in graph with two TASKs feeding an AGGREGATE with `required=2`.

### Tests for User Story 4 (REQUIRED) ✅

- [X] T017 [US4] Test fan-out/fan-in graph with AGGREGATE — aggregate waits for both upstreams before executing — in tests/test_integration_workflows.py
- [X] T018 [US4] Verify existing `test_complex_workflow_with_switch_and_merge` passes unchanged — `pytest tests/test_integration_workflows.py -k "complex_workflow"`

**Checkpoint**: Aggregate behavior correct under activation-frontier semantics.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Quality gates and constitution compliance

- [X] T019 [P] Test zero-entry-nodes graph raises `ValueError` with explicit message in tests/test_integration_workflows.py
- [X] T019b [P] Test genuinely stuck graph (activated node that can never become ready) raises `RuntimeError` in tests/test_integration_workflows.py
- [X] T019c [P] Test TERMINAL node used as SWITCH leaf schedules like TASK under activation-frontier in tests/test_integration_workflows.py
- [X] T019d [P] Test SWITCH with no matching route raises `ValueError` in tests/test_integration_workflows.py
- [X] T019e [P] Test exhausted SWITCH branches fall back to exit edge under activation-frontier in tests/test_integration_workflows.py
- [X] T020 [P] Run `tests/test_doctests.py` to verify all doctests pass — `pytest tests/test_doctests.py`
- [X] T021 [P] Run `ruff check loopgraph/` for changed modules
- [X] T022 [P] Run mypy type checks for `loopgraph/` changes
- [X] T023 [P] Inspect loopgraph/scheduler/scheduler.py to confirm the activation-frontier change adds no iteration over all graph nodes or all snapshot states inside the `while pending` loop; pending growth must be driven only by activated targets and re-entry targets (NFR-001)
- [X] T024 [P] Validate structured debug traces for fresh-run seeding, supported snapshot seeding, legacy snapshot rejection, and pending growth in loopgraph/scheduler/scheduler.py (`log_variable_change`, `log_branch`)
- [X] T025 [P] Add or update a regression test in tests/test_integration_workflows.py confirming activation-frontier loop re-entry still respects `max_visits` enforcement and visit-count tracking (Principle XIV)
- [X] T026 [P] Update README.md to document activation-frontier pending semantics, zero-entry-node failure, unmatched SWITCH route failure, and unsupported snapshot version rejection guidance
- [X] T027 Run full test suite — `pytest tests/` — final pre-merge regression check

**Checkpoint**: All quality gates pass. Feature is complete.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 (T001) — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 completion
- **US2 (Phase 4)**: Depends on Phase 2 completion — can run in parallel with US1
- **US3 (Phase 5)**: Depends on Phase 2 completion (specifically T005 and T005b) — can run in parallel with US1/US2
- **US4 (Phase 6)**: Depends on Phase 2 completion — can run in parallel with US1/US2/US3
- **Polish (Phase 7)**: Depends on all user stories being complete

### User Story Dependencies

- **US1 (P1)**: No dependencies on other stories
- **US2 (P1)**: No dependencies on other stories (validates existing behavior)
- **US3 (P2)**: No dependencies on other stories (tests resume path independently)
- **US4 (P2)**: No dependencies on other stories (tests aggregate path independently)

### Within Each User Story

- Tests written first
- Implementation validated against tests
- Checkpoint verified before moving on

### Parallel Opportunities

- T007, T008, T009 can run in parallel (different test functions, same file)
- T013, T014, T015, T015b, T015c can run in parallel (different test functions, same file)
- T019, T019b, T019c, T019d, T019e, T020, T021, T022, T023, T024, T026 can run in parallel (independent quality checks)
- US1, US2, US3, US4 can all proceed in parallel after Phase 2

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001)
2. Complete Phase 2: Foundational (T002, T003, T004, T005, T005b, T006, T006b)
3. Complete Phase 3: User Story 1 (T007–T010)
4. **STOP and VALIDATE**: SWITCH-to-leaf deadlock is fixed, issue #5 resolved
5. Deploy/demo if ready

### Incremental Delivery

1. Setup + Foundational → Activation frontier in place
2. US1 → SWITCH deadlock fixed → MVP
3. US2 → Loop re-entry confirmed → Regression-safe
4. US3 → Resume correctness → Production-ready
5. US4 → Aggregate correctness → Full coverage
6. Polish → Quality gates → Ship

---

## Notes

- [P] tasks = different files or independent test functions, no dependencies
- [Story] label maps task to specific user story for traceability
- All changes are in existing files — no new files created
- The key implementation is in Phase 2 (T002, T003, T004, T005, T005b, T006, T006b) — everything else is testing, validation, and documentation sync
- Commit after each phase checkpoint
