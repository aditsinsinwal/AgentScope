from cart import checkout


def test_checkout_totals_items() -> None:
    assert checkout([10, 20]) == {"status": "ok", "total": 30, "average": 15}
