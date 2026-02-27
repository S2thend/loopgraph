# Implementation Plan: Scheduler Loop Re-entry

**Branch**: `001-scheduler-loop-reentry` | **Date**: 2026-02-20 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-scheduler-loop-reentry/spec.md`

## Summary

Enable the scheduler to re-enter completed nodes via SWITCH back-edges by
resetting them to PENDING, bounded by `max_visits`. Adds graph-level topology
validation (reject shared-node multi-loop graphs), a `reset_for_reentry` method
on `ExecutionState`, and re-entry logic in `Scheduler._execute_node` / `run()`.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: None (zero runtime dependencies)
**Storage**: N/A (in-memory state + optional pluggable snapshot/event stores)
**Testing**: pytest + pytest-asyncio
**Target Platform**: Any Python 3.10+ runtime
**Project Type**: Single Python package (`eventflow`)
**Performance Goals**: N/A (orchestration engine, not compute-bound)
**Constraints**: Zero runtime deps, async-first API, PEP 561 typing

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **Compact Core**: Changes are limited to `ExecutionState` (new
      `reset_for_reentry` method) and `Scheduler` (re-entry detection after
      downstream edge selection). Both are scheduling primitives — dependency
      resolution and state management. Graph validation for shared-node
      multi-loop rejection belongs in `Graph.validate()`, which already performs
      structural checks. No domain-specific behavior is introduced.
- [x] **Edge-Heavy Work**: No long-running or distributed work is added. Re-entry
      is a state reset + queue re-add, fully within the single-process async loop.
- [x] **Flexible Aggregation Semantics**: `is_ready()` semantics are unchanged.
      Re-entry clears `upstream_completed` so readiness is re-evaluated from
      scratch. `allow_partial_upstream` and `max_visits` continue to work as
      before. No global failure strategy is imposed.
- [x] **Handler-Owned Error Strategy**: No automatic retries introduced. FAILED
      nodes are eligible for re-entry reset (handler-driven via SWITCH), but the
      framework does not retry automatically. PENDING/RUNNING targets cause a
      hard stop.
- [x] **Pluggable Concurrency**: Re-entered nodes acquire concurrency slots via
      the same `slot(key, priority)` path. No change to `ConcurrencyManager`.
- [x] **Snapshot-First Recovery**: `reset_for_reentry` produces snapshot-compatible
      state. All reset fields (`status`, `upstream_completed`, `_completed_nodes`)
      are serialized. `snapshot()`/`restore()` round-trips remain correct.
- [x] **Docstring Doctest Coverage**: Plan includes doctests for `reset_for_reentry`
      and updated doctest gate via `tests/test_doctests.py`.
- [x] **Debug Traceability**: All new control flow uses `eventflow._debug` helpers.
      `reset_for_reentry` logs parameters and variable changes. Scheduler re-entry
      detection logs branch and variable changes.
- [x] **Typing-First Contract**: `reset_for_reentry` is typed. `_execute_node`
      return type changes from `Any` to `Tuple[Any, List[str]]` (internal method).
      All changes pass mypy.
- [x] **Observability & Telemetry**: `visit_count` on `NODE_COMPLETED` events
      correctly reflects cumulative count across re-entries. Event payloads and
      append-only chronology are preserved.
- [x] **Abstraction & Decoupling**: No new interfaces. Changes stay within existing
      `ExecutionState`/`Scheduler`/`Graph` boundary. No circular dependencies.
- [x] **Compatibility First**: `reset_for_reentry` is additive. `_execute_node` is
      internal. No public API breakage. No new runtime dependencies.
- [x] **Bounded Loop Semantics**: `max_visits` enforcement preserved. Visit counts
      accumulate across re-entries. Graph validation rejects shared-node
      multi-loop topologies. Runtime hard stop for PENDING/RUNNING back-edge
      targets as defensive fallback.
- [x] **Explicit Error Propagation**: Fail-fast behavior unchanged. Handler
      exceptions still emit `NODE_FAILED` and re-raise. No silent suppression.
- [x] **Quality Gates**: Plan includes pytest, ruff check, mypy, doctest gate,
      and docs sync.

## Project Structure

### Documentation (this feature)

```text
specs/001-scheduler-loop-reentry/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
eventflow/
├── core/
│   ├── graph.py         # MODIFY: add shared-node multi-loop validation
│   └── state.py         # MODIFY: add reset_for_reentry()
├── scheduler/
│   └── scheduler.py     # MODIFY: re-entry logic in _execute_node + run()
tests/
├── test_integration_workflows.py  # MODIFY: update existing loop test + add e2e tests
└── test_doctests.py               # VERIFY: passes with new doctests
```

**Structure Decision**: Single Python package. All changes are within existing
modules — no new files needed.
