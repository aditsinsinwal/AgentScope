"""The committed static-demo data must match what the real code generates."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_demo_data.py"


@pytest.fixture(scope="module")
def demo():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("build_demo_data", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_demo_data"] = module
    spec.loader.exec_module(module)
    return module


def test_generation_is_deterministic(demo, tmp_path):  # type: ignore[no-untyped-def]
    first = demo.generate(tmp_path / "a")
    second = demo.generate(tmp_path / "b")
    assert first == second
    assert "demo/api/v1/suite-compare/replay-chatty__replay-good.json" in first


def test_committed_demo_data_is_current(demo):  # type: ignore[no-untyped-def]
    assert demo.main(["--check"]) == 0
