from pathlib import Path

from agentscope.agents.mock import MockAction, MockAgent
from agentscope.application.repositories import InMemoryRunRepository
from agentscope.application.run_engine import RunEngine
from agentscope.domain.models import AgentConfiguration, ExperimentRun, FaultInjectionPolicy
from agentscope.domain.states import RunStatus
from agentscope.evaluation.evaluator import TestBasedEvaluator
from agentscope.execution.sandbox.local import LocalSandbox
from agentscope.reliability.faults import FaultInjectingEnvironment
from agentscope.tasks.loader import load_task
from agentscope.tracing.recorder import InMemoryTraceRecorder

ROOT = Path(__file__).parents[1]

CORRECT = (
    "def checkout(items: list[int]) -> dict[str, int | str]:\n"
    "    if not items:\n"
    "        return {'status': 'empty', 'total': 0}\n"
    "    total = sum(items)\n"
    "    return {'status': 'ok', 'total': total, 'average': total // len(items)}\n"
)


async def test_complete_local_run_is_measured_end_to_end() -> None:
    task = load_task(ROOT / "examples/cart-empty-500/task.yaml")
    traces = InMemoryTraceRecorder()
    runs = InMemoryRunRepository()
    engine = RunEngine(
        runs,
        traces,
        TestBasedEvaluator(),
        lambda task: LocalSandbox(task.repository, task.hidden_tests),
    )
    run = ExperimentRun(task.id, AgentConfiguration("mock"))
    result = await engine.execute(
        run, task, MockAgent((MockAction("write_file", {"path": "cart.py", "content": CORRECT}),))
    )
    assert result.status is RunStatus.COMPLETED
    assert result.result is not None and result.result.passed
    assert result.result.score.total == 100
    assert result.task_hash
    assert len(await traces.events(run.id)) >= 8


class EchoEnvironment:
    tools = ()

    async def call_tool(self, name: str, arguments: dict[str, object]) -> object:
        raise AssertionError("wrapped environment should not be reached")


async def test_seeded_fault_injection_is_repeatable() -> None:
    policy = FaultInjectionPolicy(seed=7, tool_failure_probability=1)
    first = FaultInjectingEnvironment(EchoEnvironment(), policy)  # type: ignore[arg-type]
    second = FaultInjectingEnvironment(EchoEnvironment(), policy)  # type: ignore[arg-type]
    a = await first.call_tool("read_file", {})
    b = await second.call_tool("read_file", {})
    assert a.error == b.error == "injected tool failure"
