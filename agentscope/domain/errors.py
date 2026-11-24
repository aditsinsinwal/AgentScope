"""Explicit AgentScope error hierarchy."""


class AgentScopeError(Exception):
    """Base class for expected application failures."""


class InvalidStateTransition(AgentScopeError):
    """Raised when a run attempts an illegal state transition."""


class TaskDefinitionError(AgentScopeError):
    """Raised for an invalid or unsafe evaluation task."""


class SandboxError(AgentScopeError):
    """Raised when isolated execution infrastructure fails."""


class AgentExecutionError(AgentScopeError):
    """Raised when an agent cannot finish its action loop."""


class ProviderError(AgentExecutionError):
    """A model provider call failed. Messages never contain credentials or request bodies."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        attempts: int = 1,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.attempts = attempts


class AgentLimitExceeded(AgentExecutionError):
    """The agent loop hit a hard step or tool-call cap; distinct from a provider/agent fault."""

    def __init__(self, limit: str, value: int) -> None:
        super().__init__(f"limit_exceeded: agent exceeded {limit}={value}")
        self.limit = limit
        self.value = value


class ToolExecutionError(AgentScopeError):
    """Raised for a controlled tool failure."""


class EvaluationError(AgentScopeError):
    """Raised when objective evaluation itself cannot complete."""


class RunNotFoundError(AgentScopeError):
    """Raised when a requested run does not exist."""


class SuiteDefinitionError(AgentScopeError):
    """Raised for an invalid or unsafe prompt-suite definition or case file."""


class ProviderError(AgentScopeError):
    """Raised when a chat-model provider cannot return a completion."""

    def __init__(
        self, message: str, *, status_code: int | None = None, retryable: bool = False
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class LoopbackViolationError(ProviderError):
    """Raised when a loopback-only endpoint guard rejects a URL."""


class SuiteComparisonError(AgentScopeError):
    """Raised when two suite results cannot be compared."""
