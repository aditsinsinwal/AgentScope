from timestamps import parse_timestamp


def test_components() -> None:
    assert parse_timestamp("2024-01-02T03:04:05Z").year == 2024
