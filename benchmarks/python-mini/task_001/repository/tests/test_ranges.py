from ranges import clamp


def test_normal_bounds() -> None:
    assert clamp(12, 0, 10) == 10
    assert clamp(5, 0, 10) == 5
