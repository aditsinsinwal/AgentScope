def parse_address(value: str) -> tuple[str, int]:
    host, port = value.split(":")
    return host, int(port)
