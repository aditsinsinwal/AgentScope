from pathlib import Path

from agentscope.domain.models import RunId
from agentscope.execution.sandbox.local import LocalSandbox
from agentscope.execution.tools.registry import default_tool_registry
from agentscope.tracing.recorder import InMemoryTraceRecorder


async def test_tools_validate_paths_and_record_two_events(tmp_path: Path) -> None:
    (tmp_path / "source.py").write_text("answer = 41\n")
    recorder = InMemoryTraceRecorder()
    run_id = RunId("run_test")
    async with LocalSandbox(tmp_path) as sandbox:
        registry = default_tool_registry(sandbox, recorder, run_id)
        result = await registry.call(
            "replace_text",
            {"path": "source.py", "old": "41", "new": "42", "expected_replacements": 1},
        )
        rejected = await registry.call("read_file", {"path": "../secret"})
    assert result.success
    assert not rejected.success
    assert len(await recorder.events(run_id)) == 4


async def test_command_allowlist_rejects_shell(tmp_path: Path) -> None:
    recorder = InMemoryTraceRecorder()
    async with LocalSandbox(tmp_path) as sandbox:
        registry = default_tool_registry(sandbox, recorder, RunId("run_test"))
        result = await registry.call("run_command", {"argv": ["sh", "-c", "true"]})
    assert not result.success
    assert "not allowlisted" in (result.error or "")


async def test_workspace_root_is_a_valid_list_path(tmp_path: Path) -> None:
    (tmp_path / "source.py").write_text("pass\n")
    recorder = InMemoryTraceRecorder()
    async with LocalSandbox(tmp_path) as sandbox:
        registry = default_tool_registry(sandbox, recorder, RunId("run_test"))
        result = await registry.call("list_directory", {"path": "."})
    assert result.success
    assert result.content == "source.py"
