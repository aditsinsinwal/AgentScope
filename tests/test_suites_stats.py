from __future__ import annotations

import json
import random
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentscope.cli import app
from agentscope.suites.artifacts import load_results
from agentscope.suites.compare import compare_results
from agentscope.suites.stats import mcnemar_exact, paired_bootstrap, quantile

EXAMPLE = Path(__file__).parents[1] / "examples/suites/task-cards"
runner = CliRunner()


def test_mcnemar_hand_values() -> None:
    assert mcnemar_exact(7, 2) == 0.1796875  # 2 * (1 + 9 + 36) / 512
    assert mcnemar_exact(2, 7) == 0.1796875
    assert mcnemar_exact(4, 0) == 0.125  # 2 / 16
    assert mcnemar_exact(5, 5) == 1.0
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(1, 0) == 1.0  # min(1, 2 * 1/2)


def test_quantile_interpolates() -> None:
    assert quantile([0.0, 1.0], 0.5) == 0.5
    assert quantile([1.0, 2.0, 3.0], 0.0) == 1.0 and quantile([1.0, 2.0, 3.0], 1.0) == 3.0


def test_bootstrap_constant_differences_collapse() -> None:
    out = paired_bootstrap({"m": [0.5] * 6}, resamples=200)
    iv = out["m"]
    assert iv is not None
    assert (iv.estimate, iv.low, iv.high, iv.n) == (0.5, 0.5, 0.5, 6)


def test_bootstrap_two_cases_hand_checked() -> None:
    # Diffs [0, 1]: every resample mean is 0, 0.5 or 1, so the interval lies inside [0, 1].
    iv = paired_bootstrap({"m": [0.0, 1.0]}, resamples=1000)["m"]
    assert iv is not None and iv.estimate == 0.5
    assert 0.0 <= iv.low <= 0.5 <= iv.high <= 1.0


def test_bootstrap_null_when_fewer_than_two() -> None:
    out = paired_bootstrap(
        {"one": [1.0, None], "none": [None, None], "ok": [1.0, 0.0]}, resamples=100
    )
    assert out["one"] is None and out["none"] is None and out["ok"] is not None
    assert paired_bootstrap({"m": []}, resamples=100) == {"m": None}
    assert paired_bootstrap({}, resamples=100) == {}


def test_bootstrap_missing_entries_set_n() -> None:
    iv = paired_bootstrap({"m": [1.0, None, 0.0, 1.0]}, resamples=200)["m"]
    assert iv is not None and iv.n == 3 and iv.estimate == pytest.approx(2 / 3)


def test_bootstrap_deterministic_per_seed() -> None:
    rng = random.Random(1)
    data = {"m": [rng.choice([-1.0, 0.0, 1.0]) for _ in range(30)]}
    a = paired_bootstrap(data, resamples=500, seed=3)
    assert a == paired_bootstrap(data, resamples=500, seed=3)
    assert a != paired_bootstrap(data, resamples=500, seed=4)


def test_bootstrap_validates() -> None:
    with pytest.raises(ValueError, match="resamples"):
        paired_bootstrap({"m": [1.0, 0.0]}, resamples=99)
    with pytest.raises(ValueError, match="confidence"):
        paired_bootstrap({"m": [1.0, 0.0]}, confidence=0.5)
    with pytest.raises(ValueError, match="same paired cases"):
        paired_bootstrap({"a": [1.0], "b": [1.0, 2.0]})


def test_bootstrap_speed() -> None:
    rng = random.Random(0)
    metrics = {k: [rng.choice([-1.0, 0.0, 1.0]) for _ in range(50)] for k in "abcdefgh"}
    start = time.perf_counter()
    paired_bootstrap(metrics, resamples=10_000)
    assert time.perf_counter() - start < 1.5


def _docs(tmp_path: Path):  # type: ignore[no-untyped-def]
    paths = {}
    for name in ("good", "chatty"):
        out = tmp_path / name
        result = runner.invoke(
            app,
            [
                "suite", "run", "--suite", str(EXAMPLE / "suite.yaml"),
                "--provider", "replay",
                "--replay-outputs", str(EXAMPLE / f"replay-{name}.outputs.jsonl"),
                "--out", str(out),
            ],
        )  # fmt: skip
        assert result.exit_code == 0, result.output
        paths[name] = out / "results.json"
    return load_results(paths["chatty"]), load_results(paths["good"]), paths


def test_compare_intervals_values(tmp_path: Path) -> None:
    a, b, _ = _docs(tmp_path)
    iv = compare_results(a, b).intervals
    assert iv["method"] == "paired percentile bootstrap"
    assert (iv["resamples"], iv["confidence"], iv["seed"], iv["n_paired"]) == (10000, 0.95, 0, 8)
    assert iv["pass_rate_delta"]["estimate"] == 0.5
    assert iv["format_valid_rate_delta"]["estimate"] == 0.75
    assert iv["mean_score_delta"]["estimate"] == pytest.approx(0.0)
    assert iv["mcnemar_pass"] == {
        "b_only": 4,
        "a_only": 0,
        "p_value": 0.125,
        "method": "exact two-sided binomial",
    }
    prio = iv["field_accuracy_delta"]["PRIORITY"]
    assert prio["estimate"] == 0.125 and prio["n"] == 8
    assert prio["low"] <= 0.125 <= prio["high"]


def test_compare_invariant_to_case_order(tmp_path: Path) -> None:
    a, b, _ = _docs(tmp_path)
    base = compare_results(a, b).intervals
    shuffled_a = a.model_copy(update={"cases": list(reversed(a.cases))})
    cases_b = list(b.cases)
    random.Random(5).shuffle(cases_b)
    shuffled_b = b.model_copy(update={"cases": cases_b})
    assert compare_results(shuffled_a, shuffled_b).intervals == base


def test_compare_seed_changes_bounds_not_estimate(tmp_path: Path) -> None:
    a, b, _ = _docs(tmp_path)
    one = compare_results(a, b, seed=1, resamples=300).intervals
    again = compare_results(a, b, seed=1, resamples=300).intervals
    assert one == again and one["seed"] == 1 and one["resamples"] == 300
    assert one["pass_rate_delta"]["estimate"] == 0.5


def test_compare_null_when_under_two_paired(tmp_path: Path) -> None:
    a, b, _ = _docs(tmp_path)
    a1 = a.model_copy(update={"cases": a.cases[:1]})
    iv = compare_results(a1, b, allow_mismatch=True).intervals
    assert iv["n_paired"] == 1
    assert iv["mean_score_delta"] is None and iv["pass_rate_delta"] is None
    assert iv["format_valid_rate_delta"] is None and iv["mcnemar_pass"] is None
    assert all(v is None for v in iv["field_accuracy_delta"].values())
    a0 = a.model_copy(update={"cases": []})
    assert compare_results(a0, b, allow_mismatch=True).intervals["n_paired"] == 0


def test_cli_options_and_output(tmp_path: Path) -> None:
    _, _, paths = _docs(tmp_path)
    args = ["suite", "compare", str(paths["chatty"]), str(paths["good"])]
    text = runner.invoke(app, [*args, "--resamples", "200", "--seed", "7", "--confidence", "0.9"])
    assert text.exit_code == 0, text.output
    assert "paired percentile bootstrap" in text.output and "n=8 paired" in text.output
    assert "90% confidence, 200 resamples, seed 7" in text.output
    assert "McNemar on pass/fail" in text.output and "p = 0.1250" in text.output
    lowered = text.output.lower()
    assert (
        "significant." not in lowered and "proves" not in lowered and "better model" not in lowered
    )
    js = runner.invoke(app, [*args, "--json", "--resamples", "200", "--seed", "7"])
    body = json.loads(js.stdout)
    assert body["intervals"]["seed"] == 7 and body["intervals"]["resamples"] == 200
    assert body["n_paired"] == 8


@pytest.mark.parametrize(
    "extra",
    [
        ["--resamples", "99"],
        ["--resamples", "100001"],
        ["--confidence", "0.5"],
        ["--confidence", "1"],
        ["--confidence", "0.2"],
    ],
)
def test_cli_rejects_bad_options(tmp_path: Path, extra: list[str]) -> None:
    _, _, paths = _docs(tmp_path)
    result = runner.invoke(
        app, ["suite", "compare", str(paths["chatty"]), str(paths["good"]), *extra]
    )
    assert result.exit_code != 0
