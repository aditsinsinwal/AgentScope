from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import sys
import time
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Self

from agentscope.domain.errors import SandboxError
from agentscope.execution.sandbox.base import CommandResult, validate_relative_path


class LocalSandbox:
    """Unsafe host-process sandbox for deterministic tests only.

    It provides the same controlled API as Docker but is not a security boundary.
    """

    def __init__(self, repository: Path, hidden_tests: Path | None = None) -> None:
        self._repository = repository.resolve()
        self._hidden_tests = hidden_tests.resolve() if hidden_tests else None
        self._temporary: TemporaryDirectory[str] | None = None
        self.root: Path | None = None

    async def __aenter__(self) -> Self:
        self._temporary = TemporaryDirectory(prefix="agentscope-")
        self.root = Path(self._temporary.name).resolve() / "workspace"
        await asyncio.to_thread(shutil.copytree, self._repository, self.root)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._temporary:
            await asyncio.to_thread(self._temporary.cleanup)
        self.root = None

    def _resolve(self, path: PurePosixPath) -> Path:
        validate_relative_path(path)
        if self.root is None:
            raise SandboxError("sandbox is not running")
        candidate = (self.root / Path(*path.parts)).resolve()
        if not candidate.is_relative_to(self.root.resolve()):
            raise SandboxError(f"path escapes workspace: {path}")
        return candidate

    async def read_file(self, path: PurePosixPath, max_bytes: int = 1_000_000) -> str:
        target = self._resolve(path)
        if target.stat().st_size > max_bytes:
            raise SandboxError(f"file exceeds {max_bytes} byte read limit")
        return await asyncio.to_thread(target.read_text, encoding="utf-8")

    async def write_file(self, path: PurePosixPath, content: str) -> None:
        target = self._resolve(path)
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_text, content, encoding="utf-8")

    async def list_directory(self, path: PurePosixPath) -> Sequence[str]:
        target = self._resolve(path)
        return tuple(
            sorted(item.name + ("/" if item.is_dir() else "") for item in target.iterdir())
        )

    async def search(self, query: str, path: PurePosixPath) -> Sequence[str]:
        root = self._resolve(path)

        def find() -> tuple[str, ...]:
            matches: list[str] = []
            files = [root] if root.is_file() else root.rglob("*")
            for file in files:
                if not file.is_file() or ".git" in file.parts:
                    continue
                try:
                    for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
                        if query in line:
                            assert self.root is not None
                            matches.append(f"{file.relative_to(self.root)}:{number}:{line[:300]}")
                except (UnicodeDecodeError, OSError):
                    continue
            return tuple(matches[:500])

        return await asyncio.to_thread(find)

    async def execute(self, command: tuple[str, ...], timeout_seconds: float) -> CommandResult:
        if self.root is None:
            raise SandboxError("sandbox is not running")
        started = time.monotonic()
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(self.root)}
        executable_command = (sys.executable, *command[1:]) if command[0] == "python" else command
        process = await asyncio.create_subprocess_exec(
            *executable_command,
            cwd=self.root,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout_seconds)
            timed_out = False
        except TimeoutError:
            process.kill()
            stdout, stderr = await process.communicate()
            timed_out = True
        return CommandResult(
            command,
            process.returncode or 0,
            stdout.decode(errors="replace")[-100_000:],
            stderr.decode(errors="replace")[-100_000:],
            time.monotonic() - started,
            timed_out,
        )

    async def git_diff(self) -> str:
        result = await self.execute(("git", "diff", "--no-ext-diff"), 10)
        return result.stdout

    async def snapshot_hashes(self, paths: Sequence[str]) -> dict[str, str]:
        if self.root is None:
            raise SandboxError("sandbox is not running")

        def snapshot() -> dict[str, str]:
            result: dict[str, str] = {}
            assert self.root is not None
            for prefix in paths:
                target = self._resolve(PurePosixPath(prefix.rstrip("/")))
                candidates = target.rglob("*") if target.is_dir() else (target,)
                for candidate in candidates:
                    generated = "__pycache__" in candidate.parts or candidate.suffix in {
                        ".pyc",
                        ".pyo",
                    }
                    if candidate.is_file() and not generated:
                        name = str(candidate.relative_to(self.root.resolve()))
                        result[name] = hashlib.sha256(candidate.read_bytes()).hexdigest()
            return result

        return await asyncio.to_thread(snapshot)

    async def install_hidden_tests(self) -> None:
        if self._hidden_tests is None:
            return
        if self.root is None:
            raise SandboxError("sandbox is not running")
        destination = self.root / ".agentscope_hidden_tests"
        await asyncio.to_thread(shutil.copytree, self._hidden_tests, destination)

    async def export_workspace(self, destination: Path) -> None:
        if self.root is None:
            raise SandboxError("sandbox is not running")
        await asyncio.to_thread(shutil.copytree, self.root, destination)
