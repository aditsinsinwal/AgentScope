import json
from pathlib import Path

from typer.testing import CliRunner, Result

from agentscope.cli import app

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/suites/task-cards"
runner = CliRunner()


def run_suite(out: Path, name: str = "good", *extra: str) -> Result:
    return runner.invoke(
        app,
        [
            "suite",
            "run",
            "--suite",
            str(EXAMPLE / "suite.yaml"),
            "--provider",
            "replay",
            "--replay-outputs",
            str(EXAMPLE / f"replay-{name}.outputs.jsonl"),
            "--out",
            str(out),
            *extra,
        ],
    )


def test_validate_ok_and_bad(tmp_path: Path) -> None:
    ok = runner.invoke(app, ["suite", "validate", str(EXAMPLE / "suite.yaml")])
    assert ok.exit_code == 0 and "Cases: 8" in ok.output and "Fingerprint:" in ok.output
    bad = tmp_path / "suite.yaml"
    bad.write_text("id: x\n")
    result = runner.invoke(app, ["suite", "validate", str(bad)])
    assert result.exit_code == 2 and "error:" in result.output


def test_run_replay_and_compare(tmp_path: Path) -> None:
    good = run_suite(tmp_path / "good")
    assert good.exit_code == 0, good.output
    assert "Source: replay" in good.output
    assert "not a human preference judgement" in good.output
    assert run_suite(tmp_path / "chatty", "chatty").exit_code == 0
    for name in ("outputs.jsonl", "results.json", "trace.jsonl", "report.md"):
        assert (tmp_path / "good" / name).is_file()

    result = runner.invoke(
        app,
        [
            "suite",
            "compare",
            str(tmp_path / "chatty/results.json"),
            str(tmp_path / "good/results.json"),
        ],
    )
    assert result.exit_code == 0 and "B better:" in result.output
    assert "no significance" in result.output
    as_json = runner.invoke(
        app,
        [
            "suite",
            "compare",
            "--json",
            str(tmp_path / "chatty/results.json"),
            str(tmp_path / "good/results.json"),
        ],
    )
    assert json.loads(as_json.stdout)["n_paired"] == 8


def test_run_refuses_existing_out_dir(tmp_path: Path) -> None:
    assert run_suite(tmp_path).exit_code == 0
    again = run_suite(tmp_path)
    assert again.exit_code == 2
    assert run_suite(tmp_path, "good", "--overwrite").exit_code == 0


def test_run_exit_code_nonzero_when_a_case_has_no_output(tmp_path: Path) -> None:
    partial = tmp_path / "partial.jsonl"
    lines = (EXAMPLE / "replay-good.outputs.jsonl").read_text().splitlines()[:-1]
    partial.write_text("\n".join(lines) + "\n")
    result = runner.invoke(
        app,
        [
            "suite",
            "run",
            "--suite",
            str(EXAMPLE / "suite.yaml"),
            "--provider",
            "replay",
            "--replay-outputs",
            str(partial),
            "--out",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 1
    assert "FAILED: 1 case" in result.output
    assert len((tmp_path / "out/outputs.jsonl").read_text().splitlines()) == 7


def test_no_trace_text(tmp_path: Path) -> None:
    assert run_suite(tmp_path, "good", "--no-trace-text").exit_code == 0
    assert "Renew the lab licence" not in (tmp_path / "trace.jsonl").read_text()


def test_provider_guards(tmp_path: Path) -> None:
    base = ["suite", "run", "--suite", str(EXAMPLE / "suite.yaml"), "--out", str(tmp_path / "o")]
    remote = runner.invoke(
        app, [*base, "--provider", "ollama", "--model", "m", "--base-url", "https://x.example/v1"]
    )
    assert remote.exit_code == 2 and "not loopback" in remote.output
    local_only = runner.invoke(
        app,
        [
            *base,
            "--provider",
            "openai-compatible",
            "--model",
            "m",
            "--base-url",
            "https://x.example/v1",
            "--local-only",
        ],
    )
    assert local_only.exit_code == 2
    no_url = runner.invoke(app, [*base, "--provider", "openai-compatible", "--model", "m"])
    assert no_url.exit_code == 2
    no_model = runner.invoke(app, [*base, "--provider", "ollama"])
    assert no_model.exit_code != 0
    no_replay = runner.invoke(app, [*base, "--provider", "replay"])
    assert no_replay.exit_code != 0
