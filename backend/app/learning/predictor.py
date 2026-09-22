"""
Online learning predictor — Phase 6.

Estimates p_accept(step_type, model) and quality(step_type, model) from
telemetry stored in StepRunRecord. Uses a Beta-Binomial conjugate update:

  α_prior = prior_strength * q_prior
  β_prior = prior_strength * (1 - q_prior)
  α_post = α_prior + sum(accepted)
  β_post = β_prior + sum(rejected)
  E[p] = α_post / (α_post + β_post)

The prior comes from registry step_types.yaml (via the profiles.quality module).
This module is called after each run to update an in-process cache.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from threading import Lock

logger = logging.getLogger(__name__)

_PRIOR_STRENGTH = 10  # pulled from step_types.yaml if available


@dataclass
class BetaBinomialState:
    alpha: float
    beta: float

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def uncertainty(self) -> float:
        """Std dev of Beta distribution."""
        a, b = self.alpha, self.beta
        n = a + b
        return (a * b / (n * n * (n + 1))) ** 0.5

    def update(self, accepted: int, rejected: int) -> None:
        self.alpha += accepted
        self.beta += rejected


# Cache: (step_type, model) → BetaBinomialState
_STATE: dict[tuple[str, str], BetaBinomialState] = {}
_LOCK = Lock()


def _prior_alpha_beta(step_type: str, model_id: str) -> tuple[float, float]:
    """Initialize Beta prior from quality registry."""
    from app.config import get_step_types_registry
    from app.profiles.quality import _model_tier

    strength = get_step_types_registry().get("prior_strength", _PRIOR_STRENGTH)
    tier = _model_tier(model_id)

    st = get_step_types_registry().get("step_types", {}).get(step_type)
    q = 0.8
    if st:
        q = float(st.get("q", {}).get(tier, st.get("q", {}).get("M", 0.8)))

    alpha = strength * q
    beta = strength * (1 - q)
    return max(alpha, 0.1), max(beta, 0.1)


def get_state(step_type: str, model_id: str) -> BetaBinomialState:
    """Get (or initialize) the Beta-Binomial state for a (step_type, model) pair."""
    key = (step_type, model_id)
    with _LOCK:
        if key not in _STATE:
            alpha, beta = _prior_alpha_beta(step_type, model_id)
            _STATE[key] = BetaBinomialState(alpha=alpha, beta=beta)
        return _STATE[key]


def update_from_run(run_id: str) -> int:
    """
    Pull all telemetry for the given run_id from DB and update in-memory state.
    Returns the number of records processed.
    """
    try:
        from app.db import get_session, StepRunRecord
        from sqlmodel import select

        with get_session() as session:
            records = session.exec(
                select(StepRunRecord).where(StepRunRecord.run_id == run_id)
            ).all()

        n = 0
        for rec in records:
            if rec.accepted is None:
                continue
            state = get_state(rec.step_type, rec.model)
            with _LOCK:
                state.update(
                    accepted=1 if rec.accepted else 0,
                    rejected=0 if rec.accepted else 1,
                )
            n += 1

        logger.info("Predictor: updated %d states from run %s", n, run_id)
        return n
    except Exception as exc:
        logger.warning("Predictor update failed for run %s: %s", run_id, exc)
        return 0


def predict_p_accept(step_type: str, model_id: str) -> float:
    """Return the posterior mean E[p_accept] for (step_type, model)."""
    return get_state(step_type, model_id).mean


def predict_quality(step_type: str, model_id: str) -> float:
    """
    Return a blended quality estimate: 70% registry prior + 30% learned p_accept.
    Once we have enough data (n > 20), weight shifts toward learned.
    """
    from app.profiles.quality import estimate_quality_single
    from app.config import get_step_types_registry

    state = get_state(step_type, model_id)
    n = state.alpha + state.beta
    prior_strength = get_step_types_registry().get("prior_strength", _PRIOR_STRENGTH)

    registry_q = estimate_quality_single(step_type, model_id)
    learned_q = state.mean

    # Weight toward learned estimate as we accumulate data beyond prior strength
    extra_data = max(0, n - prior_strength)
    weight_learned = min(0.7, extra_data / 50.0)  # caps at 0.7 after 50 examples
    blended = (1 - weight_learned) * registry_q + weight_learned * learned_q

    return round(max(0.0, min(1.0, blended)), 4)


def get_all_states() -> list[dict]:
    """Return all states as dicts for the /api/predictor endpoint."""
    with _LOCK:
        return [
            {
                "step_type": st,
                "model": model,
                "mean": round(state.mean, 4),
                "uncertainty": round(state.uncertainty, 4),
                "alpha": round(state.alpha, 3),
                "beta": round(state.beta, 3),
                "n": round(state.alpha + state.beta, 1),
            }
            for (st, model), state in _STATE.items()
        ]


def reset_state(step_type: str | None = None, model_id: str | None = None) -> None:
    """Reset state (to prior) for a specific (step_type, model) or all."""
    with _LOCK:
        if step_type and model_id:
            _STATE.pop((step_type, model_id), None)
        else:
            _STATE.clear()
