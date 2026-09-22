"""
Quality profile estimator (Phase 1).

Quality is a [0,1] float representing expected output quality for a given
model + step_type combination. Sources:
  - step_types.yaml: quality_prior[model_tier] (e.g. S: 0.72, M: 0.85, L: 0.95)
  - Default: 0.80

Cascade mode quality = p_accept * q_small + (1-p_accept) * q_large  (approx upper bound)
where p_accept = probability the small model's output is accepted by the verifier.
"""
from __future__ import annotations

from app.config import get_model_by_id, get_step_types_registry


def _model_tier(model_id: str) -> str:
    model = get_model_by_id(model_id)
    if model is None:
        return "M"
    return model.get("tier", "M")


def estimate_quality_single(step_type: str, model_id: str) -> float:
    """Expected quality for a single-model run."""
    tier = _model_tier(model_id)
    reg = get_step_types_registry()
    st = reg.get("step_types", {}).get(step_type)
    if st is None:
        return 0.80
    priors: dict = st.get("q", {})
    return float(priors.get(tier, priors.get("M", 0.80)))


def estimate_p_accept(step_type: str, small_model_id: str) -> float:
    """
    P(small model output passes the verifier) for a given step_type.
    Read from step_types.yaml cascade_p_accept if present; default 0.65.
    """
    reg = get_step_types_registry()
    st = reg.get("step_types", {}).get(step_type)
    if st is None:
        return 0.65
    return float(st.get("p_accept_S", 0.65))


def estimate_quality_cascade(
    step_type: str,
    small_model_id: str,
    large_model_id: str,
    p_accept: float | None = None,
) -> tuple[float, float]:
    """
    Returns (quality, p_accept) for cascade (small → large if rejected).
    quality = p_accept * q_small + (1 - p_accept) * q_large
    """
    q_small = estimate_quality_single(step_type, small_model_id)
    q_large = estimate_quality_single(step_type, large_model_id)
    if p_accept is None:
        p_accept = estimate_p_accept(step_type, small_model_id)
    quality = p_accept * q_small + (1 - p_accept) * q_large
    return round(quality, 4), round(p_accept, 4)
