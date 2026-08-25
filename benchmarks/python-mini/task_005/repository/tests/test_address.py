from address import parse_address


def test_hostname() -> None:
    assert parse_address("localhost:8080") == ("localhost", 8080)
