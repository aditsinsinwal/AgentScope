import pytest
from address import parse_address


def test_ipv6_and_port_range() -> None:
    assert parse_address("[::1]:443") == ("::1", 443)
    with pytest.raises(ValueError):
        parse_address("host:70000")
    with pytest.raises(ValueError):
        parse_address("host")
