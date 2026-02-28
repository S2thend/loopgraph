# Tasks: Scheduler Loop Re-entry

**Input**: Design documents from `/specs/001-scheduler-loop-reentry/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, quickstart.md

**Tests**: Test tasks are REQUIRED for every feature and bug fix. Include
coverage that proves behavior changes and keeps doctest examples valid when
documentation examples are touched.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Package source**: `eventflow/` at repository root
- **Tests**: `tests/` at repository root

---

## Phase 1: Setup

**Purpose**: No new files or project init needed — all changes modify existing files.

- [ ] T001 Verify existing tests pass before starting: `python -m pytest tests/ -x`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T002 [P] Add `reset_for_reentry(node_id)` method to `ExecutionState` in `eventflow/core/state.py`. Must: set status to `NodeStatus.PENDING`, clear `upstream_completed`, remove from `_completed_nodes`. Must NOT reset `visits.count`. Include `eventflow._debug` logging (`log_parameter`, `log_variable_change`, `log_branch`). Include docstring with doctest example.
- [ ] T003 [P] Add shared-node multi-loop validation and SWITCH self-loop rejection to `Graph.validate()` in `eventflow/core/graph.py`. Use DFS-based cycle detection on forward adjacency. Find all cycles, check for node intersection across cycles. Raise `ValueError` listing shared nodes if any node appears in more than one cycle. Also reject edges where `source == target` and the source node is `NodeKind.SWITCH` (SWITCH self-loops are meaningless). Include `eventflow._debug` logging. Include docstring with doctest example.
- [ ] T004 Unit test for `reset_for_reentry` in `tests/test_integration_workflows.py`: verify status reset to PENDING, `upstream_completed` cleared, removed from `_completed_nodes`, `visits.count` preserved. Verify snapshot/restore round-trip after reset.
- [ ] T005 Unit test for graph topology validation in `tests/test_integration_workflows.py`: verify `Graph.validate()` raises `ValueError` for graphs with overlapping cycles. Verify graphs with multiple disjoint loops pass validation. Verify graphs with a single loop of any length pass validation. Verify SWITCH self-loop raises `ValueError`. Verify non-SWITCH self-loop passes validation.

**Checkpoint**: Foundation ready — `reset_for_reentry` and graph topology validation are independently testable and proven correct.

---

## Phase 3: User Story 1 — Bounded Loop Execution (Priority: P1) 🎯 MVP

**Goal**: SWITCH back-edges drive loop re-entry with `max_visits` bounding. The scheduler re-enters completed nodes automatically — no manual state resets.

**Independent Test**: Build a graph with `loop_body (max_visits=3) → switch → loop_body` back-edge, run `Scheduler.run()`, assert loop_body executes exactly 3 times and exit route fires once.

### Tests for User Story 1 (REQUIRED) ✅

- [ ] T006 [P] [US1] Integration test `test_scheduler_bounded_loop_reentry` in `tests/test_integration_workflows.py`: graph with `start → loop_body (max_visits=3, allow_partial_upstream=True) → switch → loop_body (route="continue") / output (route="done")`. Switch handler returns "continue" while visits < max. Assert: loop_body runs 3 times, output runs once, results correct.
- [ ] T007 [P] [US1] Integration test `test_scheduler_loop_max_visits_1` in `tests/test_integration_workflows.py`: loop_body with `max_visits=1`. Assert: loop_body runs once, exit route taken immediately on back-edge.
- [ ] T008 [P] [US1] Integration test `test_scheduler_disjoint_loops_execute` in `tests/test_integration_workflows.py`: construct a graph with two disjoint loops, ensure graph validation passes, and assert both loop segments execute without loop-topology errors.
- [ ] T008a [P] [US1] Integration test `test_scheduler_reentry_pending_running_hard_stop` in `tests/test_integration_workflows.py`: verify scheduler raises `RuntimeError` if `_execute_node` encounters a back-edge target in PENDING or RUNNING state (defensive assertion for bugs bypassing graph validation).

### Implementation for User Story 1

- [ ] T009 [US1] Modify `_execute_node` in `eventflow/scheduler/scheduler.py` to detect re-entry targets after downstream edge processing (line 267-272). For each selected edge target: if target status is COMPLETED and has remaining visits, call `reset_for_reentry`. If target is PENDING or RUNNING, raise `RuntimeError` (defensive hard-stop). Otherwise (FAILED), do not reset. Return `Tuple[Any, List[str]]` (handler result + re-entry node IDs). Include `eventflow._debug` logging for re-entry detection.
- [ ] T010 [US1] Modify `run()` in `eventflow/scheduler/scheduler.py` to unpack `_execute_node` return value as `handler_result, reentry_targets`. After `pending.remove(node_id)`, add `pending.add(target)` for each re-entry target. Include `eventflow._debug` logging for re-queue.
- [ ] T011 [US1] Update existing `test_loop_respects_max_visits` in `tests/test_integration_workflows.py`: replace manual state reset (lines 183-185) with `state.reset_for_reentry("loop")` to validate the new method integrates with existing test patterns.

**Checkpoint**: Bounded loop re-entry works end-to-end via `Scheduler.run()`. This is the MVP — loops with `max_visits` work natively without manual state manipulation.

---

## Phase 4: User Story 2 — Unbounded Loop with Handler-Controlled Exit (Priority: P2)

**Goal**: Loops with `max_visits=None` run indefinitely until the SWITCH handler returns a different route (e.g., "done" instead of "continue").

**Independent Test**: Build a graph where loop_body has no `max_visits`, switch handler returns "continue" 5 times then "done". Assert loop_body runs exactly 5 times.

### Tests for User Story 2 (REQUIRED) ✅

- [ ] T012 [P] [US2] Integration test `test_scheduler_unbounded_loop_handler_exit` in `tests/test_integration_workflows.py`: graph with `loop_body (max_visits=None, allow_partial_upstream=True) → switch → loop_body (route="continue") / output (route="done")`. Switch handler returns "continue" 5 times then "done". Assert: loop_body runs 5 times, output runs once.

### Implementation for User Story 2

No additional code changes needed — the Phase 3 implementation handles `max_visits=None` because `_has_remaining_visits` returns `True` when `max_visits is None` (scheduler.py:387-389). This phase validates the behavior with a dedicated test.

**Checkpoint**: Unbounded loops work. Handler controls exit timing. `max_visits=None` nodes re-enter indefinitely until route changes.

---

## Phase 5: User Story 3 — Visit Count Observability (Priority: P3)

**Goal**: `NODE_COMPLETED` events carry correct cumulative `visit_count` across re-entries. Operators can monitor loop progress via the event log.

**Independent Test**: Subscribe to event bus, run a bounded loop graph, assert `visit_count` on successive `NODE_COMPLETED` events for the loop body increments 1, 2, 3.

### Tests for User Story 3 (REQUIRED) ✅

- [ ] T013 [P] [US3] Integration test `test_loop_visit_count_observability` in `tests/test_integration_workflows.py`: run bounded loop graph with `InMemoryEventLog`. Collect `NODE_COMPLETED` events for loop_body node. Assert `visit_count` values are `[1, 2, 3]`.
- [ ] T014 [P] [US3] Integration test `test_loop_snapshot_resume_visit_count` in `tests/test_integration_workflows.py`: run a bounded loop graph (max_visits=3) with `InMemorySnapshotStore`, stop after 2 iterations. Create a new `Scheduler` instance with the same snapshot store, call `Scheduler.run()` again, and assert: execution resumes from iteration 3 (not from scratch), `visit_count` on the resumed `NODE_COMPLETED` event is 3, and the exit route fires correctly.

### Implementation for User Story 3

No additional code changes needed — `mark_complete` already increments `visits.count` (state.py:306) and the scheduler already emits `visit_count` on `NODE_COMPLETED` events (scheduler.py:255-257). These tests validate the existing observability path works correctly across re-entries.

**Checkpoint**: Visit count observability confirmed. Event log accurately reflects cumulative executions across re-entries.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Quality gates and cross-cutting validation

- [ ] T015 Run doctest gate: `python -m pytest --doctest-modules eventflow/core/state.py` — verify `reset_for_reentry` doctest passes
- [ ] T016 Run doctest gate: `python -m pytest --doctest-modules eventflow/core/graph.py` — verify validate() cycle detection doctest passes
- [ ] T017 Run doctest gate: `python -m pytest tests/test_doctests.py` — verify all doctests pass
- [ ] T018 Run type check: `mypy` with repository configuration — verify all changed modules pass
- [ ] T019 Run lint: `ruff check` — verify all changed modules pass
- [ ] T020 Run full test suite: `python -m pytest tests/ -x -v` — verify all tests pass including existing ones (backward compatibility)
- [ ] T021 Verify `eventflow._debug` traces: review `reset_for_reentry`, re-entry detection in `_execute_node`, and cycle detection in `validate()` all use `log_parameter`, `log_variable_change`, `log_branch` consistently
- [ ] T022 Verify `max_visits` enforcement: confirm visit counts accumulate across re-entries and exhausted nodes take exit route (Principle XIV)
- [ ] T023 Verify fail-fast behavior: confirm handler exceptions still emit `NODE_FAILED` and abort `Scheduler.run()` (Principle XV)
- [ ] T024 Verify zero-runtime-dependency NFR: confirm `[project.dependencies]` remains unchanged (no new runtime deps)
- [ ] T025 Verify steady-state scheduler-overhead NFR: confirm no new graph-wide traversal is added to `Scheduler.run()`/`_execute_node` (topology analysis remains in `Graph.validate()`)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — verify baseline
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Phase 2 (T002, T003 must be complete)
- **User Story 2 (Phase 4)**: Depends on Phase 3 (same code path, tests only)
- **User Story 3 (Phase 5)**: Depends on Phase 3 (same code path, tests only)
- **Polish (Phase 6)**: Depends on all user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Depends on Foundational phase. This is the core implementation — all code changes happen here.
- **User Story 2 (P2)**: Depends on US1 completion (uses same re-entry code path). Phase 4 is test-only.
- **User Story 3 (P3)**: Depends on US1 completion (uses same observability code path). Phase 5 is test-only.

### Within Each User Story

- Tests written first → verify they fail
- Implementation → verify tests pass
- Checkpoint validation before moving to next story

### Parallel Opportunities

- T002 and T003 can run in parallel (different files: state.py vs graph.py)
- T004 and T005 can run in parallel (independent test targets)
- T006, T007, T008, T008a can run in parallel (independent test cases, all in same file but no dependencies)
- T012 can run in parallel with T013, T014 (different test focus areas)
- T015, T016, T017, T018, T019, T024, T025 can all run in parallel (independent quality gates)

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Verify baseline passes
2. Complete Phase 2: `reset_for_reentry` + graph validation (T002-T005)
3. Complete Phase 3: Scheduler re-entry logic + bounded loop tests (T006-T011)
4. **STOP and VALIDATE**: Run `python -m pytest tests/ -x -v`
5. MVP is complete — bounded loops work natively

### Incremental Delivery

1. Phase 1 + Phase 2 → Foundation ready
2. Phase 3 (US1) → Bounded loops work → MVP!
3. Phase 4 (US2) → Unbounded loops validated (test-only)
4. Phase 5 (US3) → Observability confirmed (test-only)
5. Phase 6 → All quality gates pass

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- US2 and US3 require no additional code — the US1 implementation handles both. Phases 4 and 5 are test-only.
- The 3 source files modified: `eventflow/core/state.py`, `eventflow/core/graph.py`, `eventflow/scheduler/scheduler.py`
- The 1 test file modified: `tests/test_integration_workflows.py`
- Commit after each phase checkpoint
