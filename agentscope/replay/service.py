from agentscope.domain.models import RunId
from agentscope.tracing.recorder import TraceRecorder
from agentscope.tracing.render import render_trace


class ReplayService:
    """Read-only deterministic trace inspection; it does not re-call a model."""

    def __init__(self, traces: TraceRecorder) -> None:
        self.traces = traces

    async def replay(self, run_id: RunId, from_step: int = 1) -> str:
        if from_step < 1:
            raise ValueError("from_step must be positive")
        return render_trace(await self.traces.events(run_id), from_step)
