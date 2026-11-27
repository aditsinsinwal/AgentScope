"""Property-based tests for the loopback guard in agentscope.suites.providers."""

from __future__ import annotations

import ipaddress

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agentscope.domain.errors import LoopbackViolationError
from agentscope.suites.providers import require_loopback, url_host

SETTINGS = settings(max_examples=200, deadline=None)

ports = st.integers(min_value=1, max_value=65535)
loopback_v4 = st.integers(min_value=0, max_value=2**24 - 1).map(
    lambda low: str(ipaddress.IPv4Address(int(ipaddress.IPv4Address("127.0.0.0")) + low))
)
any_v4 = st.ip_addresses(v=4).map(str)
non_loopback_v4 = any_v4.filter(
    lambda host: ipaddress.IPv4Address(host) not in ipaddress.ip_network("127.0.0.0/8")
)
label = st.from_regex(r"[a-z][a-z0-9]{0,8}", fullmatch=True)


@SETTINGS
@given(host=loopback_v4, port=ports)
def test_accepts_any_127_address(host: str, port: int) -> None:
    url = f"http://{host}:{port}/v1"
    assert require_loopback(url) == url


@SETTINGS
@given(port=ports)
def test_accepts_ipv6_loopback(port: int) -> None:
    url = f"http://[::1]:{port}/v1"
    assert require_loopback(url) == url


@SETTINGS
@given(host=non_loopback_v4, port=ports)
def test_rejects_non_loopback_ipv4(host: str, port: int) -> None:
    with pytest.raises(LoopbackViolationError):
        require_loopback(f"http://{host}:{port}/v1")


@SETTINGS
@given(user=label, password=label, host=loopback_v4)
def test_rejects_userinfo(user: str, password: str, host: str) -> None:
    for url in (f"http://{user}@{host}/v1", f"http://{user}:{password}@{host}/v1"):
        with pytest.raises(LoopbackViolationError):
            require_loopback(url)


@SETTINGS
@given(loopback=loopback_v4, suffix=label)
def test_rejects_lookalike_hostnames(loopback: str, suffix: str) -> None:
    for host in (f"{loopback}.{suffix}.com", f"localhost.{suffix}.com"):
        with pytest.raises(LoopbackViolationError):
            require_loopback(f"http://{host}/v1")


@SETTINGS
@given(user=label, password=label, host=loopback_v4, port=ports)
def test_url_host_never_leaks_userinfo(user: str, password: str, host: str, port: int) -> None:
    secret = f"s3cr3t{password}"
    result = url_host(f"http://{user}:{secret}@{host}:{port}/v1?k=1")
    assert result == f"{host}:{port}"
    assert secret not in result
    assert "@" not in result
