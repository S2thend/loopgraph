# LoopGraph

**The agent workflow engine that treats loops as a first-class citizen.**

Build graph-based AI agent workflows where cycles, re-entry, and iterative reasoning are native — not hacks. More intuitive and lightweight than LangGraph, with loops as a first-class primitive.

- **Zero dependencies** — pure Python 3.10+, nothing to install beyond your own agents
- **Native loop support** — cycles in your graph are validated, tracked, and safe by design
- **Event-driven** — every state transition emits events; hook in logging, metrics, or triggers anywhere
- **Async-first** — built on `asyncio`, handles concurrent nodes without blocking
- **Recoverable** — snapshot and replay any run from any point

```bash
pip install loopgraph
```

---

## Quickstart

```python
import asyncio
from loopgraph.core.graph import Graph, Node, Edge, NodeKind
from loopgraph.bus.eventbus import EventBus
from loopgraph.registry.function_registry import FunctionRegistry
from loopgraph.scheduler.scheduler import Scheduler

async def my_agent(payload):
    # your agent logic here
    return {"result": "done", "loop_again": False}

async def router(payload):
    # return the next node id
    return "end" if not payload.get("loop_again") else "agent"

graph = Graph(
    nodes=[
        Node(id="agent", kind=NodeKind.TASK),
        Node(id="router", kind=NodeKind.SWITCH),
        Node(id="end", kind=NodeKind.TASK),
    ],
    edges=[
        Edge(source="agent", target="router"),
        Edge(source="router", target="agent"),   # the loop back-edge
        Edge(source="router", target="end"),
    ],
    entry="agent",
)

registry = FunctionRegistry()
registry.register("agent", my_agent)
registry.register("router", router)
registry.register("end", lambda p: p)

bus = EventBus()
scheduler = Scheduler(graph=graph, registry=registry, bus=bus)

asyncio.run(scheduler.run(payload={"input": "hello"}))
```

---

## Why LoopGraph?

Most workflow engines assume a DAG — a graph with no cycles. That works for linear pipelines, but agent workflows are inherently iterative: an agent reasons, reflects, decides to try again, and loops back. Forcing that into a DAG requires awkward workarounds.

LoopGraph makes loops explicit and safe:

- **Back-edges are first-class** — declare a cycle in your graph and the engine handles reset, visit tracking, and state management automatically
- **Loop safety** — the engine validates your graph at construction time; overlapping loops that share nodes are rejected before anything runs
- **Full observability** — every loop iteration emits events (`NODE_SCHEDULED`, `NODE_COMPLETED`, `NODE_FAILED`) so you always know where you are

---

## Event Hooks

Subscribe to any workflow event to add logging, metrics, or side effects:

```python
from loopgraph.core.types import EventType

async def on_completed(event):
    print(f"{event.node_id} finished → {event.payload}")

bus.subscribe(EventType.NODE_COMPLETED, on_completed)
```

Available events: `NODE_SCHEDULED`, `NODE_STARTED`, `NODE_COMPLETED`, `NODE_FAILED`.

---

## Custom Events from Handlers

Wrap your handler in a closure to emit custom events mid-execution:

```python
def make_handler(bus, base_handler):
    async def wrapper(payload):
        await bus.emit(Event(id="pre", graph_id="g", node_id="n",
                             type=EventType.NODE_SCHEDULED, payload={"stage": "pre"}))
        result = await base_handler(payload)
        await bus.emit(Event(id="post", graph_id="g", node_id="n",
                             type=EventType.NODE_COMPLETED, payload={"stage": "post"}))
        return result
    return wrapper

registry.register("my_node", make_handler(bus, my_agent))
```

---

## Loop Re-entry Rules

- Re-entry is triggered by a `SWITCH` node selecting a back-edge
- Only `COMPLETED` nodes can be reset for re-entry
- Reset clears upstream-completion tracking and preserves cumulative `visit_count`
- Overlapping loops sharing any node are rejected at graph construction time

## Scheduler Semantics

- The scheduler seeds its internal pending set from graph entry nodes only. A
  node enters pending later only when an upstream edge actually activates it.
- Unselected `SWITCH` branches never enter pending, so leaf branches that were
  not chosen cannot deadlock the workflow.
- A graph with nodes but no entry nodes now fails fast with `ValueError`
  instead of entering a deadlocked run loop.
- If a `SWITCH` returns a route that matches no downstream edge and no
  `exit` fallback edge exists, the scheduler raises `ValueError`.
- `NodeKind.TERMINAL` keeps the same runtime scheduling semantics as `TASK`.

## Recovery Boundaries

- Persisted scheduler snapshots now include `snapshot_format_version`.
- Resume is supported only for snapshots with the current supported snapshot
  format version.
- If a snapshot is missing `snapshot_format_version` or carries an unsupported
  version, resume fails fast with a `ValueError` that reports the actual
  version, the supported version, and discard-or-migrate guidance.
- On resume, pending is rebuilt from uncompleted entry nodes plus nodes already
  persisted as `PENDING` or `RUNNING`. Persisted `RUNNING` nodes are reset to
  `PENDING` before scheduling.

---

## Installation

```bash
pip install loopgraph
```

Requires Python 3.10+. No runtime dependencies.

---

## Development

```bash
git clone https://github.com/your-org/loopgraph
cd loopgraph
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test,lint]"
pytest
```

---

## Design Principles

- **Keep the core compact.** Nodes stay stateless and the scheduler stays simple, with minimum opinionated design and maximum freedom for users to compose their own workflow patterns. Handlers capture their own context (event bus, metrics, side effects) so the framework never grows special cases for custom behaviour.
- **Push heavy lifting to the edge.** Long-running work should run via remote APIs, threads, or separate nodes/clusters. We avoid building a distributed fan-out scheduler; users orchestrate their own parallelism while the engine focuses on deterministic single-node execution.
- **Flexible aggregation semantics.** Aggregator nodes may proceed when only a subset of upstream nodes finish — as long as those nodes reach a terminal state. Fail-fast and error-tolerance are user-level workflow patterns, and the engine stays policy-light so users can implement either.
- **Retries live with handlers.** The framework doesn't implement automatic retries. Each handler decides whether to retry, abort, or compensate, keeping recovery logic close to the business code.
- **Pluggable concurrency.** A shared ConcurrencyManager (semaphore or priority-aware) controls global slots. Multiple schedulers can share one manager, but there's no hidden magic — users choose the policy, preserving clarity and control.
- **Recovery through snapshots.** The engine snapshots execution state and event logs so users can resume or replay runs without re-executing nodes. Payloads flow naturally between nodes, satisfying replay needs without extra APIs.
