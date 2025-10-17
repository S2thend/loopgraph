# EventFlow2

EventFlow2 is an asynchronous workflow engine experiment driven by immutable graph definitions and exhaustive debug logging.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[test]
pytest
```

## Implemented Modules

- `eventflow/_debug.py` centralises the verbose logging helpers required by the DevSOP.
- `eventflow/core/graph.py` provides immutable nodes, edges, and graph serialisation with validation helper methods.
- `eventflow/core/types.py` defines the enums and outcome helpers reused throughout the codebase.
- `eventflow/core/state.py` captures execution progress, visit tracking, and snapshot support.
- `eventflow/bus/eventbus.py` offers an in-memory async event bus for workflow signals.
- `eventflow/concurrency/policies.py` implements the semaphore-based concurrency policy.
- `eventflow/registry/function_registry.py` stores handler functions and executes them with awaitable support.
- `eventflow/scheduler/scheduler.py` coordinates linear workflows by combining the registry, state, and event bus.
- `eventflow/persistence/event_log.py` and `eventflow/persistence/snapshot.py` provide in-memory persistence primitives.
- `eventflow/diagnostics/inspect.py` supplies inspection helpers for graphs and execution state summaries.

Each function includes doctest examples; the `tests/test_doctests.py` suite ensures the documentation remains executable.
