"""Load and validate prompt suites from YAML plus a JSONL cases file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from agentscope.domain.errors import SuiteDefinitionError
from agentscope.suites.models import (
    CaseDocument,
    PromptSuite,
    SuiteCase,
    SuiteDocument,
    split_jsonl,
    suite_fingerprint,
)

DEFAULT_MAX_CASES = 10_000
MAX_CASES_FILE_BYTES = 64 * 1024 * 1024


def _child(base: Path, value: str) -> Path:
    candidate = (base / value).resolve()
    if not candidate.is_relative_to(base.resolve()):
        raise SuiteDefinitionError(f"suite path escapes its definition directory: {value}")
    return candidate


def _brief(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors(include_url=False):
        where = ".".join(str(item) for item in error["loc"]) or "<root>"
        parts.append(f"{where}: {error['msg']}")
    return "; ".join(parts)


def parse_cases(
    data: bytes, source: str, *, max_cases: int = DEFAULT_MAX_CASES
) -> tuple[SuiteCase, ...]:
    """Parse JSONL bytes. Errors name the 1-based line number."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SuiteDefinitionError(f"{source}: not valid UTF-8: {exc}") from exc
    cases: list[SuiteCase] = []
    seen: dict[str, int] = {}
    for number, line in enumerate(split_jsonl(text), start=1):
        if not line.strip():
            continue
        try:
            raw: Any = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SuiteDefinitionError(f"{source} line {number}: invalid JSON: {exc.msg}") from exc
        try:
            document = CaseDocument.model_validate(raw)
        except ValidationError as exc:
            raise SuiteDefinitionError(f"{source} line {number}: {_brief(exc)}") from exc
        if not document.prompt.strip():
            raise SuiteDefinitionError(f"{source} line {number}: prompt must not be blank")
        if document.id in seen:
            raise SuiteDefinitionError(
                f"{source} line {number}: duplicate case id {document.id!r} "
                f"(first seen on line {seen[document.id]})"
            )
        seen[document.id] = number
        if len(cases) >= max_cases:
            raise SuiteDefinitionError(f"{source}: more than {max_cases} cases (see --max-cases)")
        cases.append(SuiteCase(document.id, document.prompt, document.reference, document.metadata))
    if not cases:
        raise SuiteDefinitionError(f"{source}: no cases found")
    return tuple(cases)


def load_suite(path: Path, *, max_cases: int = DEFAULT_MAX_CASES) -> PromptSuite:
    path = path.resolve()
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        document = SuiteDocument.model_validate(raw)
        cases_path = _child(path.parent, document.cases)
        if not cases_path.is_file():
            raise SuiteDefinitionError(f"cases file does not exist: {document.cases}")
        if cases_path.stat().st_size > MAX_CASES_FILE_BYTES:
            raise SuiteDefinitionError(f"cases file larger than {MAX_CASES_FILE_BYTES} bytes")
        cases_bytes = cases_path.read_bytes()
        cases = parse_cases(cases_bytes, document.cases, max_cases=max_cases)
        if document.checker.type == "exact":
            missing = [case.id for case in cases if case.reference is None]
            if missing:
                raise SuiteDefinitionError(
                    f"exact checker needs a reference for every case; missing: "
                    f"{', '.join(missing[:5])}"
                )
        return PromptSuite(
            id=document.id,
            name=document.name,
            version=document.version,
            system_prompt=document.system_prompt,
            generation=document.generation,
            checker=document.checker,
            cases=cases,
            fingerprint=suite_fingerprint(
                document.id,
                document.version,
                document.system_prompt,
                document.generation,
                document.checker,
                cases_bytes,
            ),
            source_path=path,
        )
    except SuiteDefinitionError:
        raise
    except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
        detail = _brief(exc) if isinstance(exc, ValidationError) else str(exc)
        raise SuiteDefinitionError(f"invalid suite definition {path}: {detail}") from exc
