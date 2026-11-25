from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from agentscope.config import get_settings
from agentscope.domain.errors import RunNotFoundError
from agentscope.domain.models import AgentConfiguration, ExperimentRun, TaskId
from agentscope.domain.states import RunStatus
from agentscope.persistence.models import TaskRecord
from agentscope.persistence.repositories import SqlAlchemyRunRepository, SqlAlchemyTraceRecorder
from agentscope.tracing.models import EventType, TraceEvent

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("AGENTSCOPE_TEST_POSTGRES") != "1",
        reason="set AGENTSCOPE_TEST_POSTGRES=1 after alembic upgrade head",
    ),
]

TASK = "persistence-ordering"


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker]:  # type: ignore[type-arg]
    engine: AsyncEngine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await session.merge(
            TaskRecord(
                id=TASK,
                name="Persistence ordering",
                version="1",
                fingerprint="1" * 64,
                definition={"source": "integration-test"},
            )
        )
    yield factory
    await engine.dispose()


async def test_concurrent_trace_appends_are_gap_free_and_ordered(
    sessions: async_sessionmaker,  # type: ignore[type-arg]
) -> None:
    runs = SqlAlchemyRunRepository(sessions)
    traces = SqlAlchemyTraceRecorder(sessions)
    run = ExperimentRun(TaskId(TASK), AgentConfiguration("mock"))
    await runs.save(run)
    count = 20
    recorded = await asyncio.gather(
        *(
            traces.append(TraceEvent(run.id, 0, EventType.AGENT_STEP, f"step-{index}"))
            for index in range(count)
        )
    )
    assert sorted(event.sequence for event in recorded) == list(range(1, count + 1))
    loaded = await traces.events(run.id)
    assert [event.sequence for event in loaded] == list(range(1, count + 1))
    assert {event.name for event in loaded} == {f"step-{index}" for index in range(count)}


async def test_trace_append_for_unknown_run_is_rejected(
    sessions: async_sessionmaker,  # type: ignore[type-arg]
) -> None:
    traces = SqlAlchemyTraceRecorder(sessions)
    stranger = ExperimentRun(TaskId(TASK), AgentConfiguration("mock"))
    with pytest.raises(RunNotFoundError):
        await traces.append(TraceEvent(stranger.id, 0, EventType.AGENT_STEP, "orphan"))
    assert await traces.events(stranger.id) == ()


async def test_run_save_is_an_upsert_and_unknown_run_raises(
    sessions: async_sessionmaker,  # type: ignore[type-arg]
) -> None:
    runs = SqlAlchemyRunRepository(sessions)
    run = ExperimentRun(TaskId(TASK), AgentConfiguration("mock"))
    await runs.save(run)
    queued = run.transition(RunStatus.QUEUED)
    await runs.save(queued)
    loaded = await runs.get(run.id)
    assert loaded == queued
    assert loaded.status is RunStatus.QUEUED
    assert run.id in {item.id for item in await runs.list(limit=1000)}
    other = ExperimentRun(TaskId(TASK), AgentConfiguration("mock"))
    with pytest.raises(RunNotFoundError):
        await runs.get(other.id)
