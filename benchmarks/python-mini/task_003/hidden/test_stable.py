from dedupe import unique


def test_order_and_unhashable_values() -> None:
    values = [[1], [1], [2], [1]]
    assert unique(values) == [[1], [2]]
    assert values == [[1], [1], [2], [1]]
