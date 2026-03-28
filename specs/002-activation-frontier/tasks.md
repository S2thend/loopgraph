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

- [ ] T001 Add `entry_nodes()` method with doctest and debug logging to loopgraph/core/graph.py

**Checkpoint**: `Graph.entry_nodes()` is available and `tests/test_doctests.py` passes

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core scheduler changes that MUST be complete before any user story can be validated

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T002 Change `Scheduler.run()` pending-set initialization to seed from entry nodes only (fresh run) in loopgraph/scheduler/scheduler.py — replace line 190 `pending = {node_id for node_id in graph.nodes if node_id not in completed_nodes}` with `pending = {n.id for n in graph.entry_nodes()}` guarded by the zero-entry-nodes `ValueError` (FR-011)
- [ ] T003 Change `Scheduler._execute_node()` return type from `Tuple[Any, List[str]]` to `Tuple[Any, List[str], List[str]]` (result, reentry_targets, activated_targets) in loopgraph/scheduler/scheduler.py — collect targets from the `initial_pending_target` branch into `activated_targets` and return them
- [ ] T004 Update `Scheduler.run()` loop to add activated targets to `pending` after each node completion in loopgraph/scheduler/scheduler.py — iterate `activated_targets` from T003 and `pending.add(target)` for targets not already completed
- [ ] T005 Add resume-path pending seeding in `Scheduler.run()` in loopgraph/scheduler/scheduler.py — when snapshot has state, seed pending from (a) uncompleted entry nodes, (b) PENDING nodes in snapshot, (c) RUNNING nodes in snapshot (reset RUNNING to PENDING in execution state)
- [ ] T006 Add `log_variable_change` debug traces for new pending-set initialization and growth points in loopgraph/scheduler/scheduler.py

**Checkpoint**: Scheduler uses activation-frontier semantics. Existing doctests in `Scheduler` class still pass.

---

## Phase 3: User Story 1 — SWITCH to terminal leaf completes without deadlock (Priority: P1) 🎯 MVP

**Goal**: A SWITCH node routing to one of N leaf branches completes without deadlock; unselected branches never block.

**Independent Test**: Build a graph with `[input] → [decide(SWITCH)] → [done]` and `[decide] → [fix]`. Route to `done`. Verify no `RuntimeError`.

### Tests for User Story 1 (REQUIRED) ✅

- [ ] T007 [P] [US1] Test SWITCH with two leaf branches — selected branch completes, unselected does not block — in tests/test_integration_workflows.py
- [ ] T008 [P] [US1] Test SWITCH with three downstream branches — only selected one executes — in tests/test_integration_workflows.py
- [ ] T009 [P] [US1] Test SWITCH selecting each branch in separate runs — both complete successfully — in tests/test_integration_workflows.py

### Validation for User Story 1

- [ ] T010 [US1] Run all existing tests to confirm no regressions — `pytest tests/`

**Checkpoint**: SWITCH-to-leaf-branch deadlock is fixed. Issue #5 scenario passes.

---

## Phase 4: User Story 2 — Loop re-entry with SWITCH still works (Priority: P1)

**Goal**: Existing loop/re-entry behavior is preserved — SWITCH can route back to an earlier node on some iterations and exit on the final iteration.

**Independent Test**: Run existing loop tests (`test_scheduler_bounded_loop_reentry`, `test_scheduler_loop_max_visits_1`, `test_scheduler_unbounded_loop_handler_exit`, `test_scheduler_disjoint_loops_execute`).

### Tests for User Story 2 (REQUIRED) ✅

- [ ] T011 [US2] Verify all existing loop/re-entry tests pass unchanged — `pytest tests/test_integration_workflows.py -k "loop"`

### Validation for User Story 2

- [ ] T012 [US2] If any loop test fails, fix the activation-frontier logic in loopgraph/scheduler/scheduler.py to ensure re-entry targets are correctly re-added to pending

**Checkpoint**: All loop/re-entry tests pass. No regression.

---

## Phase 5: User Story 3 — Resume from snapshot with activated pending nodes (Priority: P2)

**Goal**: On resume, only activated nodes (PENDING/RUNNING in snapshot + uncompleted entry nodes) enter pending. Never-activated nodes are excluded.

**Independent Test**: Create a snapshot with COMPLETED, PENDING, RUNNING, and absent nodes. Resume and verify correct pending set.

### Tests for User Story 3 (REQUIRED) ✅

- [ ] T013 [P] [US3] Test resume with PENDING node in snapshot — node enters pending and executes — in tests/test_scheduler_recovery.py
- [ ] T014 [P] [US3] Test resume with RUNNING node in snapshot — node is reset to PENDING and executes — in tests/test_scheduler_recovery.py
- [ ] T015 [P] [US3] Test resume with never-activated node (no state entry, has upstream edges) — node does NOT enter pending — in tests/test_scheduler_recovery.py

### Validation for User Story 3

- [ ] T016 [US3] Run existing recovery test `test_scheduler_resumes_from_snapshot` to confirm no regression — `pytest tests/test_scheduler_recovery.py`

**Checkpoint**: Resume correctly distinguishes activated vs never-activated nodes.

---

## Phase 6: User Story 4 — Merge/aggregate nodes wait in pending until enough upstreams complete (Priority: P2)

**Goal**: AGGREGATE nodes enter pending when first upstream activates them but wait for `required` count before executing.

**Independent Test**: Fan-out/fan-in graph with two TASKs feeding an AGGREGATE with `required=2`.

### Tests for User Story 4 (REQUIRED) ✅

- [ ] T017 [US4] Test fan-out/fan-in graph with AGGREGATE — aggregate waits for both upstreams before executing — in tests/test_integration_workflows.py
- [ ] T018 [US4] Verify existing `test_complex_workflow_with_switch_and_merge` passes unchanged — `pytest tests/test_integration_workflows.py -k "complex_workflow"`

**Checkpoint**: Aggregate behavior correct under activation-frontier semantics.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Quality gates and constitution compliance

- [ ] T019 [P] Test zero-entry-nodes graph raises `ValueError` with explicit message in tests/test_integration_workflows.py
- [ ] T020 [P] Run `tests/test_doctests.py` to verify all doctests pass — `pytest tests/test_doctests.py`
- [ ] T021 [P] Run `ruff check loopgraph/` for changed modules
- [ ] T022 [P] Run mypy type checks for `loopgraph/` changes
- [ ] T023 Validate structured debug traces for new pending-set control flow (log_variable_change, log_branch calls) in loopgraph/scheduler/scheduler.py
- [ ] T024 Verify loop re-entry paths still respect `max_visits` enforcement and visit-count tracking (Principle XIV)
- [ ] T025 Run full test suite — `pytest tests/` — final regression check

**Checkpoint**: All quality gates pass. Feature is complete.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 (T001) — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 completion
- **US2 (Phase 4)**: Depends on Phase 2 completion — can run in parallel with US1
- **US3 (Phase 5)**: Depends on Phase 2 completion (specifically T005) — can run in parallel with US1/US2
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
- T013, T014, T015 can run in parallel (different test functions, same file)
- T019, T020, T021, T022 can run in parallel (independent quality checks)
- US1, US2, US3, US4 can all proceed in parallel after Phase 2

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001)
2. Complete Phase 2: Foundational (T002–T006)
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
- The key implementation is in Phase 2 (T002–T005) — everything else is testing and validation
- Commit after each phase checkpoint
