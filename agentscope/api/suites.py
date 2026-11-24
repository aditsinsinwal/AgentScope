"""Read-only API over suite report directories (``<reports_dir>/<report_id>/results.json``).

Path safety: ids must match a strict pattern (no separators or leading dots), the directory and
file must not be symlinks, the resolved file must stay inside the resolved reports directory,
and files over ``MAX_RESULTS_BYTES`` are refused. Nothing is ever written.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from agentscope.api.middleware import error_envelope
from agentscope.suites.compare import compare_results
from agentscope.suites.results import SCHEMA_VERSION, ResultsDocument

logger = logging.getLogger("agentscope.api.suites")

REPORT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
MAX_RESULTS_BYTES = 8 * 1024 * 1024
MAX_REPORTS = 500
RESULTS_FILE = "results.json"


class ReportError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _load(root: Path, report_id: str) -> ResultsDocument:
    if not REPORT_ID.fullmatch(report_id):
        raise ReportError(400, "invalid_report_id", "report id contains unsupported characters")
    directory = root / report_id
    path = directory / RESULTS_FILE
    try:
        if directory.is_symlink() or path.is_symlink():
            raise ReportError(404, "not_found", "report not found")
        resolved_root = root.resolve()
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
            raise ReportError(404, "not_found", "report not found")
        if resolved.stat().st_size > MAX_RESULTS_BYTES:
            raise ReportError(422, "report_too_large", f"{RESULTS_FILE} exceeds the size limit")
        with resolved.open("rb") as handle:
            raw = handle.read(MAX_RESULTS_BYTES + 1)
    except (FileNotFoundError, NotADirectoryError):
        raise ReportError(404, "not_found", "report not found") from None
    except OSError:
        raise ReportError(404, "not_found", "report not found") from None
    if len(raw) > MAX_RESULTS_BYTES:
        raise ReportError(422, "report_too_large", f"{RESULTS_FILE} exceeds the size limit")
    try:
        doc = ResultsDocument.model_validate_json(raw)
    except ValidationError:
        raise ReportError(
            422, "invalid_report", f"{RESULTS_FILE} failed schema validation"
        ) from None
    if doc.schema_version != SCHEMA_VERSION:
        raise ReportError(
            422, "invalid_report", f"unsupported results schema_version {doc.schema_version}"
        )
    return doc


def _summary(report_id: str, doc: ResultsDocument) -> dict[str, Any]:
    return {
        "report_id": report_id,
        "suite_id": doc.suite.id,
        "suite_name": doc.suite.name,
        "suite_version": doc.suite.version,
        "model": doc.run.model,
        "provider": doc.run.provider,
        "source": doc.run.source,
        "n": doc.aggregate.n,
        "n_failed": doc.aggregate.n_failed,
        "pass_rate": doc.aggregate.pass_rate,
        "format_valid_rate": doc.aggregate.format_valid_rate,
        "finished_at": doc.run.finished_at,
    }


def build_suite_router(reports_dir: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v1/suite-reports", tags=["suite-reports"])

    def fail(request: Request, exc: ReportError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=exc.status,
            content=error_envelope(
                exc.code, exc.message, request_id if isinstance(request_id, str) else None
            ),
        )

    @router.get("")
    def list_reports() -> list[dict[str, Any]]:
        if not reports_dir.is_dir():
            return []
        rows: list[dict[str, Any]] = []
        for entry in sorted(reports_dir.iterdir())[:MAX_REPORTS]:
            if not entry.is_dir() or entry.is_symlink() or not REPORT_ID.fullmatch(entry.name):
                continue
            try:
                rows.append(_summary(entry.name, _load(reports_dir, entry.name)))
            except ReportError as exc:
                if exc.code != "not_found":
                    logger.warning("skipping report %r: %s", entry.name, exc.message)
        rows.sort(key=lambda r: (r["finished_at"], r["report_id"]), reverse=True)
        return rows

    # Declared before "/{report_id}" so "compare" is never treated as an id.
    @router.get("/compare", response_model=None)
    def compare_reports(
        request: Request,
        a: str = Query(max_length=128),
        b: str = Query(max_length=128),
        allow_mismatch: bool = False,
    ) -> Any:
        try:
            doc_a, doc_b = _load(reports_dir, a), _load(reports_dir, b)
        except ReportError as exc:
            return fail(request, exc)
        result = compare_results(doc_a, doc_b, allow_mismatch=allow_mismatch)
        body = asdict(result)
        body["warnings"] = list(result.warnings)
        body["a"], body["b"] = _summary(a, doc_a), _summary(b, doc_b)
        return body

    @router.get("/{report_id}", response_model=None)
    def get_report(request: Request, report_id: str) -> Any:
        try:
            return _load(reports_dir, report_id).model_dump(mode="json")
        except ReportError as exc:
            return fail(request, exc)

    return router
