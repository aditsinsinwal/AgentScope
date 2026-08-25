from __future__ import annotations

import hashlib
import shlex
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentscope.domain.errors import TaskDefinitionError
from agentscope.domain.models import EvaluationTask, TaskId


class TaskDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=200)
    repository: str
    description: str = Field(min_length=1)
    public_test_command: str | tuple[str, ...]
    hidden_test_command: str | tuple[str, ...]
    hidden_tests: str | None = None
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    forbidden_paths: tuple[str, ...] = ("tests/",)
    version: str = "1"


def _command(value: str | tuple[str, ...]) -> tuple[str, ...]:
    command = tuple(shlex.split(value)) if isinstance(value, str) else value
    if not command or any(token in {";", "&&", "||", "|", ">", "<"} for token in command):
        raise TaskDefinitionError("test commands must be non-shell argv commands")
    return command


def _child(base: Path, value: str) -> Path:
    candidate = (base / value).resolve()
    if not candidate.is_relative_to(base.resolve()):
        raise TaskDefinitionError(f"task path escapes its definition directory: {value}")
    return candidate


def load_task(path: Path) -> EvaluationTask:
    path = path.resolve()
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        document = TaskDocument.model_validate(raw)
        repository = _child(path.parent, document.repository)
        hidden = _child(path.parent, document.hidden_tests) if document.hidden_tests else None
        if not repository.is_dir():
            raise TaskDefinitionError(f"repository does not exist: {repository}")
        if hidden is not None and not hidden.is_dir():
            raise TaskDefinitionError(f"hidden test directory does not exist: {hidden}")
        return EvaluationTask(
            TaskId(document.id),
            document.name,
            repository,
            document.description,
            _command(document.public_test_command),
            _command(document.hidden_test_command),
            hidden,
            document.timeout_seconds,
            document.forbidden_paths,
            document.version,
        )
    except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
        if isinstance(exc, TaskDefinitionError):
            raise
        raise TaskDefinitionError(f"invalid task definition {path}: {exc}") from exc


def task_fingerprint(task: EvaluationTask) -> str:
    digest = hashlib.sha256()
    digest.update(task.id.encode())
    digest.update(task.version.encode())
    digest.update(task.description.encode())
    for file in sorted(task.repository.rglob("*")):
        if file.is_file() and ".git" not in file.parts:
            digest.update(str(file.relative_to(task.repository)).encode())
            digest.update(file.read_bytes())
    if task.hidden_tests:
        for file in sorted(task.hidden_tests.rglob("*")):
            if file.is_file():
                digest.update(str(file.relative_to(task.hidden_tests)).encode())
                digest.update(file.read_bytes())
    return digest.hexdigest()
