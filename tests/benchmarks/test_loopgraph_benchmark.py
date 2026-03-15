from __future__ import annotations

import asyncio
import time

from loopgraph.bus.eventbus import Event, EventBus
from loopgraph.core.types import EventType


class DoubleBufferedQueue:
    """Double-buffered async queue for benchmark baselines."""

    def __init__(self) -> None:
        self._queue: list[Event] = []
        self._waiter: asyncio.Future[Event] | None = None

    def enqueue(self, message: Event) -> None:
        if self._waiter is not None:
            waiter = self._waiter
            self._waiter = None
            waiter.set_result(message)
            return
        self._queue.append(message)

    async def next(self) -> Event:
        if self._queue:
            return self._queue.pop(0)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Event] = loop.create_future()
        self._waiter = future
        return await future


def _event(index: int) -> Event:
    return Event(
        id=f"evt-{index}",
        graph_id="bench",
        node_id=None,
        type=EventType.WORKFLOW_COMPLETED,
    )


def _report(label: str, count: int, elapsed: float) -> None:
    throughput = count / elapsed if elapsed > 0 else 0.0
    per_msg_ms = (elapsed / count) * 1000 if count else 0.0
    print(
        f"eventbus {label}: count={count} total={elapsed:.4f}s "
        f"throughput={throughput:,.0f} msg/s per_msg_ms={per_msg_ms:.3f}"
    )


async def _benchmark_zero_latency(count: int) -> float:
    bus = EventBus()
    queue = DoubleBufferedQueue()

    async def listener(event: Event) -> None:
        queue.enqueue(event)

    bus.subscribe(None, listener)

    start = time.perf_counter()
    for index in range(count):
        consumer = asyncio.create_task(queue.next())
        await bus.emit(_event(index))
        await consumer
    return time.perf_counter() - start


async def _benchmark_buffered(count: int) -> float:
    bus = EventBus()
    queue = DoubleBufferedQueue()

    async def listener(event: Event) -> None:
        queue.enqueue(event)

    bus.subscribe(None, listener)

    start = time.perf_counter()
    for index in range(count):
        await bus.emit(_event(index))
    for _ in range(count):
        await queue.next()
    return time.perf_counter() - start


def test_eventbus_double_buffered_benchmark() -> None:
    count = 50000
    zero_elapsed = asyncio.run(_benchmark_zero_latency(count))
    _report("zero_latency", count, zero_elapsed)

    buffer_elapsed = asyncio.run(_benchmark_buffered(count))
    _report("buffered", count, buffer_elapsed)
