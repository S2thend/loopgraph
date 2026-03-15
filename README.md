# loopgraph

loopgraph is an asynchronous workflow engine experiment driven by immutable graph definitions and exhaustive debug logging.

## Design Principles

- Keep the core compact. Nodes stay stateless and the scheduler stays simple, with minimum opinionated design and maximum freedom for users to compose their own workflow patterns.
  Handlers capture their own context (event bus, metrics, side effects) so the framework never grows special cases for custom behaviour.
- Push heavy lifting to the edge. Long-running work should run via remote APIs, threads, or separate nodes/clusters. We avoid building a distributed fan-out scheduler; users
orchestrate their own parallelism while the engine focuses on deterministic single-node execution.
- Flexible aggregation semantics. Aggregator nodes may proceed when only a subset of upstream nodes finish—as long as those nodes reach a terminal state.
  Fail-fast and error-tolerance are user-level workflow patterns, and the engine stays policy-light so users can implement either.
- Retries live with handlers. The framework doesn’t implement automatic retries. Each handler decides whether to retry, abort, or compensate, keeping recovery logic close to the
business code.
- Pluggable concurrency. A shared ConcurrencyManager (semaphore or priority-aware) controls global slots. Multiple schedulers can share one manager, but there’s no hidden magic—
users choose the policy, preserving clarity and control.
- Recovery through snapshots. The engine snapshots execution state and event logs so users can resume or replay runs without re-executing nodes. Payloads flow naturally between
nodes, satisfying replay needs without extra APIs.

These principles balance extensibility with clarity: you get a predictable, type-safe scheduler that composes with external services, while staying free to layer domain-specific
complexity on top.


## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[test]
pytest
```

## Implemented Modules

- `loopgraph/_debug.py` centralises the verbose logging helpers required by the DevSOP.
- `loopgraph/core/graph.py` provides immutable nodes, edges, and graph serialisation with validation helper methods.
- `loopgraph/core/types.py` defines the enums and outcome helpers reused throughout the codebase.
- `loopgraph/core/state.py` captures execution progress, visit tracking, and snapshot support.
- `loopgraph/bus/eventbus.py` offers an in-memory async event bus for workflow signals.
- `loopgraph/concurrency/policies.py` implements pluggable concurrency managers, including a priority-aware global semaphore.
- `loopgraph/registry/function_registry.py` stores handler functions and executes them with awaitable support.
- `loopgraph/scheduler/scheduler.py` coordinates linear workflows, supports switch/aggregate semantics, and integrates persistence for recovery.
- `loopgraph/persistence/event_log.py` and `loopgraph/persistence/snapshot.py` provide in-memory persistence primitives.
- `loopgraph/diagnostics/inspect.py` supplies inspection helpers for graphs and execution state summaries.

Each function includes doctest examples; the `tests/test_doctests.py` suite ensures the documentation remains executable.

## Loop Re-entry Semantics

- Re-entry is triggered only by a `SWITCH` back-edge selection.
- Back-edge reset is allowed only for `COMPLETED` targets.
- Reset moves target state back to `PENDING`, clears upstream-completion tracking, and preserves cumulative `visit_count`.
- If a selected back-edge target is not `COMPLETED`, re-entry reset is not applied.
- Handler exceptions keep existing fail-fast behavior: emit `NODE_FAILED`, persist state, and re-raise.
- Loop cycles of arbitrary length are supported, including multiple disjoint loops.
- Multiple loops sharing any node are explicitly disallowed and rejected during graph construction/validation.

## custom listeners
You can hook into the workflow lifecycle by registering async listeners on the EventBus before you start the scheduler. The EventBus.subscribe(event_type, listener) API lets
you target a specific EventType (or pass None for “catch everything”). Each listener is awaited with the emitted Event, so you can perform side effects—logging, metrics,
persistence, etc.—inside the coroutine.

Reference implementation:

- Listener registration and dispatch live in loopgraph/bus/eventbus.py:70. subscribe stores your callable; emit collects typed plus global listeners and runs them via
asyncio.create_task.
- Event types such as NODE_SCHEDULED, NODE_COMPLETED, and NODE_FAILED are defined in loopgraph/core/types.py:40.
- The scheduler forwards every state change through _dispatch_event, so your listeners see everything (loopgraph/scheduler/scheduler.py:171).

Example:
```py
import asyncio
from loopgraph.bus.eventbus import EventBus
from loopgraph.core.types import EventType

async def on_node_completed(event):
    if event.type is EventType.NODE_COMPLETED:
        print(f"{event.node_id} finished with payload {event.payload}")

bus = EventBus()
bus.subscribe(EventType.NODE_COMPLETED, on_node_completed)

# wire the same bus into Scheduler(...)
```
Because listeners are standard coroutines, you can fire off side effects—write to a database, push metrics, trigger other services—without altering the core scheduler.


## how to emit custom events during node task execution?


• Out of the box we don’t inject the EventBus into node handlers, so tasks can’t call emit directly. But you can still raise custom events by wrapping your handler in a closure that
  already knows about the bus. That’s exactly the pattern FunctionRegistry supports—registering callables that capture external state.

  Example:

  async def make_notifying_handler(bus: EventBus, base_handler):
      async def wrapper(payload):
          await bus.emit(Event(
              id="custom-start",
              graph_id="graph-1",
              node_id="notification",
              type=EventType.NODE_SCHEDULED,  # or define your own enum
              payload={"stage": "pre"},
          ))
          result = await base_handler(payload)
          await bus.emit(Event(
              id="custom-complete",
              graph_id="graph-1",
              node_id="notification",
              type=EventType.NODE_COMPLETED,
              payload={"stage": "post", "result": result},
          ))
          return result
      return wrapper

  registry.register("task", await make_notifying_handler(bus, my_handler))

  Every time the node runs, your wrapper emits the custom events via the same EventBus the scheduler uses (loopgraph/bus/eventbus.py:70), so all subscribed listeners see them.
  Since FunctionRegistry just stores the callable you register, capturing the bus in a closure is the simplest way to let handlers emit additional events without changing scheduler
  internals.
