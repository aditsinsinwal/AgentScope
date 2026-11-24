from agentscope.domain import errors
from agentscope.domain.errors import (
    AgentExecutionError,
    AgentScopeError,
    LoopbackViolationError,
    ProviderError,
)


def test_provider_error_is_single_agent_execution_error() -> None:
    # The run engine maps AgentExecutionError to agent_failed; both the agent loop and
    # the prompt-suite chat models must raise the same class for that to hold.
    assert issubclass(ProviderError, AgentExecutionError)
    assert issubclass(LoopbackViolationError, ProviderError)
    assert issubclass(ProviderError, AgentScopeError)
    source = open(errors.__file__, encoding="utf-8").read()
    assert source.count("class ProviderError(") == 1


def test_provider_error_carries_retry_metadata() -> None:
    error = ProviderError("boom", retryable=True, status_code=503, attempts=3)
    assert (error.retryable, error.status_code, error.attempts) == (True, 503, 3)
