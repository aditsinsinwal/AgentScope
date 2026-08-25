from __future__ import annotations

import asyncio
import io
import shutil
import socket
import tarfile
import time
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Self

from agentscope.domain.errors import SandboxError
from agentscope.execution.sandbox.base import CommandResult, validate_relative_path


class DockerSandbox:
    """Ephemeral, network-disabled Docker execution boundary."""

    workspace = "/workspace"

    def __init__(
        self,
        repository: Path,
        hidden_tests: Path | None = None,
        *,
        image: str = "agentscope-sandbox:py312",
        memory: str = "512m",
        nano_cpus: int = 1_000_000_000,
        pids_limit: int = 256,
    ) -> None:
        self.repository = repository.resolve()
        self.hidden_tests = hidden_tests.resolve() if hidden_tests else None
        self.image = image
        self.limits = {"mem_limit": memory, "nano_cpus": nano_cpus, "pids_limit": pids_limit}
        self._client: Any = None
        self._container: Any = None

    async def __aenter__(self) -> Self:
        try:
            import docker

            self._client = await asyncio.to_thread(docker.from_env)
            self._container = await asyncio.to_thread(
                self._client.containers.run,
                self.image,
                ["sleep", "infinity"],
                detach=True,
                network_disabled=True,
                read_only=True,
                tmpfs={
                    self.workspace: "rw,noexec,nosuid,size=256m,uid=65534,gid=65534",
                    "/tmp": "rw,noexec,nosuid,size=64m,uid=65534,gid=65534",
                },
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                user="65534:65534",
                working_dir=self.workspace,
                **self.limits,
            )
            await self._put_tree(self.repository, self.workspace)
            return self
        except Exception as exc:
            await self.__aexit__()
            raise SandboxError(f"failed to provision Docker sandbox: {exc}") from exc

    async def __aexit__(self, *exc_info: object) -> None:
        if self._container is not None:
            try:
                await asyncio.to_thread(self._container.remove, force=True)
            finally:
                self._container = None
        if self._client is not None:
            await asyncio.to_thread(self._client.close)
            self._client = None

    async def _put_tree(self, source: Path, destination: str) -> None:
        if self._container is None:
            raise SandboxError("sandbox is not running")

        def archive() -> bytes:
            buffer = io.BytesIO()

            def normalize(info: tarfile.TarInfo) -> tarfile.TarInfo:
                info.uid = 65534
                info.gid = 65534
                info.uname = "nobody"
                info.gname = "nogroup"
                if info.isfile():
                    info.mode |= 0o600
                elif info.isdir():
                    info.mode |= 0o700
                return info

            with tarfile.open(fileobj=buffer, mode="w") as tar:
                for child in source.iterdir():
                    tar.add(child, arcname=child.name, filter=normalize)
            return buffer.getvalue()

        payload = await asyncio.to_thread(archive)

        def upload() -> None:
            assert self._client is not None
            assert self._container is not None
            created = self._client.api.exec_create(
                self._container.id,
                ["tar", "-x", "-f", "-", "-C", destination],
                stdin=True,
                stdout=True,
                stderr=True,
                user="65534:65534",
            )
            exec_id = str(created["Id"])
            attached = self._client.api.exec_start(exec_id, socket=True)
            raw_socket = attached._sock
            try:
                raw_socket.sendall(payload)
                raw_socket.shutdown(socket.SHUT_WR)
                while raw_socket.recv(65_536):
                    pass
            finally:
                attached.close()
            inspection = self._client.api.exec_inspect(exec_id)
            if inspection.get("ExitCode") != 0:
                raise SandboxError("Docker rejected workspace tar stream")

        await asyncio.to_thread(upload)

    def _path(self, path: PurePosixPath) -> str:
        validate_relative_path(path)
        return f"{self.workspace}/{path.as_posix()}"

    async def _exec(self, command: tuple[str, ...], timeout_seconds: float) -> CommandResult:
        if self._container is None:
            raise SandboxError("sandbox is not running")
        started = time.monotonic()

        def run() -> Any:
            return self._container.exec_run(list(command), workdir=self.workspace, demux=True)

        try:
            response = await asyncio.wait_for(asyncio.to_thread(run), timeout_seconds)
        except TimeoutError as exc:
            # Docker SDK exec cancellation cannot reliably kill only the exec process.
            await self.__aexit__()
            raise SandboxError("command timed out; sandbox destroyed") from exc
        stdout, stderr = response.output
        return CommandResult(
            command,
            int(response.exit_code),
            (stdout or b"").decode(errors="replace")[-100_000:],
            (stderr or b"").decode(errors="replace")[-100_000:],
            time.monotonic() - started,
        )

    async def read_file(self, path: PurePosixPath, max_bytes: int = 1_000_000) -> str:
        result = await self._exec(
            (
                "python",
                "-c",
                "import pathlib,sys;"
                "sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())",
                self._path(path),
            ),
            10,
        )
        if result.exit_code or len(result.stdout.encode()) > max_bytes:
            raise SandboxError(result.stderr or "file read failed or exceeded limit")
        return result.stdout

    async def write_file(self, path: PurePosixPath, content: str) -> None:
        # Content travels over stdin-like base64 argument, never through a shell.
        import base64

        encoded = base64.b64encode(content.encode()).decode()
        result = await self._exec(
            (
                "python",
                "-c",
                "import base64,pathlib,sys;"
                "p=pathlib.Path(sys.argv[1]);"
                "p.parent.mkdir(parents=True,exist_ok=True);"
                "p.write_bytes(base64.b64decode(sys.argv[2]))",
                self._path(path),
                encoded,
            ),
            10,
        )
        if result.exit_code:
            raise SandboxError(result.stderr)

    async def list_directory(self, path: PurePosixPath) -> Sequence[str]:
        result = await self._exec(
            (
                "python",
                "-c",
                "import pathlib,sys;"
                "print('\\n'.join(sorted(x.name+('/' if x.is_dir() else '') "
                "for x in pathlib.Path(sys.argv[1]).iterdir())))",
                self._path(path),
            ),
            10,
        )
        if result.exit_code:
            raise SandboxError(result.stderr)
        return tuple(result.stdout.splitlines())

    async def search(self, query: str, path: PurePosixPath) -> Sequence[str]:
        result = await self._exec(
            ("rg", "--line-number", "--fixed-strings", "--", query, self._path(path)), 20
        )
        if result.exit_code not in (0, 1):
            raise SandboxError(result.stderr)
        return tuple(result.stdout.splitlines()[:500])

    async def execute(self, command: tuple[str, ...], timeout_seconds: float) -> CommandResult:
        return await self._exec(command, timeout_seconds)

    async def git_diff(self) -> str:
        return (await self._exec(("git", "diff", "--no-ext-diff"), 10)).stdout

    async def snapshot_hashes(self, paths: Sequence[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for path in paths:
            command = (
                "python",
                "-c",
                "import hashlib,pathlib,sys\n"
                "r=pathlib.Path(sys.argv[1])\n"
                "for p in sorted(r.rglob('*')):\n"
                " if p.is_file() and '__pycache__' not in p.parts "
                "and p.suffix not in {'.pyc','.pyo'}: "
                "print(str(p),hashlib.sha256(p.read_bytes()).hexdigest())",
                self._path(PurePosixPath(path.rstrip("/"))),
            )
            output = await self._exec(command, 20)
            for line in output.stdout.splitlines():
                name, digest = line.rsplit(" ", 1)
                result[name.removeprefix(self.workspace + "/")] = digest
        return result

    async def install_hidden_tests(self) -> None:
        if self.hidden_tests:
            result = await self._exec(
                (
                    "python",
                    "-c",
                    "import pathlib;pathlib.Path('.agentscope_hidden_tests').mkdir()",
                ),
                10,
            )
            if result.exit_code:
                raise SandboxError(result.stderr)
            await self._put_tree(self.hidden_tests, f"{self.workspace}/.agentscope_hidden_tests")

    async def export_workspace(self, destination: Path) -> None:
        if self._container is None:
            raise SandboxError("sandbox is not running")

        def export() -> None:
            response = self._container.exec_run(
                ["tar", "-c", "-f", "-", "."],
                workdir=self.workspace,
                demux=False,
            )
            if response.exit_code != 0:
                raise SandboxError("failed to freeze Docker workspace")
            buffer = io.BytesIO(response.output)
            staging = destination.parent / f".{destination.name}-archive"
            staging.mkdir(parents=True)
            try:
                with tarfile.open(fileobj=buffer, mode="r:*") as archive:
                    # The data filter rejects traversal, devices, and escaping links from
                    # the untrusted agent workspace before anything reaches the host.
                    archive.extractall(staging, filter="data")
                shutil.copytree(staging, destination, symlinks=True)
            finally:
                shutil.rmtree(staging, ignore_errors=True)

        await asyncio.to_thread(export)
