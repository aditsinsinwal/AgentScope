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


class ToolExecutionError(AgentScopeError):
    """Raised for a controlled tool failure."""


class EvaluationError(AgentScopeError):
    """Raised when objective evaluation itself cannot complete."""


class RunNotFoundError(AgentScopeError):
    """Raised when a requested run does not exist."""
