"""Build the static demo data for the GitHub Pages dashboard.

Runs AgentScope's real code on the recorded replay outputs in ``examples/suites/task-cards``:
``SuiteRunner`` + ``write_artifacts`` produce each ``results.json``, then the real suite API
router (``build_suite_router``) is called through FastAPI's test client. Every response body
is saved as a file, so the static demo serves exactly what ``agentscope serve`` would.

Determinism: the only per-run values are the wall-clock start/finish times, which are replaced
with fixed timestamps (the replay has no real timing). No model is called.

    python scripts/build_demo_data.py            # write frontend/demo-data/
    python scripts/build_demo_data.py --check    # exit 1 if the committed data is stale
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from itertools import permutations
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.testclient import TestClient

import agentscope
from agentscope.api.suites import build_suite_router
from agentscope.suites.artifacts import write_artifacts
from agentscope.suites.loader import load_suite
from agentscope.suites.providers import ReplayChatModel
from agentscope.suites.runner import SuiteRunner

ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "examples" / "suites" / "task-cards" / "suite.yaml"
REPLAYS = ("good", "chatty")
DEFAULT_OUT = ROOT / "frontend" / "demo-data"
BASE = "demo/api/v1"
FIXED_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _dump(body: object) -> bytes:
    return (json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def generate(reports_dir: Path) -> dict[str, bytes]:
    """Return ``{relative path: file bytes}`` for every demo response."""
    suite = load_suite(SUITE)
    for index, name in enumerate(REPLAYS):
        chat = ReplayChatModel.from_jsonl(SUITE.parent / f"replay-{name}.outputs.jsonl")
        result = asyncio.run(SuiteRunner(suite, chat, provider="replay", model_name="replay").run())
        start = FIXED_START + timedelta(minutes=index)
        result = dataclasses.replace(
            result, started_at=start, finished_at=start + timedelta(seconds=1)
        )
        write_artifacts(result, reports_dir / f"replay-{name}")

    app = FastAPI()
    app.include_router(build_suite_router(reports_dir))
    client = TestClient(app)

    def get(path: str) -> object:
        response = client.get(f"/api/v1/{path}")
        response.raise_for_status()
        return response.json()

    files: dict[str, bytes] = {
        f"{BASE}/health.json": _dump(
            {"status": "ready", "version": agentscope.__version__, "sandbox": "static-demo"}
        ),
    }
    listing = get("suite-reports")
    files[f"{BASE}/suite-reports.json"] = _dump(listing)
    ids = [row["report_id"] for row in listing]  # type: ignore[index]
    for report_id in ids:
        files[f"{BASE}/suite-reports/{report_id}.json"] = _dump(get(f"suite-reports/{report_id}"))
    for a, b in permutations(sorted(ids), 2):
        query = f"suite-compare?a={quote(a)}&b={quote(b)}"
        files[f"{BASE}/suite-compare/{a}__{b}.json"] = _dump(get(query))
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true", help="fail if --out differs")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        files = generate(Path(tmp))
    out: Path = args.out
    if args.check:
        stale = [
            p
            for p, data in files.items()
            if not (out / p).is_file() or (out / p).read_bytes() != data
        ]
        existing = (
            {str(p.relative_to(out)) for p in (out / BASE).rglob("*.json")}
            if out.is_dir()
            else set()
        )
        stale += sorted(existing - set(files))
        if stale:
            print("Demo data is stale; run scripts/build_demo_data.py:", *stale, sep="\n  ")
            return 1
        print(f"Demo data up to date ({len(files)} files).")
        return 0
    for p in sorted((out / BASE).rglob("*.json")) if (out / BASE).is_dir() else []:
        p.unlink()
    for rel, data in sorted(files.items()):
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    print(f"Wrote {len(files)} files to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
