from ranges import clamp


def test_reversed_bounds_are_normalized() -> None:
    assert clamp(5, 10, 0) == 5
    assert clamp(-1, 10, 0) == 0
