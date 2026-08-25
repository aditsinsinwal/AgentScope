from datetime import UTC

from timestamps import parse_timestamp


def test_aware_and_normalized() -> None:
    assert parse_timestamp("2024-01-02T03:04:05Z").tzinfo is UTC
    assert parse_timestamp("2024-01-02T04:04:05+01:00").hour == 3
