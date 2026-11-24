"""`agentscope suite ...` commands."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
from pathlib import Path
from typing import Annotated

import typer

from agentscope.config import get_settings
from agentscope.domain.errors import AgentScopeError
from agentscope.domain.models import RunId
from agentscope.suites.artifacts import (
    load_results,
    prepare_out_dir,
    write_artifacts,
)
from agentscope.suites.compare import compare_results
from agentscope.suites.loader import DEFAULT_MAX_CASES, load_suite
from agentscope.suites.providers import (
    PROVIDERS,
    CaseAwareChatModel,
    ChatModel,
    ReplayChatModel,
    build_chat_model,
    url_host,
)
from agentscope.suites.runner import SuiteRunner, SuiteTraceWriter

suite_app = typer.Typer(no_args_is_help=True, help="Run deterministic prompt-suite evaluations.")


def _fail(exc: Exception) -> typer.Exit:
    typer.echo(f"error: {exc}", err=True)
    return typer.Exit(2)


@suite_app.command()
def validate(
    suite_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    max_cases: Annotated[int, typer.Option("--max-cases", min=1)] = DEFAULT_MAX_CASES,
) -> None:
    """Validate a suite definition and print its fingerprint."""
    try:
        suite = load_suite(suite_path, max_cases=max_cases)
    except AgentScopeError as exc:
        raise _fail(exc) from exc
    typer.echo(f"OK: {suite.id} v{suite.version} ({suite.checker.type} checker)")
    typer.echo(f"Cases: {len(suite.cases)}")
    typer.echo(f"Fingerprint: {suite.fingerprint}")


@suite_app.command()
def run(
    suite_path: Annotated[Path, typer.Option("--suite", exists=True, dir_okay=False)],
    provider: Annotated[str, typer.Option("--provider", help=" | ".join(PROVIDERS))],
    model: Annotated[str | None, typer.Option("--model")] = None,
    base_url: Annotated[str | None, typer.Option("--base-url")] = None,
    replay_outputs: Annotated[
        Path | None, typer.Option("--replay-outputs", exists=True, dir_okay=False)
    ] = None,
    local_only: Annotated[
        bool,
        typer.Option("--local-only", help="Require a loopback endpoint (always on for presets)."),
    ] = False,
    api_key_env: Annotated[
        str | None, typer.Option("--api-key-env", help="Name of the env var holding an API key.")
    ] = None,
    concurrency: Annotated[int, typer.Option("--concurrency", min=1, max=64)] = 1,
    case_timeout: Annotated[
        float,
        typer.Option(
            "--case-timeout",
            min=0.1,
            help="Total seconds per case, covering all retry attempts and backoff.",
        ),
    ] = 120.0,
    request_timeout: Annotated[
        float | None,
        typer.Option(
            "--request-timeout",
            min=0.1,
            help="Seconds per HTTP attempt; must be below --case-timeout "
            "(default: min(60, case-timeout / 2)).",
        ),
    ] = None,
    max_cases: Annotated[int, typer.Option("--max-cases", min=1)] = DEFAULT_MAX_CASES,
    out: Annotated[Path | None, typer.Option("--out")] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
    no_trace_text: Annotated[
        bool,
        typer.Option("--no-trace-text", help="Trace lengths and hashes, not prompt/output text."),
    ] = False,
) -> None:
    """Run a prompt suite and write outputs.jsonl, results.json, trace.jsonl and report.md."""
    if provider not in PROVIDERS:
        raise typer.BadParameter(f"provider must be one of: {', '.join(PROVIDERS)}")
    try:
        suite = load_suite(suite_path, max_cases=max_cases)
        chat: ChatModel | CaseAwareChatModel
        secrets: tuple[str, ...] = ()
        host: str | None = None
        if provider == "replay":
            if replay_outputs is None:
                raise typer.BadParameter("--replay-outputs is required with --provider replay")
            chat = ReplayChatModel.from_jsonl(replay_outputs)
            model_name = model or "replay"
        else:
            if not model:
                raise typer.BadParameter("--model is required for network providers")
            per_request = (
                request_timeout if request_timeout is not None else min(60.0, case_timeout / 2)
            )
            if per_request >= case_timeout:
                raise typer.BadParameter("--request-timeout must be smaller than --case-timeout")
            network = build_chat_model(
                provider,
                model,
                base_url=base_url,
                local_only=local_only,
                api_key_env=api_key_env,
                request_timeout_seconds=per_request,
            )
            chat, secrets, model_name, host = (
                network,
                network.secrets,
                model,
                url_host(network.base_url),
            )
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", model_name).strip("-") or "model"
        out_dir = out or get_settings().reports_dir / f"{suite.id}-{provider}-{slug}"
        prepare_out_dir(out_dir, overwrite=overwrite)
    except AgentScopeError as exc:
        raise _fail(exc) from exc

    trace = SuiteTraceWriter(out_dir / "trace.jsonl", RunId(f"run_{_new_id()}"))
    runner = SuiteRunner(
        suite,
        chat,
        provider=provider,
        model_name=model_name,
        base_url_host=host,
        concurrency=concurrency,
        case_timeout_seconds=case_timeout,
        trace=trace,
        trace_text=not no_trace_text,
        secrets=secrets,
    )
    try:
        result = asyncio.run(runner.run())
    finally:
        trace.close()
    doc = write_artifacts(result, out_dir)
    agg = doc.aggregate
    typer.echo(f"Suite: {suite.id} v{suite.version}  fingerprint {suite.fingerprint[:12]}")
    typer.echo(f"Source: {doc.run.source}  Model: {model_name}")
    typer.echo(f"Cases: {agg.n} ({agg.n_scored} scored, {agg.n_failed} failed)")
    typer.echo(f"Format valid: {_pct(agg.format_valid_rate)}  Passed: {_pct(agg.pass_rate)}")
    mean = "n/a" if agg.mean_score is None else f"{agg.mean_score:.3f}"
    typer.echo(f"Mean content score (field matches; ignores format): {mean}")
    for name, acc in agg.field_accuracy.items():
        typer.echo(f"  {name}: {_pct(acc)}")
    typer.echo("Deterministic checks only; not a human preference judgement.")
    typer.echo(f"Artifacts: {out_dir}")
    if result.n_failed:
        typer.echo(
            f"FAILED: {result.n_failed} case(s) produced no output; outputs.jsonl is incomplete.",
            err=True,
        )
        raise typer.Exit(1)


def _new_id() -> str:
    from uuid import uuid4

    return uuid4().hex


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


@suite_app.command()
def compare(
    a_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    b_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    as_json: Annotated[bool, typer.Option("--json")] = False,
    allow_mismatch: Annotated[bool, typer.Option("--allow-mismatch")] = False,
) -> None:
    """Compare two results.json files from the same suite (paired, counts only)."""
    try:
        comparison = compare_results(
            load_results(a_path), load_results(b_path), allow_mismatch=allow_mismatch
        )
    except AgentScopeError as exc:
        raise _fail(exc) from exc
    if as_json:
        typer.echo(json.dumps(dataclasses.asdict(comparison), indent=2))
        return
    for warning in comparison.warnings:
        typer.echo(f"warning: {warning}", err=True)
    typer.echo(f"Suite: {comparison.suite_id}")
    typer.echo(
        f"Paired cases: {comparison.n_paired} (unpaired: {comparison.n_unpaired}); "
        f"B better: {comparison.b_better}, tie: {comparison.tie}, A better: {comparison.a_better}"
    )
    typer.echo(
        f"Format valid only in B: {comparison.format_valid_b_only}, "
        f"only in A: {comparison.format_valid_a_only}; "
        f"passed only in B: {comparison.passed_b_only}, only in A: {comparison.passed_a_only}"
    )
    typer.echo(f"Format valid rate delta (B - A): {_delta(comparison.format_valid_rate_delta)}")
    typer.echo(f"Pass rate delta (B - A): {_delta(comparison.pass_rate_delta)}")
    mean_delta = _delta(comparison.mean_score_delta, scale=1)
    typer.echo(f"Mean content score delta (field matches; ignores format) (B - A): {mean_delta}")
    for name, value in comparison.field_accuracy_delta.items():
        typer.echo(f"  {name} accuracy delta: {_delta(value)}")
    typer.echo("Counts only; no significance is claimed. Not a human preference judgement.")


def _delta(value: float | None, scale: int = 100) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:+.1f} pp" if scale == 100 else f"{value:+.3f}"
