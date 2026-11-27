"""Property-based round-trip tests for outputs.jsonl (writer) and replay reading."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from hypothesis import given, settings
from hypothesis import strategies as st

from agentscope.suites.artifacts import outputs_jsonl
from agentscope.suites.providers import ReplayChatModel
from agentscope.suites.runner import CaseOutcome, SuiteRunResult

SETTINGS = settings(max_examples=200, deadline=None)

# Arbitrary characters plus the ones line-splitting readers treat as breaks.
CHARS = st.one_of(
    st.characters(blacklist_categories=("Cs",)),
    st.sampled_from(["\u2028", "\u2029", "\u0085", "\r", "\n", "\x0b", "\x0c", "\x1c", "\\"]),
)
EMOJI = st.sampled_from(["🙂", "👩🏽\u200d💻", "🇸🇪", "🏳️‍🌈"])
text = st.lists(st.one_of(st.text(alphabet=CHARS, max_size=6), EMOJI), max_size=12).map("".join)


def _result(pairs: list[tuple[str, str]]) -> SuiteRunResult:
    outcomes = tuple(
        CaseOutcome(
            case_id=case_id,
            output=output,
            completion=None,
            check=None,
            error=None,
            wall_ms=1.0,
        )
        for case_id, output in pairs
    )
    # outputs_jsonl only reads `outcomes`; the rest of SuiteRunResult is not needed here.
    return cast(SuiteRunResult, SimpleNamespace(outcomes=outcomes))


@SETTINGS
@given(pairs=st.lists(st.tuples(text, text), max_size=8, unique_by=lambda p: p[0]))
def test_each_record_is_exactly_one_line(pairs: list[tuple[str, str]]) -> None:
    content = outputs_jsonl(_result(pairs))
    # Splits on every line boundary Python knows about, not just "\n".
    assert len(content.splitlines()) == len(pairs)
    assert content.count("\n") == len(pairs)


@SETTINGS
@given(pairs=st.lists(st.tuples(text, text), max_size=8, unique_by=lambda p: p[0]))
def test_outputs_round_trip_through_replay_reader(pairs: list[tuple[str, str]]) -> None:
    # A fresh directory per example: pytest's tmp_path is shared across hypothesis examples.
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "outputs.jsonl"
        path.write_text(outputs_jsonl(_result(pairs)), encoding="utf-8")
        replay = ReplayChatModel.from_jsonl(path)
    assert replay.case_ids() == [case_id for case_id, _ in pairs]
    for case_id, output in pairs:
        assert replay.output_for(case_id) == output
