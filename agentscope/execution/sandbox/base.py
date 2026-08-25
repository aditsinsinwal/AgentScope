from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, Self


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False


class Sandbox(Protocol):
    async def __aenter__(self) -> Self: ...

    async def __aexit__(self, *exc_info: object) -> None: ...

    async def read_file(self, path: PurePosixPath, max_bytes: int = 1_000_000) -> str: ...

    async def write_file(self, path: PurePosixPath, content: str) -> None: ...

    async def list_directory(self, path: PurePosixPath) -> Sequence[str]: ...

    async def search(self, query: str, path: PurePosixPath) -> Sequence[str]: ...

    async def execute(self, command: tuple[str, ...], timeout_seconds: float) -> CommandResult: ...

    async def git_diff(self) -> str: ...

    async def snapshot_hashes(self, paths: Sequence[str]) -> dict[str, str]: ...

    async def export_workspace(self, destination: Path) -> None: ...

    async def install_hidden_tests(self) -> None: ...


def validate_relative_path(path: PurePosixPath) -> PurePosixPath:
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe sandbox path: {path}")
    return path
