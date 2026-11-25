from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
from typing import ClassVar

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agentscope.agents.mock import MockAction, MockAgent
from agentscope.application.repositories import InMemoryRunRepository
from agentscope.application.run_engine import RunEngine
from agentscope.config import get_settings
from agentscope.domain.models import AgentConfiguration, ExperimentRun, TaskId
from agentscope.evaluation.evaluator import TestBasedEvaluator
from agentscope.execution.sandbox.docker import DockerSandbox
from agentscope.persistence.models import TaskRecord
from agentscope.persistence.repositories import SqlAlchemyRunRepository, SqlAlchemyTraceRecorder
from agentscope.tasks.loader import load_task
from agentscope.tracing.models import EventType, TraceEvent
from agentscope.tracing.recorder import InMemoryTraceRecorder

ROOT = Path(__file__).parents[1]


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("AGENTSCOPE_TEST_POSTGRES") != "1",
    reason="set AGENTSCOPE_TEST_POSTGRES=1 after alembic upgrade head",
)
async def test_postgres_run_repository_round_trip() -> None:
    engine = create_async_engine(get_settings().database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session, session.begin():
        await session.merge(
            TaskRecord(
                id="persistence-integration",
                name="Persistence integration",
                version="1",
                fingerprint="0" * 64,
                definition={"source": "integration-test"},
            )
        )
    repository = SqlAlchemyRunRepository(sessions)
    run = ExperimentRun(TaskId("persistence-integration"), AgentConfiguration("mock"))
    await repository.save(run)
    loaded = await repository.get(run.id)
    traces = SqlAlchemyTraceRecorder(sessions)
    recorded = await traces.append(TraceEvent(run.id, 0, EventType.AGENT_STEP, "smoke"))
    loaded_events = await traces.events(run.id)
    await engine.dispose()
    assert loaded == run
    assert recorded.sequence == 1
    assert loaded_events == (recorded,)


@pytest.mark.docker
@pytest.mark.skipif(
    os.getenv("AGENTSCOPE_TEST_DOCKER") != "1",
    reason="set AGENTSCOPE_TEST_DOCKER=1 after building the sandbox image",
)
async def test_two_container_hidden_test_boundary() -> None:
    task = load_task(ROOT / "examples/cart-empty-500/task.yaml")
    action = MockAction(
        "replace_text",
        {
            "path": "cart.py",
            "old": "    total = sum(items)",
            "new": (
                "    if not items:\n"
                "        return {'status': 'empty', 'total': 0}\n"
                "    total = sum(items)"
            ),
            "expected_replacements": 1,
        },
    )
    engine = RunEngine(
        InMemoryRunRepository(),
        InMemoryTraceRecorder(),
        TestBasedEvaluator(),
        lambda value: DockerSandbox(value.repository, value.hidden_tests),
    )
    result = await engine.execute(
        ExperimentRun(task.id, AgentConfiguration("mock")), task, MockAgent((action,))
    )
    assert result.result is not None and result.result.passed


class _ProbingSandbox(DockerSandbox):
    """Real DockerSandbox that records its container id and probes the network on entry."""

    instances: ClassVar[list[_ProbingSandbox]] = []

    async def __aenter__(self) -> _ProbingSandbox:
        await super().__aenter__()
        type(self).instances.append(self)
        self.container_id: str = self._container.id
        self.hidden_dir_present = (
            "\n".join(await self.list_directory(PurePosixPath("."))).find(
                ".agentscope_hidden_tests"
            )
            >= 0
        )
        self.network_probe = await self.execute(
            (
                "python",
                "-c",
                "import socket;socket.create_connection(('1.1.1.1', 443), timeout=3)",
            ),
            20,
        )
        return self


@pytest.mark.docker
@pytest.mark.skipif(
    os.getenv("AGENTSCOPE_TEST_DOCKER") != "1",
    reason="set AGENTSCOPE_TEST_DOCKER=1 after building the sandbox image",
)
async def test_agent_and_evaluator_run_in_separate_network_less_containers() -> None:
    task = load_task(ROOT / "examples/cart-empty-500/task.yaml")
    actions = tuple(
        MockAction(item["tool"], item["arguments"])
        for item in json.loads((ROOT / "examples/cart-empty-500/mock-actions.json").read_text())
    )
    _ProbingSandbox.instances = []
    engine = RunEngine(
        InMemoryRunRepository(),
        InMemoryTraceRecorder(),
        TestBasedEvaluator(),
        lambda value: _ProbingSandbox(value.repository, value.hidden_tests),
    )
    result = await engine.execute(
        ExperimentRun(task.id, AgentConfiguration("mock")), task, MockAgent(actions)
    )
    assert result.result is not None and result.result.passed
    agent_box, evaluator_box = _ProbingSandbox.instances
    assert agent_box.container_id != evaluator_box.container_id
    # The agent container never holds hidden tests; the evaluator installs them after the freeze.
    assert agent_box.hidden_dir_present is False
    # Outbound network calls fail in both containers (network_disabled=True).
    for box in (agent_box, evaluator_box):
        assert box.network_probe.exit_code != 0
        assert "OSError" in box.network_probe.stderr or "Error" in box.network_probe.stderr
