from dedupe import unique


def test_unique_numbers() -> None:
    assert set(unique([1, 1, 2])) == {1, 2}
