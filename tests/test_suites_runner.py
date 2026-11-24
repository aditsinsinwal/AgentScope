import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from agentscope.domain.errors import SuiteComparisonError, SuiteDefinitionError
from agentscope.domain.models import RunId
from agentscope.suites.artifacts import (
    load_results,
    prepare_out_dir,
    report_markdown,
    write_artifacts,
)
from agentscope.suites.compare import compare_results
from agentscope.suites.loader import load_suite
from agentscope.suites.providers import (
    ChatCompletion,
    ChatMessage,
    OpenAICompatibleChatModel,
    ReplayChatModel,
)
from agentscope.suites.results import nearest_rank
from agentscope.suites.runner import SuiteRunner, SuiteTraceWriter

ROOT = Path(__file__).parents[1]
EXAMPLE_DIR = ROOT / "examples/suites/task-cards"
SUITE = EXAMPLE_DIR / "suite.yaml"


def replay(name: str) -> ReplayChatModel:
    return ReplayChatModel.from_jsonl(EXAMPLE_DIR / f"replay-{name}.outputs.jsonl")


async def run_replay(name: str, out: Path, **kwargs: Any) -> Any:
    suite = load_suite(SUITE)
    trace = SuiteTraceWriter(out / "trace.jsonl", RunId("run_test"))
    runner = SuiteRunner(
        suite, replay(name), provider="replay", model_name="replay", trace=trace, **kwargs
    )
    try:
        result = await runner.run()
    finally:
        trace.close()
    return result


def test_nearest_rank() -> None:
    assert nearest_rank([], 50) is None
    assert nearest_rank([5.0], 95) == 5.0
    values = [float(v) for v in range(1, 11)]
    assert nearest_rank(values, 50) == 5.0
    assert nearest_rank(values, 95) == 10.0
    assert nearest_rank(list(reversed(values)), 10) == 1.0


async def test_replay_end_to_end_artifacts(tmp_path: Path) -> None:
    result = await run_replay("good", tmp_path)
    doc = write_artifacts(result, tmp_path)
    assert result.source == "replay" and doc.run.source == "replay"
    assert (doc.aggregate.n, doc.aggregate.n_failed) == (8, 0)
    assert doc.aggregate.format_valid_rate == 1.0
    assert doc.aggregate.pass_rate == pytest.approx(6 / 8)
    assert doc.aggregate.field_accuracy["PRIORITY"] == pytest.approx(7 / 8)
    assert doc.aggregate.latency_ms.p50 is None and doc.aggregate.tokens.prompt is None
    lines = (tmp_path / "outputs.jsonl").read_text(encoding="utf-8").splitlines()
    suite_ids = [case.id for case in load_suite(SUITE).cases]
    assert [json.loads(line)["id"] for line in lines] == suite_ids
    assert all(list(json.loads(line)) == ["id", "output"] for line in lines)
    assert json.loads(lines[0])["output"].startswith("TASK: Renew")
    saved = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert saved["schema_version"] == 1 and saved["run"]["source"] == "replay"
    assert load_results(tmp_path / "results.json") == doc
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "deterministic checks only" in report.lower()
    assert "not a human preference judgement" in report
    assert "replayed from a file" in report


async def test_trace_modes(tmp_path: Path) -> None:
    await run_replay("good", tmp_path / "text")
    await run_replay("good", tmp_path / "hash", trace_text=False)
    text = (tmp_path / "text/trace.jsonl").read_text(encoding="utf-8")
    hashed = (tmp_path / "hash/trace.jsonl").read_text(encoding="utf-8")
    assert "Renew the lab licence" in text
    assert "Renew the lab licence" not in hashed and "sha256=" in hashed
    events = [json.loads(line) for line in text.splitlines()]
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    assert events[0]["name"] == "suite_started" and events[-1]["name"] == "suite_finished"
    assert sum(e["event_type"] == "model_call" for e in events) == 8


def transport(fail_ids: set[str] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        prompt = body["messages"][-1]["content"]
        if fail_ids and any(marker in prompt for marker in fail_ids):
            return httpx.Response(400, text="rejected")
        return httpx.Response(
            200,
            json={
                "model": "mock-1",
                "choices": [
                    {
                        "message": {
                            "content": "TASK: x\nOWNER: y\nDUE: z\nPRIORITY: High\nNOTE: n"
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    return httpx.MockTransport(handler)


def network_model(fail_ids: set[str] | None = None) -> OpenAICompatibleChatModel:
    async def no_sleep(_: float) -> None:
        return None

    return OpenAICompatibleChatModel(
        "http://127.0.0.1:1/v1",
        "mock",
        client=httpx.AsyncClient(transport=transport(fail_ids)),
        sleep=no_sleep,
    )


async def test_mock_openai_model_run_with_tokens_and_latency(tmp_path: Path) -> None:
    suite = load_suite(SUITE)
    runner = SuiteRunner(
        suite,
        network_model(),
        provider="openai-compatible",
        model_name="mock",
        base_url_host="127.0.0.1:1",
        concurrency=4,
    )
    result = await runner.run()
    doc = write_artifacts(result, tmp_path)
    assert doc.run.source == "generated" and doc.run.base_url_host == "127.0.0.1:1"
    assert doc.aggregate.tokens.prompt == 80 and doc.aggregate.tokens.completion == 40
    assert doc.aggregate.latency_ms.p50 is not None and doc.aggregate.latency_ms.n == 8
    assert doc.aggregate.format_valid_rate == 1.0
    assert [o.case_id for o in result.outcomes] == [c.id for c in suite.cases]  # case order


async def test_failed_case_is_reported_and_excluded(tmp_path: Path) -> None:
    suite = load_suite(SUITE)
    runner = SuiteRunner(
        suite, network_model({"Tomas"}), provider="openai-compatible", model_name="mock"
    )
    result = await runner.run()
    doc = write_artifacts(result, tmp_path)
    assert result.n_failed == 1 and doc.aggregate.n_failed == 1 and doc.aggregate.n_scored == 7
    ids = [json.loads(line)["id"] for line in (tmp_path / "outputs.jsonl").read_text().splitlines()]
    assert "t02" not in ids and len(ids) == 7
    failed = next(c for c in doc.cases if c.id == "t02")
    assert failed.status == "error" and failed.check is None and "HTTP 400" in (failed.error or "")
    assert "Failed cases" in report_markdown(doc)


class SlowModel:
    async def complete(self, messages: list[ChatMessage], params: Any) -> ChatCompletion:
        await asyncio.sleep(5)
        return ChatCompletion("never", "slow")


async def test_per_case_timeout_records_error() -> None:
    suite = load_suite(SUITE)
    runner = SuiteRunner(
        suite,
        SlowModel(),
        provider="x",
        model_name="slow",
        case_timeout_seconds=0.01,
        concurrency=8,
    )
    result = await runner.run()
    assert result.n_failed == 8
    assert all("TimeoutError" in (o.error or "") for o in result.outcomes)


async def test_cancellation_is_clean() -> None:
    suite = load_suite(SUITE)
    runner = SuiteRunner(suite, SlowModel(), provider="x", model_name="slow", concurrency=2)
    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


class RecordingModel:
    def __init__(self) -> None:
        self.active = 0
        self.peak = 0

    async def complete(self, messages: list[ChatMessage], params: Any) -> ChatCompletion:
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.005)
        self.active -= 1
        return ChatCompletion(messages[-1].content, "rec")


async def test_concurrency_is_bounded_and_system_prompt_sent() -> None:
    suite = load_suite(SUITE)
    for limit in (1, 3):
        model = RecordingModel()
        await SuiteRunner(suite, model, provider="x", model_name="rec", concurrency=limit).run()
        assert model.peak == limit


async def test_secrets_are_redacted_in_trace(tmp_path: Path) -> None:
    class Leaky:
        async def complete(self, messages: list[ChatMessage], params: Any) -> ChatCompletion:
            raise RuntimeError("boom sk-SECRET")

    suite = load_suite(SUITE)
    trace = SuiteTraceWriter(tmp_path / "trace.jsonl", RunId("run_test"))
    result = await SuiteRunner(
        suite, Leaky(), provider="x", model_name="m", trace=trace, secrets=("sk-SECRET",)
    ).run()
    trace.close()
    assert "sk-SECRET" not in (tmp_path / "trace.jsonl").read_text()
    assert all("sk-SECRET" not in (o.error or "") for o in result.outcomes)


async def test_unused_replay_ids_reported(tmp_path: Path) -> None:
    extra = tmp_path / "o.jsonl"
    extra.write_text(
        (EXAMPLE_DIR / "replay-good.outputs.jsonl").read_text() + '{"id":"zz","output":"x"}\n'
    )
    result = await SuiteRunner(
        load_suite(SUITE), ReplayChatModel.from_jsonl(extra), provider="replay", model_name="r"
    ).run()
    assert write_artifacts(result, tmp_path / "out").run.replay_unused_ids == ["zz"]


def test_prepare_out_dir_refuses_mixing(tmp_path: Path) -> None:
    prepare_out_dir(tmp_path, overwrite=False)
    (tmp_path / "trace.jsonl").write_text("old")
    with pytest.raises(SuiteDefinitionError, match="already contains"):
        prepare_out_dir(tmp_path, overwrite=False)
    prepare_out_dir(tmp_path, overwrite=True)
    assert not (tmp_path / "trace.jsonl").exists()


async def test_compare(tmp_path: Path) -> None:
    good = write_artifacts(await run_replay("good", tmp_path / "g"), tmp_path / "g")
    chatty = write_artifacts(await run_replay("chatty", tmp_path / "c"), tmp_path / "c")
    cmp = compare_results(chatty, good)
    assert cmp.fingerprint_match and cmp.n_paired == 8 and cmp.n_unpaired == 0
    assert cmp.b_better + cmp.tie + cmp.a_better == 8
    # chatty and good outputs differ mostly in format, not in per-field content score
    assert (cmp.format_valid_b_only, cmp.format_valid_a_only) == (6, 0)
    assert cmp.passed_b_only >= 1 and cmp.passed_a_only == 0
    assert cmp.format_valid_rate_delta == pytest.approx(0.75)
    assert cmp.field_accuracy_delta["PRIORITY"] == pytest.approx(7 / 8 - 6 / 8)
    assert any("replay" in w for w in cmp.warnings)
    reverse = compare_results(good, chatty)
    assert (reverse.a_better, reverse.b_better) == (cmp.b_better, cmp.a_better)
    assert compare_results(good, good).tie == 8


async def test_compare_fingerprint_mismatch(tmp_path: Path) -> None:
    good = write_artifacts(await run_replay("good", tmp_path / "g"), tmp_path / "g")
    other = good.model_copy(deep=True)
    other.suite.fingerprint = "0" * 64
    with pytest.raises(SuiteComparisonError, match="--allow-mismatch"):
        compare_results(good, other)
    cmp = compare_results(good, other, allow_mismatch=True)
    assert not cmp.fingerprint_match and any("fingerprints differ" in w for w in cmp.warnings)


async def test_compare_with_failed_cases_counts_unpaired(tmp_path: Path) -> None:
    good = write_artifacts(await run_replay("good", tmp_path / "g"), tmp_path / "g")
    failed = write_artifacts(
        await SuiteRunner(
            load_suite(SUITE), network_model({"Tomas"}), provider="p", model_name="m"
        ).run(),
        tmp_path / "f",
    )
    cmp = compare_results(good, failed)
    assert cmp.n_unpaired == 1 and cmp.n_paired == 7
