<!--
Sync Impact Report
===================
Version change: 1.5.3 → 1.5.4
Modified principles:
  - XIV. Bounded Loop Semantics: re-added runtime hard-stop for PENDING/RUNNING
    back-edge targets as defensive fallback; added SWITCH self-loop rejection
    at graph validation
Removed sections: none
Added sections: none
Technical Constraints changes: none
Development Workflow changes: none
Governance changes: none
Templates requiring updates:
  - No template changes required (principle clarification)
Follow-up TODOs: none

Previous sync (1.5.2 → 1.5.3):
  Modified: XIV (disjoint loops, removed runtime hard-stop); Constraints: none
-->

# EventFlow2 Constitution

## Core Principles

### I. Compact Core

Workflow primitives (`Node`, `Edge`) MUST remain immutable, and scheduler
responsibilities MUST stay limited to dependency resolution, handler dispatch,
and state/event persistence. Domain-specific behavior (metrics, retries, side
effects, remote orchestration) MUST live in handlers or external services. Any
proposal to expand core modules MUST first show why the behavior cannot be
composed outside `eventflow/core` and `eventflow/scheduler`. Core APIs MUST stay
minimally opinionated to maximize user freedom in workflow design. EventFlow2's
core is a graph execution engine; features outside graph execution semantics are
out of scope unless required for correctness. Design decisions MUST follow
Occam's razor: choose the smallest correct core behavior and push optional
policy to handlers or integrations.

Rationale: the less policy built into the engine, the more predictable and
resilient the platform remains across diverse workloads. Keeping core logic
compact and scope-disciplined maximizes long-term flexibility for user-level
composition.

### II. Edge-Heavy Work

Scheduler execution MUST remain single-process async orchestration. Long-running
or resource-intensive work MUST be delegated to handler-managed remote APIs,
threads, or external worker systems. The framework MUST NOT add a built-in
distributed fan-out scheduler.

Rationale: deterministic local orchestration improves reproducibility,
operability, and failure analysis.

### III. Flexible Aggregation Semantics

Node readiness MUST be derived from explicit configuration (`config.required`,
`allow_partial_upstream`, `max_visits`) plus terminal upstream outcomes.
EventFlow2 MUST provide primitives that allow users to implement their own
patterns (including fail-fast and error-tolerant flows) without the engine
enforcing a single global failure strategy.

Rationale: explicit, composable primitives preserve flexibility while keeping
runtime behavior inspectable.

### IV. Handler-Owned Retries and Error Handling

The framework MUST NOT implement automatic retries, backoff, or compensation.
Retries, compensation, fail-fast behavior, and error-tolerance behavior MUST be
implemented by user workflow logic and handlers.

Rationale: keeping recovery logic close to domain code avoids hidden scheduler
policy and preserves maximum freedom.

### V. Pluggable Concurrency

A `ConcurrencyManager` implementation MUST gate every node execution via
`slot(key, priority)`. Shared manager instances MAY be reused across scheduler
instances to enforce global capacity. The core MAY provide simple policies
(`SemaphorePolicy`, `PrioritySemaphorePolicy`), but concurrency policy selection
MUST remain explicit at scheduler construction.

Rationale: explicit concurrency policy prevents hidden contention and keeps
throughput tradeoffs visible.

### VI. Snapshot-First Recovery

Execution-state changes MUST preserve `ExecutionState.snapshot()` /
`ExecutionState.restore()` compatibility and JSON-serializable payloads.
Scheduler recovery paths MUST support resuming already-completed nodes from
snapshots without re-executing them when prior state exists. Event logs, when
configured, MUST remain append-only.

Rationale: resumability and replayable traces are required for long-running
workflows and post-incident diagnostics.

### VII. Docstring Doctest Coverage

Every public function and non-trivial internal helper MUST include doctest-style
examples in docstrings. Changes that modify examples or behavior MUST keep
`tests/test_doctests.py` passing.

Rationale: executable examples keep documentation truthful and prevent drift.

### VIII. Debug Traceability

Runtime control-flow changes MUST emit structured debug traces for parameter
inputs, return values, branch selection, loop progression, and variable updates
using `eventflow._debug` helpers. Logs MUST be machine-parseable and stable in
shape (for example, key-value fields or JSON), and SHOULD include `function`,
`call_id`, `branch`, `loop_iter`, and `elapsed_ms` when applicable. Redaction
policy is out of scope for this base dependency and is delegated to consuming
applications. Debug tracing MUST be disabled by default for production/release
runs and MUST be removable from release artifacts.

Rationale: structured traces accelerate diagnosis while keeping production
behavior stable and policy surface minimal.

### IX. Typing-First API Contract

Public APIs MUST provide complete type annotations and preserve PEP 561 typing
support. The `py.typed` marker file MUST be present in the published package.
Changes to `eventflow/` MUST pass repository type-check configuration before
merge.

Rationale: strong typing improves correctness while keeping integration behavior
predictable.

### X. Linting & Formatting Discipline

Code changes MUST satisfy repository lint/format policy (`ruff`) before merge.
Formatting and lint checks are mandatory quality gates, not optional cleanup.

Rationale: consistent style reduces review friction and avoids avoidable defects.

### XI. Observability & Telemetry

Execution lifecycle events MUST remain observable through `EventBus` emissions,
and optional `EventLog` recording MUST preserve append-only chronology. Event
payloads MUST contain enough identifiers (`graph_id`, `node_id`, status/type) to
support cross-run diagnosis and telemetry correlation.

Rationale: stable observability is required for production debugging and replay.

### XII. Abstraction & Decoupling Discipline

High-level orchestration MUST depend on protocols/interfaces (`ConcurrencyManager`,
`SnapshotStore`, `EventLog`) rather than concrete infrastructure details.
Abstractions MUST be introduced only for recurring, proven reuse; circular
dependencies are forbidden.

Rationale: controlled abstraction preserves flexibility without over-engineering.

### XIII. Compatibility First

Platform decisions MUST prioritize broad runtime compatibility and low dependency
burden. Runtime dependencies MUST stay minimal and public API changes MUST include
deprecation or migration guidance when behavior changes.

Rationale: compatibility-first design keeps EventFlow deployable across diverse
environments.

### XIV. Bounded Loop Semantics

The scheduler MUST track visit counts for every node and MUST NOT re-schedule a
node whose visit count has reached its `max_visits` limit. Nodes targeted by
back-edges are SUGGESTED to declare an explicit `max_visits` to ensure
deterministic termination. When `max_visits` is not set, the scheduler SHOULD
declare an explicit termination strategy; omitting one is permitted for
intentionally unbounded loops (e.g., a primary agent loop) where the handler
controls exit. The scheduler MUST support loop topologies of any cycle length
and MAY include multiple disjoint loops in the same graph. Multiple loops that
share nodes are explicitly OUT OF SCOPE; graph construction MUST reject graphs
containing shared-node multi-loop topologies before execution begins. SWITCH
self-loops (a SWITCH node routing back to itself) MUST be rejected at graph
validation. The scheduler MUST additionally raise a runtime error if a back-edge
targets a node in a non-terminal state (PENDING or RUNNING) as a defensive
fallback.

Rationale: deterministic termination prevents runaway workflows and makes loop
behavior inspectable and testable, while allowing intentionally unbounded loops
where the handler owns the exit decision. Allowing disjoint loops preserves
expressiveness without adding state-ownership conflicts; rejecting shared-node
multi-loop topologies avoids ambiguous re-entry ownership and contention.
SWITCH self-loops are meaningless (routing without processing) and are rejected
to prevent degenerate graphs. The runtime hard-stop for non-terminal back-edge
targets is a defensive fallback for bugs that bypass graph validation.

### XV. Explicit Error Propagation

Listener and handler errors MUST NOT be silently discarded. The `EventBus` MUST
route listener exceptions through an explicit error callback when configured.
Unhandled listener failures in the absence of an error callback MUST be logged at
warning level or above. Framework components MUST NOT catch-and-suppress
exceptions without providing an observable signal.

Rationale: silent error swallowing hides failures and undermines the
observability guarantees of Principle XI.

## Technical Constraints

- **Language**: Python 3.10+ (`pyproject.toml` `requires-python`).
- **Async-first API**: Public scheduling and event dispatch interfaces MUST
  remain async (`Scheduler.run`, `EventBus.emit`, `FunctionRegistry.execute`).
  Synchronous wrappers are allowed only at the outermost boundary (tests,
  scripts, examples).
- **Zero runtime dependencies**: The published `eventflow` package MUST NOT
  declare runtime dependencies in `[project.dependencies]`.
- **License compatibility**: Contributions MUST remain compatible with MIT
  licensing.
- **Type safety**: Public APIs MUST carry complete type annotations, and changes
  to `eventflow/` MUST pass mypy using repository configuration
  (`pyproject.toml` `[tool.mypy]`).
- **Formatting/linting**: Changes to `eventflow/` MUST pass `ruff check` using
  repository configuration.
- **Diagnostic instrumentation**: Non-trivial control flow changes in runtime
  modules MUST use `eventflow._debug` logging helpers
  (`log_parameter`, `log_variable_change`, `log_branch`, `log_loop_iteration`).
- **Debug logging release policy**: Development debug traces MUST be gated by
  `logging.getLogger` level configuration and MUST be disabled by default (level
  above DEBUG). Debug instrumentation MUST NOT require compile-time removal or
  code stripping for production use.
- **Handler-owned retries/compensation**: The framework MUST NOT add implicit
  retry/backoff policies; retry and compensation logic MUST remain in user
  workflow logic and handlers.
- **Occam scope gate**: Core scheduler changes MUST prefer the smallest correct
  graph-execution behavior; optional domain policy and out-of-scope orchestration
  logic MUST be implemented in handlers, integrations, or external services.

## Development Workflow

- **Tests are mandatory**: Every feature and bug fix MUST include automated
  tests under `tests/` that demonstrate behavior changes.
- **Executable examples**: Any change that modifies documented examples MUST keep
  doctest coverage green via `tests/test_doctests.py`.
- **Spec and docs sync**: Changes to scheduler/state semantics MUST update
  affected docs and specs in the same change set (minimum: `README.md` plus
  impacted `docs/` or `specs/` files).
- **Review and branch policy**: Changes under `eventflow/` MUST be reviewed
  before merge. Feature branches MUST follow the numbered pattern
  `^[0-9]{3}-...` consistent with `.specify/scripts/bash/common.sh`. Hotfix and
  release branches are exempt from this naming convention.

## Governance

This constitution is the highest-authority engineering policy for EventFlow2.
When plans, specs, tasks, or implementation choices conflict with this
constitution, this document takes precedence.

**Amendment procedure**:

1. Submit a pull request that modifies this file and explains the exact
   principle or section impact.
2. Include a migration and compatibility note for any runtime semantic change
   (scheduler behavior, state model, event model, or persistence contract).
3. Obtain approval from at least one maintainer.
4. Update the Sync Impact Report at the top of this file, including required
   template/runtime-doc propagation status.
5. Update `CONSTITUTION_VERSION` and `LAST_AMENDED_DATE` upon merge.

**Versioning policy** (semantic):

- **MAJOR**: Removal or backward-incompatible redefinition of a core principle.
- **MINOR**: Addition of a new principle or materially expanded governance.
- **PATCH**: Clarifications, wording improvements, and non-semantic refinements.

**Compliance review expectations**:

- Every implementation plan MUST include a Constitution Check against all core
  principles.
- Every feature specification MUST include a Constitution Alignment section
  addressing core boundary, execution semantics, failure strategy, concurrency,
  recovery, debug logging, typing, and validation impacts.
- Every tasks list MUST include constitution-required quality tasks
  (tests, lint/type checks, and documentation sync when semantics change),
  including user-defined failure-pattern tests where applicable.
- Every pull request MUST state how constitution compliance was validated.

**Version**: 1.5.4 | **Ratified**: 2026-02-14 | **Last Amended**: 2026-02-28
