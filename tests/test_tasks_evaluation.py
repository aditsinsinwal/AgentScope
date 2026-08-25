from pathlib import Path

import pytest

from agentscope.domain.errors import TaskDefinitionError
from agentscope.evaluation.evaluator import TestBasedEvaluator
from agentscope.execution.sandbox.local import LocalSandbox
from agentscope.tasks.loader import load_task, task_fingerprint

ROOT = Path(__file__).parents[1]


def test_load_task_and_stable_fingerprint() -> None:
    task = load_task(ROOT / "examples/cart-empty-500/task.yaml")
    assert task.id == "cart-empty-500"
    assert len(task_fingerprint(task)) == 64


def test_task_loader_rejects_path_escape(tmp_path: Path) -> None:
    definition = tmp_path / "task.yaml"
    definition.write_text(
        "id: bad-task\nname: Bad\nrepository: ../\ndescription: bad\n"
        "public_test_command: pytest\nhidden_test_command: pytest\n"
    )
    with pytest.raises(TaskDefinitionError, match="escapes"):
        load_task(definition)


async def test_evaluator_scores_a_correct_patch() -> None:
    task = load_task(ROOT / "examples/cart-empty-500/task.yaml")
    async with LocalSandbox(task.repository, task.hidden_tests) as sandbox:
        before = await sandbox.snapshot_hashes(task.forbidden_paths)
        await sandbox.write_file(
            __import__("pathlib").PurePosixPath("cart.py"),
            "def checkout(items: list[int]) -> dict[str, int | str]:\n"
            "    if not items:\n        return {'status': 'empty', 'total': 0}\n"
            "    total = sum(items)\n"
            "    return {'status': 'ok', 'total': total, 'average': total // len(items)}\n",
        )
        result = await TestBasedEvaluator().evaluate(task, sandbox, before)
    assert result.passed
    assert result.score.total == 100
