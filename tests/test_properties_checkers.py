"""Property-based tests for the deterministic checkers in agentscope.suites.checkers."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from agentscope.suites.checkers import (
    MAX_CHECK_CHARS,
    ExactChecker,
    FieldLinesChecker,
    JsonKeysChecker,
    RegexChecker,
    parse_field_lines,
)

SETTINGS = settings(max_examples=200, deadline=None)

FIELDS = ("TASK", "OWNER", "DUE", "PRIORITY")
ALLOWED = {"PRIORITY": ("Low", "Medium", "High")}

# Characters that matter to line splitting and whitespace handling, mixed with arbitrary text.
LINE_TRICKY = st.one_of(
    st.characters(),
    st.sampled_from(["\u2028", "\u2029", "\u0085", "\r", "\n", "\x0b", "\x0c", "\x1c", ":", " "]),
)
tricky_text = st.text(alphabet=LINE_TRICKY, max_size=300)

# A value that survives the card's strip()/split rules unchanged, so a card built from it
# is a well-formed card that must accept itself.
card_value = st.text(alphabet=LINE_TRICKY, min_size=1, max_size=40).filter(
    lambda s: s.strip() != "" and "\n" not in s and "\r" not in s
)


@SETTINGS
@given(text=tricky_text, ci=st.booleans())
def test_exact_accepts_its_own_reference(text: str, ci: bool) -> None:
    assert ExactChecker(ci).check(text, text).passed


@SETTINGS
@given(output=tricky_text, reference=tricky_text)
def test_scores_stay_within_unit_interval(output: str, reference: str) -> None:
    checkers = [
        ExactChecker(),
        RegexChecker(r".*", mode="search"),
        JsonKeysChecker(("a", "b")),
        FieldLinesChecker(FIELDS, ALLOWED),
    ]
    for checker in checkers:
        for ref in (None, reference):
            if ref is None and isinstance(checker, ExactChecker):
                continue  # exact requires a reference by contract
            score = checker.check(output, ref).score
            assert 0.0 <= score <= 1.0


@SETTINGS
@given(output=tricky_text, reference=st.one_of(st.none(), tricky_text))
def test_checks_are_deterministic(output: str, reference: str | None) -> None:
    checker = FieldLinesChecker(FIELDS, ALLOWED)
    assert checker.check(output, reference) == checker.check(output, reference)


@SETTINGS
@given(text=tricky_text)
def test_field_lines_never_crashes_on_arbitrary_text(text: str) -> None:
    parsed = parse_field_lines(text, FIELDS)
    assert set(parsed.values) <= set(FIELDS)
    assert len(parsed.order) == sum(len(v) for v in parsed.values.values())
    FieldLinesChecker(FIELDS, ALLOWED).check(text, None)


@SETTINGS
@given(
    task=card_value,
    owner=card_value,
    due=card_value,
    priority=st.sampled_from(ALLOWED["PRIORITY"]),
)
def test_field_card_accepts_its_own_reference(
    task: str, owner: str, due: str, priority: str
) -> None:
    card = f"TASK: {task}\nOWNER: {owner}\nDUE: {due}\nPRIORITY: {priority}"
    result = FieldLinesChecker(FIELDS, ALLOWED).check(card, card)
    assert result.format_valid
    assert result.passed
    assert result.score == 1.0


@SETTINGS
@given(
    body=st.text(alphabet=st.characters(blacklist_characters="`"), max_size=60).filter(
        lambda s: s.strip() != ""
    )
)
def test_exact_accepts_fenced_reference(body: str) -> None:
    # Regression: body="a" -> reference "```\na\n```" used to fail to match itself.
    reference = f"```\n{body}\n```"
    assert ExactChecker().check(reference, reference).passed


@SETTINGS
@given(length=st.integers(min_value=MAX_CHECK_CHARS + 1, max_value=MAX_CHECK_CHARS + 50))
def test_exact_refuses_to_compare_over_the_limit(length: int) -> None:
    # Truncated comparison would pass values that differ only past MAX_CHECK_CHARS.
    result = ExactChecker().check("a" * length + "X", "a" * length + "Y")
    assert not result.passed
    assert "not compared" in result.detail
    assert not ExactChecker().check("a" * length, "a" * length).passed


@SETTINGS
@given(body=st.text(alphabet=st.characters(blacklist_characters="`"), max_size=60))
def test_exact_fenced_reference_matches_unfenced_output(body: str) -> None:
    # A fence is removed from both sides, so a fenced reference matches the bare text.
    result = ExactChecker().check(body, f"```\n{body}\n```")
    assert result.passed
