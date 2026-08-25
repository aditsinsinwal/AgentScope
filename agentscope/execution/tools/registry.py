from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentscope.domain.errors import ToolExecutionError
from agentscope.domain.models import RunId
from agentscope.execution.sandbox.base import Sandbox
from agentscope.execution.tools.models import ToolDefinition, ToolOutput
from agentscope.tracing.models import EventType, TraceEvent
from agentscope.tracing.recorder import TraceRecorder


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PathInput(StrictInput):
    path: str = Field(min_length=1)


class ReadFileInput(PathInput):
    max_bytes: int = Field(default=1_000_000, ge=1, le=2_000_000)


class SearchInput(PathInput):
    query: str = Field(min_length=1, max_length=500)


class WriteFileInput(PathInput):
    content: str = Field(max_length=2_000_000)


class ReplaceTextInput(PathInput):
    old: str = Field(min_length=1, max_length=500_000)
    new: str = Field(max_length=500_000)
    expected_replacements: int = Field(default=1, ge=1, le=1000)


class RunCommandInput(StrictInput):
    argv: tuple[str, ...] = Field(min_length=1, max_length=64)
    timeout_seconds: float = Field(default=60, gt=0, le=300)


ToolHandler = Callable[[BaseModel], Awaitable[str]]


class ToolRegistry:
    def __init__(
        self,
        sandbox: Sandbox,
        recorder: TraceRecorder,
        run_id: RunId,
        *,
        allowed_commands: Sequence[str] = ("pytest", "python", "git", "ruff"),
    ) -> None:
        self.sandbox = sandbox
        self.recorder = recorder
        self.run_id = run_id
        self.allowed_commands = frozenset(allowed_commands)
        self._tools: dict[str, tuple[type[BaseModel], ToolDefinition, ToolHandler]] = {}

    def register(
        self,
        model: type[BaseModel],
        definition: ToolDefinition,
        handler: ToolHandler,
    ) -> None:
        if definition.name in self._tools:
            raise ValueError(f"duplicate tool: {definition.name}")
        self._tools[definition.name] = (model, definition, handler)

    @property
    def definitions(self) -> Sequence[ToolDefinition]:
        return tuple(item[1] for item in self._tools.values())

    async def call(self, name: str, arguments: Mapping[str, Any]) -> ToolOutput:
        if name not in self._tools:
            raise ToolExecutionError(f"unknown or disabled tool: {name}")
        model, definition, handler = self._tools[name]
        summary = json.dumps(arguments, default=str)
        # Avoid retaining file contents in traces.
        if "content" in arguments:
            summary = json.dumps(
                {**arguments, "content": f"<{len(str(arguments['content']))} chars>"}
            )
        await self.recorder.append(
            TraceEvent(self.run_id, 0, EventType.TOOL_CALL, name, input_summary=summary[:2000])
        )
        started = time.monotonic()
        try:
            validated = model.model_validate(arguments)
            content = await asyncio.wait_for(handler(validated), definition.timeout_seconds)
            duration = (time.monotonic() - started) * 1000
            output = ToolOutput(True, content, duration)
        except (ValidationError, ToolExecutionError, OSError, ValueError, TimeoutError) as exc:
            duration = (time.monotonic() - started) * 1000
            output = ToolOutput(False, "", duration, str(exc))
        await self.recorder.append(
            TraceEvent(
                self.run_id,
                0,
                EventType.TOOL_RESULT,
                name,
                duration_ms=output.duration_ms,
                status="success" if output.success else "error",
                output_summary=output.content[:2000] if output.success else None,
                error=output.error,
            )
        )
        return output


def _schema(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema()


def default_tool_registry(
    sandbox: Sandbox,
    recorder: TraceRecorder,
    run_id: RunId,
    *,
    allowed_commands: Sequence[str] = ("pytest", "python", "git", "ruff"),
) -> ToolRegistry:
    registry = ToolRegistry(sandbox, recorder, run_id, allowed_commands=allowed_commands)

    async def read(value: BaseModel) -> str:
        item = ReadFileInput.model_validate(value)
        return await sandbox.read_file(PurePosixPath(item.path), item.max_bytes)

    async def list_dir(value: BaseModel) -> str:
        item = PathInput.model_validate(value)
        return "\n".join(await sandbox.list_directory(PurePosixPath(item.path)))

    async def search(value: BaseModel) -> str:
        item = SearchInput.model_validate(value)
        return "\n".join(await sandbox.search(item.query, PurePosixPath(item.path)))

    async def write(value: BaseModel) -> str:
        item = WriteFileInput.model_validate(value)
        await sandbox.write_file(PurePosixPath(item.path), item.content)
        return f"wrote {len(item.content)} characters to {item.path}"

    async def replace(value: BaseModel) -> str:
        item = ReplaceTextInput.model_validate(value)
        path = PurePosixPath(item.path)
        original = await sandbox.read_file(path)
        actual = original.count(item.old)
        if actual != item.expected_replacements:
            raise ToolExecutionError(
                f"expected {item.expected_replacements} matches, found {actual}; file unchanged"
            )
        await sandbox.write_file(path, original.replace(item.old, item.new))
        return f"replaced {actual} occurrence(s) in {item.path}"

    async def command(value: BaseModel) -> str:
        item = RunCommandInput.model_validate(value)
        if item.argv[0] not in registry.allowed_commands:
            raise ToolExecutionError(f"command is not allowlisted: {item.argv[0]}")
        result = await sandbox.execute(item.argv, item.timeout_seconds)
        if result.timed_out:
            raise ToolExecutionError(f"command timed out after {item.timeout_seconds}s")
        return json.dumps(
            {"exit_code": result.exit_code, "stdout": result.stdout, "stderr": result.stderr}
        )

    async def diff(_: BaseModel) -> str:
        return await sandbox.git_diff()

    registrations: tuple[tuple[type[BaseModel], ToolDefinition, ToolHandler], ...] = (
        (
            ReadFileInput,
            ToolDefinition("read_file", "Read a UTF-8 workspace file", _schema(ReadFileInput), 10),
            read,
        ),
        (
            PathInput,
            ToolDefinition("list_directory", "List a workspace directory", _schema(PathInput), 10),
            list_dir,
        ),
        (
            SearchInput,
            ToolDefinition(
                "search_code", "Find literal text in workspace files", _schema(SearchInput), 20
            ),
            search,
        ),
        (
            WriteFileInput,
            ToolDefinition(
                "write_file", "Write a UTF-8 workspace file", _schema(WriteFileInput), 10
            ),
            write,
        ),
        (
            ReplaceTextInput,
            ToolDefinition(
                "replace_text", "Replace an exact occurrence count", _schema(ReplaceTextInput), 10
            ),
            replace,
        ),
        (
            RunCommandInput,
            ToolDefinition(
                "run_command",
                "Run an allowlisted argv command without a shell",
                _schema(RunCommandInput),
                305,
            ),
            command,
        ),
        (
            StrictInput,
            ToolDefinition("git_diff", "Show the current source diff", _schema(StrictInput), 10),
            diff,
        ),
    )
    for model, definition, handler in registrations:
        registry.register(model, definition, handler)
    return registry
