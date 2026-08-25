from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskCreate(StrictSchema):
    definition_path: str = Field(min_length=1)


class TaskView(BaseModel):
    id: str
    name: str
    description: str
    version: str
    fingerprint: str


class ModelConfigurationSchema(StrictSchema):
    provider: str
    model: str
    base_url: str | None = None
    temperature: float = Field(default=0, ge=0, le=2)
    max_output_tokens: int = Field(default=4096, ge=1)


class AgentConfigurationSchema(StrictSchema):
    name: str
    model: ModelConfigurationSchema | None = None
    tools: tuple[str, ...] = ()
    system_prompt: str = ""
    max_steps: int = Field(default=50, ge=1, le=500)


class ExperimentCreate(StrictSchema):
    name: str
    task_ids: tuple[str, ...] = Field(min_length=1)
    configurations: tuple[AgentConfigurationSchema, ...] = Field(min_length=1)
    seed: int = 0


class ExperimentView(BaseModel):
    id: str
    name: str
    task_ids: tuple[str, ...]
    configuration_names: tuple[str, ...]
    seed: int


class RunView(BaseModel):
    id: str
    task_id: str
    agent: str
    status: str
    seed: int
    task_hash: str
    created_at: datetime
    updated_at: datetime
    passed: bool | None = None
    score: Decimal | None = None
    agent_duration_seconds: float = 0
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failure_message: str | None = None


class RunBatchView(BaseModel):
    run_ids: tuple[str, ...]


class TraceView(BaseModel):
    run_id: str
    timeline: str


class ErrorBody(BaseModel):
    code: str
    message: str
