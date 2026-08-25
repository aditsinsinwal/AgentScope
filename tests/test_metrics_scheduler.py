import asyncio
from decimal import Decimal

import pytest

from agentscope.agents.base import Usage
from agentscope.metrics.costs import ModelPrice, estimate_cost
from agentscope.scheduler.local import AsyncRunScheduler, InfrastructureFailure, ScheduledJob


def test_cost_is_configuration_driven_and_decimal_exact() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=500_000, cached_tokens=200_000)
    price = ModelPrice(Decimal("2"), Decimal("4"), Decimal("1"))
    assert estimate_cost(usage, price) == Decimal("3.8")


async def test_scheduler_retries_only_explicit_infrastructure_failure() -> None:
    scheduler = AsyncRunScheduler(concurrency=1)
    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise InfrastructureFailure("worker vanished before start")
        return "done"

    future = await scheduler.submit(ScheduledJob(flaky))
    assert await future == "done"
    assert attempts == 2
    await scheduler.close()


async def test_scheduler_does_not_retry_agent_exception() -> None:
    scheduler = AsyncRunScheduler(concurrency=1)
    attempts = 0

    async def broken() -> None:
        nonlocal attempts
        attempts += 1
        raise ValueError("agent outcome")

    future = await scheduler.submit(ScheduledJob(broken))
    with pytest.raises(ValueError, match="agent outcome"):
        await future
    assert attempts == 1
    await scheduler.close()


async def test_scheduler_enforces_concurrency() -> None:
    scheduler = AsyncRunScheduler(concurrency=2)
    active = peak = 0
    lock = asyncio.Lock()

    async def work() -> None:
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.01)
        async with lock:
            active -= 1

    futures = [await scheduler.submit(ScheduledJob(work)) for _ in range(6)]
    await asyncio.gather(*futures)
    assert peak == 2
    await scheduler.close()
