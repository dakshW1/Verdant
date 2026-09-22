"""
Cost profile estimator (Phase 1).

Cloud models: (tokens_in * price_in + tokens_out * price_out) / 1_000_000
Ollama models: 0 (free, self-hosted)
"""
from __future__ import annotations

from app.config import get_model_by_id


def estimate_cost(
    model_id: str,
    tokens_in: int,
    tokens_out: int,
) -> float:
    """Returns expected cost in USD."""
    model = get_model_by_id(model_id)
    if model is None:
        return 0.0

    if model.get("provider") == "ollama":
        return 0.0

    price_in: float = model.get("price_in_per_mtok_usd", 0.0)
    price_out: float = model.get("price_out_per_mtok_usd", 0.0)

    cost = (tokens_in * price_in + tokens_out * price_out) / 1_000_000.0
    return round(cost, 8)
