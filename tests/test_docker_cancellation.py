from __future__ import annotations

import asyncio
import sys
import threading
import types
from pathlib import Path
from typing import Any

import pytest

from agentscope.execution.sandbox import docker as docker_module
from agentscope.execution.sandbox.docker import DockerSandbox


class FakeDocker:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.entered = threading.Event()
        self.created = 0
        self.removed = 0
        self.closed = 0
        fake = self

        class Container:
            def remove(self, force: bool = False) -> None:
                fake.removed += 1

            def put_archive(self, *a: Any, **k: Any) -> bool:
                return True

            def exec_run(self, *a: Any, **k: Any) -> Any:
                return types.SimpleNamespace(exit_code=0, output=b"")

        class Containers:
            @staticmethod
            def run(*a: Any, **k: Any) -> Container:
                fake.entered.set()
                fake.release.wait(5)
                fake.created += 1
                return Container()

        class Client:
            containers = Containers()

            def close(self) -> None:
                fake.closed += 1

        self.client = Client()


@pytest.fixture
def fake_docker(monkeypatch: pytest.MonkeyPatch) -> FakeDocker:
    fake = FakeDocker()
    monkeypatch.setitem(sys.modules, "docker", types.SimpleNamespace(from_env=lambda: fake.client))
    return fake


async def test_cancel_during_provisioning_removes_late_container(
    fake_docker: FakeDocker, tmp_path: Path
) -> None:
    (tmp_path / "a.txt").write_text("x")

    async def job() -> None:
        async with DockerSandbox(tmp_path):
            await asyncio.sleep(10)

    task = asyncio.create_task(job())
    await asyncio.to_thread(fake_docker.entered.wait, 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    fake_docker.release.set()  # the docker call finishes only after cancellation
    for _ in range(100):
        if docker_module._BACKGROUND == set() and fake_docker.closed:
            break
        await asyncio.sleep(0.02)
    assert (fake_docker.created, fake_docker.removed, fake_docker.closed) == (1, 1, 1)
