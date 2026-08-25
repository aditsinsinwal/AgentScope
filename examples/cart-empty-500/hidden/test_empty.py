from cart import checkout


def test_empty_cart_is_rejected_without_exception() -> None:
    assert checkout([]) == {"status": "empty", "total": 0}
