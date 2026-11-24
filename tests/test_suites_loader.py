import json
from pathlib import Path

import pytest

from agentscope.domain.errors import SuiteDefinitionError
from agentscope.suites.loader import load_suite

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/suites/task-cards/suite.yaml"

BASE_YAML = """\
id: demo-suite
kind: prompt_suite
name: Demo
version: "1"
cases: cases.jsonl
checker:
  type: regex
  pattern: "ok"
"""


def make(tmp_path: Path, cases: str, yaml_text: str = BASE_YAML) -> Path:
    (tmp_path / "cases.jsonl").write_text(cases, encoding="utf-8")
    path = tmp_path / "suite.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    return path


def test_loads_example_with_stable_fingerprint() -> None:
    first = load_suite(EXAMPLE)
    assert first.id == "task-cards-demo"
    assert len(first.cases) == 8
    assert first.fingerprint == load_suite(EXAMPLE).fingerprint
    assert first.generation.max_tokens == 200


def test_fingerprint_changes_with_cases_checker_and_prompt(tmp_path: Path) -> None:
    base = load_suite(make(tmp_path, '{"id":"a","prompt":"p"}\n'))
    other_case = load_suite(make(tmp_path, '{"id":"a","prompt":"q"}\n'))
    other_yaml = load_suite(
        make(tmp_path, '{"id":"a","prompt":"p"}\n', BASE_YAML.replace('"ok"', '"no"'))
    )
    other_system = load_suite(
        make(tmp_path, '{"id":"a","prompt":"p"}\n', BASE_YAML + "system_prompt: hi\n")
    )
    assert (
        len(
            {
                base.fingerprint,
                other_case.fingerprint,
                other_yaml.fingerprint,
                other_system.fingerprint,
            }
        )
        == 4
    )


def test_name_does_not_change_fingerprint(tmp_path: Path) -> None:
    a = load_suite(make(tmp_path, '{"id":"a","prompt":"p"}\n'))
    b = load_suite(make(tmp_path, '{"id":"a","prompt":"p"}\n', BASE_YAML.replace("Demo", "Other")))
    assert a.fingerprint == b.fingerprint


def test_rejects_path_escape(tmp_path: Path) -> None:
    (tmp_path / "outside.jsonl").write_text('{"id":"a","prompt":"p"}\n')
    inner = tmp_path / "inner"
    inner.mkdir()
    path = inner / "suite.yaml"
    path.write_text(BASE_YAML.replace("cases.jsonl", "../outside.jsonl"))
    with pytest.raises(SuiteDefinitionError, match="escapes"):
        load_suite(path)


def test_rejects_duplicate_ids_with_line_numbers(tmp_path: Path) -> None:
    path = make(tmp_path, '{"id":"a","prompt":"p"}\n\n{"id":"a","prompt":"q"}\n')
    with pytest.raises(SuiteDefinitionError, match=r"line 3: duplicate case id 'a' .*line 1"):
        load_suite(path)


def test_rejects_bad_json_with_line_number(tmp_path: Path) -> None:
    path = make(tmp_path, '{"id":"a","prompt":"p"}\n{not json}\n')
    with pytest.raises(SuiteDefinitionError, match=r"cases.jsonl line 2: invalid JSON"):
        load_suite(path)


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ('{"id":"a","prompt":"   "}', "line 1: prompt must not be blank"),
        ('{"id":"a","prompt":"p","extra":1}', "line 1"),
        ('{"id":"a b","prompt":"p"}', "line 1"),
        ('["a"]', "line 1"),
    ],
)
def test_rejects_bad_cases(tmp_path: Path, line: str, message: str) -> None:
    with pytest.raises(SuiteDefinitionError, match=message):
        load_suite(make(tmp_path, line + "\n"))


def test_max_cases_and_empty(tmp_path: Path) -> None:
    rows = "".join(json.dumps({"id": f"c{i}", "prompt": "p"}) + "\n" for i in range(3))
    with pytest.raises(SuiteDefinitionError, match="more than 2 cases"):
        load_suite(make(tmp_path, rows), max_cases=2)
    with pytest.raises(SuiteDefinitionError, match="no cases"):
        load_suite(make(tmp_path, "\n\n"))


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown: 1\n",
        "generation: {temperature: 9}\n",
        "generation: {surprise: 1}\n",
    ],
)
def test_rejects_unknown_or_invalid_yaml_keys(tmp_path: Path, mutation: str) -> None:
    with pytest.raises(SuiteDefinitionError):
        load_suite(make(tmp_path, '{"id":"a","prompt":"p"}\n', BASE_YAML + mutation))


@pytest.mark.parametrize(
    "checker",
    [
        "type: regex",
        "type: regex\n  pattern: '('",
        "type: exact\n  pattern: x",
        "type: field_lines",
        "type: field_lines\n  fields: [A, A]",
        "type: field_lines\n  fields: [A]\n  allowed_values: {B: [x]}",
        "type: json_keys",
        "type: nope",
    ],
)
def test_rejects_bad_checker_config(tmp_path: Path, checker: str) -> None:
    yaml_text = BASE_YAML.split("checker:")[0] + "checker:\n  " + checker + "\n"
    with pytest.raises(SuiteDefinitionError):
        load_suite(make(tmp_path, '{"id":"a","prompt":"p"}\n', yaml_text))


def test_exact_requires_references(tmp_path: Path) -> None:
    yaml_text = BASE_YAML.split("checker:")[0] + "checker:\n  type: exact\n"
    with pytest.raises(SuiteDefinitionError, match="reference"):
        load_suite(make(tmp_path, '{"id":"a","prompt":"p"}\n', yaml_text))


def test_bad_kind_and_id(tmp_path: Path) -> None:
    with pytest.raises(SuiteDefinitionError):
        load_suite(
            make(tmp_path, '{"id":"a","prompt":"p"}\n', BASE_YAML.replace("prompt_suite", "x"))
        )
    with pytest.raises(SuiteDefinitionError):
        load_suite(
            make(tmp_path, '{"id":"a","prompt":"p"}\n', BASE_YAML.replace("demo-suite", "X"))
        )
