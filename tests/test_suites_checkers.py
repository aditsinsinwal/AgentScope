import pytest

from agentscope.suites.checkers import (
    ExactChecker,
    FieldLinesChecker,
    JsonKeysChecker,
    RegexChecker,
    normalise,
    unwrap_fence,
)

FIELDS = ("TASK", "OWNER", "DUE", "PRIORITY", "NOTE")
ALLOWED = {"PRIORITY": ("Low", "Medium", "High")}
REF = "TASK: Book the room\nOWNER: Omar\nDUE: Thursday\nPRIORITY: Medium\nNOTE: Asked by Noor."


def card() -> FieldLinesChecker:
    return FieldLinesChecker(FIELDS, ALLOWED)


def test_normalise_and_fence() -> None:
    assert normalise("  Héllo \n\t WORLD ") == "héllo world"
    assert normalise("A  b", case_insensitive=False) == "A b"
    assert unwrap_fence("```\nabc\n```") == "abc"
    assert unwrap_fence("```text\n a \n```  ") == "a"
    # two fences, or text around a fence, are not unwrapped
    assert unwrap_fence("```\na\n```\n```\nb\n```") == "```\na\n```\n```\nb\n```"
    assert unwrap_fence("hi\n```\na\n```") == "hi\n```\na\n```"


def test_exact() -> None:
    checker = ExactChecker()
    assert checker.check("  hello\n  world ", "hello world").passed
    assert checker.check("```\nhello world\n```", "hello world").passed
    assert not checker.check("Hello world", "hello world").passed
    assert ExactChecker(case_insensitive=True).check("Hello world", "hello world").passed
    wrong = checker.check("nope", "hello world")
    assert (wrong.passed, wrong.score, wrong.format_valid) == (False, 0.0, True)
    assert not checker.check("", "x").format_valid
    with pytest.raises(ValueError):
        checker.check("x", None)


def test_regex_modes_and_limits() -> None:
    full = RegexChecker(r"\d{3}-\d{4}")
    assert full.check("  555-1234\n", None).passed
    assert not full.check("call 555-1234", None).passed
    assert RegexChecker(r"\d{3}", mode="search").check("call 555-1234", None).passed
    assert RegexChecker("yes", ignore_case=True).check("YES", None).passed
    # output beyond the bound is truncated, so a match past it is not seen
    assert not RegexChecker("needle", mode="search").check("x" * 100_000 + "needle", None).passed


def test_json_keys() -> None:
    checker = JsonKeysChecker(("a", "b"))
    assert checker.check('{"a": 1, "b": 2, "c": 3}', None).passed
    assert checker.check('```json\n{"a": 1, "b": 2}\n```', None).passed
    partial = checker.check('{"a": 1}', None)
    assert (partial.passed, partial.format_valid, partial.score) == (False, False, 0.5)
    assert "missing keys: b" in partial.detail
    assert not checker.check("[1]", None).format_valid
    assert not checker.check("Sure: {}", None).format_valid
    assert checker.check("not json", None).score == 0.0


def test_field_lines_perfect_and_fenced() -> None:
    result = card().check(REF, REF)
    assert (result.passed, result.score, result.format_valid) == (True, 1.0, True)
    assert card().check("\n```\n" + REF + "\n```\n", REF).passed
    assert result.fields is not None and result.fields["OWNER"].matched is True


def test_field_lines_value_with_colon_and_unicode() -> None:
    ref = "TASK: Café: renew\nOWNER: Zoë\nDUE: Thursday\nPRIORITY: High\nNOTE: naïve résumé"
    out = ref.replace("Zoë", "ZOË").replace("Thursday", "  Thursday  ")
    assert card().check(out, ref).passed
    decomposed = ref.replace("Zoë", "Zoë")  # NFC-equivalent
    assert card().check(decomposed, ref).passed


def test_field_lines_rejects_chatty_preamble() -> None:
    result = card().check("Sure! Here is the card:\n" + REF, REF)
    assert not result.format_valid and not result.passed
    assert "extra non-field line" in result.detail
    assert result.score == 1.0  # content right, format wrong is visible


def test_field_lines_trailing_chatter_and_non_strict() -> None:
    assert not card().check(REF + "\nHope that helps!", REF).format_valid
    loose = FieldLinesChecker(FIELDS, ALLOWED, strict_line_count=False)
    assert loose.check(REF + "\nHope that helps!", REF).passed


def test_field_lines_missing_field() -> None:
    out = REF.replace("DUE: Thursday\n", "")
    result = card().check(out, REF)
    assert not result.format_valid and "missing DUE" in result.detail
    assert result.fields is not None
    assert result.fields["DUE"].present is False
    assert result.score == pytest.approx(4 / 5)


def test_field_lines_order() -> None:
    lines = REF.splitlines()
    swapped = "\n".join([lines[1], lines[0], *lines[2:]])
    assert "out of order" in card().check(swapped, REF).detail
    unordered = FieldLinesChecker(FIELDS, ALLOWED, ordered=False)
    assert unordered.check(swapped, REF).passed


def test_field_lines_duplicate_empty_and_disallowed() -> None:
    assert "duplicate TASK" in card().check("TASK: x\n" + REF, REF).detail
    assert "empty OWNER" in card().check(REF.replace("OWNER: Omar", "OWNER:"), REF).detail
    bad = card().check(REF.replace("Medium", "medium"), REF)
    assert not bad.format_valid and "allowed values" in bad.detail
    assert bad.fields is not None and bad.fields["PRIORITY"].valid is False
    assert bad.fields["PRIORITY"].matched is True  # case-insensitive vs reference


def test_field_lines_keys_are_case_sensitive_and_tight() -> None:
    assert not card().check(REF.replace("TASK:", "Task:"), REF).format_valid
    assert not card().check(REF.replace("TASK:", "TASK :"), REF).format_valid


def test_field_lines_wrong_content_scores_partially() -> None:
    result = card().check(REF.replace("Omar", "Priya").replace("Thursday", "Friday"), REF)
    assert result.format_valid and not result.passed
    assert result.score == pytest.approx(3 / 5)
    assert "OWNER" in result.detail and "DUE" in result.detail


def test_field_lines_without_reference_scores_format_only() -> None:
    good = card().check(REF, None)
    assert (good.passed, good.score) == (True, 1.0)
    assert good.fields is not None and good.fields["TASK"].matched is None
    bad = card().check("hello", None)
    assert (bad.passed, bad.score) == (False, 0.0)


def test_empty_output() -> None:
    result = card().check("", REF)
    assert not result.format_valid and result.score == 0.0
