from __future__ import annotations

import asyncio

from loopgraph.concurrency import PrioritySemaphorePolicy


def test_priority_policy_orders_tasks() -> None:
    order: list[str] = []
    policy = PrioritySemaphorePolicy(limit=1)

    async def worker(name: str, priority: int, delay: float) -> None:
        await asyncio.sleep(delay)
        async with policy.slot(name, priority=priority):
            order.append(name)

    async def run() -> None:
        await asyncio.gather(
            worker("low", priority=10, delay=0.01),
            worker("high", priority=0, delay=0.0),
        )

    asyncio.run(run())
    assert order == ["high", "low"]
