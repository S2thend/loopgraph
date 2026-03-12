# Quickstart: Scheduler Loop Re-entry

**Feature**: 001-scheduler-loop-reentry
**Date**: 2026-02-20

## Usage Example

### Bounded Loop (max_visits=3)

```python
import asyncio
from eventflow.bus.eventbus import EventBus
from eventflow.concurrency import PrioritySemaphorePolicy
from eventflow.core.graph import Edge, Graph, Node
from eventflow.core.types import NodeKind
from eventflow.registry.function_registry import FunctionRegistry
from eventflow.scheduler.scheduler import Scheduler

# 1. Define handlers
registry = FunctionRegistry()
counter = {"n": 0}

def loop_body(payload):
    counter["n"] += 1
    return {"iteration": counter["n"]}

def switch_handler(payload):
    # Continue looping until 3 iterations, then exit
    if counter["n"] < 3:
        return "continue"
    return "done"

def output_handler(payload):
    return f"Finished after {payload['iteration']} iterations"

registry.register("loop_body", loop_body)
registry.register("switch", switch_handler)
registry.register("output", output_handler)

# 2. Build graph with back-edge
graph = Graph(
    nodes={
        "loop_body": Node(
            id="loop_body",
            kind=NodeKind.TASK,
            handler="loop_body",
            max_visits=3,
            allow_partial_upstream=True,
        ),
        "switch": Node(
            id="switch",
            kind=NodeKind.SWITCH,
            handler="switch",
        ),
        "output": Node(
            id="output",
            kind=NodeKind.TASK,
            handler="output",
        ),
    },
    edges={
        "body->switch": Edge(
            id="body->switch", source="loop_body", target="switch"
        ),
        "switch->body": Edge(
            id="switch->body",
            source="switch",
            target="loop_body",
            metadata={"route": "continue"},  # back-edge
        ),
        "switch->output": Edge(
            id="switch->output",
            source="switch",
            target="output",
            metadata={"route": "done"},
        ),
    },
)

# 3. Run
async def main():
    scheduler = Scheduler(registry, EventBus(), PrioritySemaphorePolicy(1))
    results = await scheduler.run(graph)
    print(results["output"])  # "Finished after 3 iterations"

asyncio.run(main())
```

### Unbounded Loop (handler-controlled exit)

Same pattern but omit `max_visits` on the loop body node:

```python
"loop_body": Node(
    id="loop_body",
    kind=NodeKind.TASK,
    handler="loop_body",
    # max_visits omitted — handler decides when to exit
    allow_partial_upstream=True,
),
```

The SWITCH handler returns `"done"` when the termination condition is met.

## Running Tests

```bash
cd /Users/borui/Devs/open-source-general-agents/wormhole/eventflow

# All tests
python -m pytest tests/ -v

# Integration tests only
python -m pytest tests/test_integration_workflows.py -v

# Doctest gate
python -m pytest --doctest-modules eventflow/core/state.py
python -m pytest --doctest-modules eventflow/scheduler/scheduler.py

# Type check
mypy

# Lint
ruff check
```

## Key Concepts

- **Back-edge**: A SWITCH edge whose target is a node earlier in the graph
  (creating a cycle). Identified by `metadata={"route": "..."}`.
- **Re-entry**: When the scheduler resets a completed node to PENDING so it can
  be scheduled again. Visit count is preserved.
- **`max_visits`**: Upper bound on how many times a node can execute. When
  exhausted, the SWITCH falls back to the `"exit"` route.
- **`allow_partial_upstream`**: Required on back-edge targets so they can be
  re-scheduled even when not all upstream nodes are completed.
