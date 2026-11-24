"""Turn a SuiteRunResult into results.json, outputs.jsonl and report.md."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from agentscope.domain.errors import SuiteDefinitionError
from agentscope.suites.results import (
    RESULTS_NOTE,
    SCHEMA_VERSION,
    Aggregate,
    CaseResultDoc,
    CheckResult,
    FieldResult,
    Percentiles,
    ResultsDocument,
    RunInfo,
    SuiteInfo,
    TokenTotals,
    nearest_rank,
)
from agentscope.suites.runner import CaseOutcome, SuiteRunResult

ARTIFACT_NAMES = ("outputs.jsonl", "results.json", "trace.jsonl", "report.md")


def _case_doc(outcome: CaseOutcome) -> CaseResultDoc:
    if not outcome.ok or outcome.check is None or outcome.completion is None:
        return CaseResultDoc(id=outcome.case_id, status="error", error=outcome.error)
    check = outcome.check
    completion = outcome.completion
    text = outcome.output or ""
    return CaseResultDoc(
        id=outcome.case_id,
        status="ok",
        check=CheckResult(
            passed=check.passed,
            score=check.score,
            format_valid=check.format_valid,
            fields=(
                {
                    name: FieldResult(present=f.present, valid=f.valid, matched=f.matched)
                    for name, f in check.fields.items()
                }
                if check.fields is not None
                else None
            ),
            detail=check.detail,
        ),
        output_chars=len(text),
        output_sha256=hashlib.sha256(text.encode()).hexdigest(),
        latency_ms=completion.latency_ms,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
        finish_reason=completion.finish_reason,
    )


def build_aggregate(cases: list[CaseResultDoc], field_names: tuple[str, ...]) -> Aggregate:
    """Rates are over scored (successful) cases; failed cases are counted in n_failed."""
    scored = [c for c in cases if c.status == "ok" and c.check is not None]
    n = len(scored)

    def rate(values: list[bool]) -> float | None:
        return sum(values) / len(values) if values else None

    accuracy: dict[str, float | None] = {}
    for name in field_names:
        hits = [
            bool(c.check.fields[name].matched)
            for c in scored
            if c.check
            and c.check.fields
            and name in c.check.fields
            and c.check.fields[name].matched is not None
        ]
        accuracy[name] = rate(hits)
    latencies = [c.latency_ms for c in scored if c.latency_ms is not None]
    both = [c for c in scored if c.prompt_tokens is not None and c.completion_tokens is not None]
    complete_tokens = n > 0 and len(both) == n
    return Aggregate(
        n=len(cases),
        n_failed=len(cases) - n,
        n_scored=n,
        format_valid_rate=rate([bool(c.check and c.check.format_valid) for c in scored]),
        pass_rate=rate([bool(c.check and c.check.passed) for c in scored]),
        mean_score=(sum(c.check.score for c in scored if c.check) / n) if n else None,
        field_accuracy=accuracy,
        latency_ms=Percentiles(
            p50=nearest_rank(latencies, 50), p95=nearest_rank(latencies, 95), n=len(latencies)
        ),
        tokens=TokenTotals(
            prompt=sum(c.prompt_tokens or 0 for c in both) if complete_tokens else None,
            completion=sum(c.completion_tokens or 0 for c in both) if complete_tokens else None,
            cases_reporting=len(both),
        ),
    )


def build_results(result: SuiteRunResult) -> ResultsDocument:
    suite = result.suite
    cases = [_case_doc(outcome) for outcome in result.outcomes]
    field_names = suite.checker.fields if suite.checker.type == "field_lines" else ()
    return ResultsDocument(
        schema_version=SCHEMA_VERSION,
        suite=SuiteInfo(
            id=suite.id,
            name=suite.name,
            version=suite.version,
            fingerprint=suite.fingerprint,
            checker=suite.checker,
            n_cases=len(suite.cases),
        ),
        run=RunInfo(
            source=result.source,
            provider=result.provider,
            model=result.model,
            base_url_host=result.base_url_host,
            params=suite.generation,
            concurrency=result.concurrency,
            case_timeout_seconds=result.case_timeout_seconds,
            trace_text=result.trace_text,
            started_at=result.started_at.isoformat(),
            finished_at=result.finished_at.isoformat(),
            replay_unused_ids=(
                list(result.replay_unused_ids) if result.replay_unused_ids is not None else None
            ),
        ),
        cases=cases,
        aggregate=build_aggregate(cases, field_names),
    )


def outputs_jsonl(result: SuiteRunResult) -> str:
    """Exactly `{"id", "output"}` per successful case, in suite case order."""
    lines = [
        json.dumps({"id": o.case_id, "output": o.output}, ensure_ascii=False)
        for o in result.outcomes
        if o.ok
    ]
    return "".join(line + "\n" for line in lines)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _int(value: int | None) -> str:
    return "n/a" if value is None else str(value)


def _num(value: float | None, unit: str = "") -> str:
    return "n/a" if value is None else f"{value:.1f}{unit}"


def report_markdown(doc: ResultsDocument) -> str:
    agg = doc.aggregate
    run = doc.run
    lines = [
        f"# Prompt suite report: {doc.suite.name}",
        "",
        f"> {RESULTS_NOTE}",
        "",
        f"- Suite: `{doc.suite.id}` v{doc.suite.version} "
        f"(fingerprint `{doc.suite.fingerprint[:12]}`)",
        f"- Model: `{run.model}` via `{run.provider}`"
        + (f" at `{run.base_url_host}`" if run.base_url_host else ""),
        f"- Source: **{run.source}**"
        + (" (outputs were replayed from a file, not generated)" if run.source == "replay" else ""),
        f"- Cases: {agg.n} total, {agg.n_scored} scored, {agg.n_failed} failed",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Format valid | {_pct(agg.format_valid_rate)} |",
        f"| Passed | {_pct(agg.pass_rate)} |",
        f"| Mean score | {_num(agg.mean_score)} |",
        f"| Latency p50 / p95 (nearest-rank) | {_num(agg.latency_ms.p50, ' ms')} / "
        f"{_num(agg.latency_ms.p95, ' ms')} |",
        f"| Tokens prompt / completion | {_int(agg.tokens.prompt)} / "
        f"{_int(agg.tokens.completion)} |",
    ]
    if agg.field_accuracy:
        lines += ["", "| Field | Accuracy vs reference |", "|---|---|"]
        lines += [f"| {name} | {_pct(acc)} |" for name, acc in agg.field_accuracy.items()]
    failed = [c for c in doc.cases if c.status == "error"]
    if failed:
        lines += ["", "## Failed cases (no output produced)", ""]
        lines += [f"- `{c.id}`: {c.error}" for c in failed]
        lines += [
            "",
            "outputs.jsonl omits these ids; a downstream tool that needs every id will reject it.",
        ]
    bad = [c for c in doc.cases if c.check is not None and not c.check.passed]
    if bad:
        lines += ["", "## Cases that did not pass", "", "| Case | Score | Format valid | Detail |"]
        lines += ["|---|---|---|---|"]
        lines += [
            f"| `{c.id}` | {c.check.score:.2f} | {c.check.format_valid} | {c.check.detail} |"
            for c in bad
            if c.check
        ]
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(content, encoding="utf-8")
    os.replace(temp, path)


def prepare_out_dir(out_dir: Path, *, overwrite: bool) -> None:
    """Create out_dir; refuse to mix runs unless overwrite (which clears old artifacts)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = [name for name in ARTIFACT_NAMES if (out_dir / name).exists()]
    if existing and not overwrite:
        raise SuiteDefinitionError(
            f"{out_dir} already contains {', '.join(existing)}; use --overwrite or a new --out"
        )
    for name in existing:
        (out_dir / name).unlink()


def write_artifacts(result: SuiteRunResult, out_dir: Path) -> ResultsDocument:
    """Write outputs.jsonl, results.json and report.md (trace.jsonl is written live)."""
    doc = build_results(result)
    out_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(out_dir / "outputs.jsonl", outputs_jsonl(result))
    _atomic_write(out_dir / "results.json", doc.model_dump_json(indent=2) + "\n")
    _atomic_write(out_dir / "report.md", report_markdown(doc))
    return doc


def load_results(path: Path) -> ResultsDocument:
    try:
        return ResultsDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SuiteDefinitionError(f"cannot read results {path}: {exc}") from exc
