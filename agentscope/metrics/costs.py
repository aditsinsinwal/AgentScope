from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from agentscope.agents.base import Usage


class PriceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_per_million: Decimal = Field(ge=0)
    output_per_million: Decimal = Field(ge=0)
    cached_input_per_million: Decimal = Field(default=Decimal(0), ge=0)


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_per_million: Decimal
    output_per_million: Decimal
    cached_input_per_million: Decimal


class PricingCatalog:
    def __init__(self, prices: dict[str, ModelPrice]) -> None:
        self.prices = prices

    @classmethod
    def load(cls, path: Path) -> PricingCatalog:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(
            {
                str(model): ModelPrice(**PriceDocument.model_validate(value).model_dump())
                for model, value in raw.items()
            }
        )

    def get(self, model: str) -> ModelPrice:
        try:
            return self.prices[model]
        except KeyError as exc:
            raise KeyError(f"no price configured for model {model!r}") from exc


def estimate_cost(usage: Usage, price: ModelPrice) -> Decimal:
    million = Decimal(1_000_000)
    uncached = max(0, usage.input_tokens - usage.cached_tokens)
    return (
        Decimal(uncached) * price.input_per_million
        + Decimal(usage.cached_tokens) * price.cached_input_per_million
        + Decimal(usage.output_tokens) * price.output_per_million
    ) / million
