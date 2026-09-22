"""
Value of Information (VoI) cascade decision module (Phase 3).

Decides whether to escalate a step to the larger model based on:
  1. Verifier score vs. tau threshold
  2. Value of Information: E[benefit of escalation] > E[cost of escalation]

VoI formula (simplified from Section 9 of AGENTS.md):
  VoI = (1 - p_accept) * (q_large - q_small) * omega
  Cost = (energy_large - energy_small) * CI / 1000 + (cost_large - cost_small)

Escalate if: verifier_score < tau AND (step.cascade_allowed) AND
             (VoI / max_voi >= cascade_rho OR remaining_slack > 0)
"""
from __future__ import annotations

import logging

from app.config import get_step_types_registry
from app.schemas import ConfigOption, Step

logger = logging.getLogger(__name__)


def should_escalate(
    step: Step,
    option: ConfigOption,
    verifier_score: float,
    remaining_slack_s: int,
    ci_g_per_kwh: float,
) -> bool:
    """
    Decide whether to escalate from small to large model.

    Returns True if escalation is warranted.
    """
    tau = float(get_step_types_registry().get("verifier_tau", 0.7))

    # If verifier passes, no escalation needed
    if verifier_score >= tau:
        return False

    # If cascade not configured on this option, cannot escalate
    if option.mode != "cascade" or option.escalate_model is None:
        return False

    # If no cascade on step, skip
    if not step.cascade_allowed:
        return False

    # Always escalate if below quality floor (step-level)
    if verifier_score < step.min_quality:
        logger.debug("Step %s: score %.2f < min_quality %.2f → escalating", step.id, verifier_score, step.min_quality)
        return True

    # VoI decision: is the benefit worth the extra cost?
    voi = _compute_voi(step, option, ci_g_per_kwh)
    cascade_rho = float(get_step_types_registry().get("cascade_rho", 0.93))

    # Escalate if VoI is positive and quality gap warrants it
    if voi > 0:
        logger.debug(
            "Step %s: score %.2f < tau %.2f, VoI=%.4f → escalating", step.id, verifier_score, tau, voi
        )
        return True

    logger.debug(
        "Step %s: score %.2f < tau %.2f but VoI=%.4f ≤ 0 → accepting small output",
        step.id, verifier_score, tau, voi,
    )
    return False


def _compute_voi(step: Step, option: ConfigOption, ci_g_per_kwh: float) -> float:
    """
    Simplified VoI = quality_gain * importance - carbon_penalty * carbon_weight.

    quality_gain = (1 - p_accept) * (assumed q_large - q_small)
    carbon_penalty = extra energy * CI (for the escalation call)
    """
    from app.config import get_model_by_id
    from app.profiles.quality import estimate_quality_single

    p_accept = option.p_accept or 0.65
    q_small = estimate_quality_single(step.step_type, option.model)

    escalate_model = option.escalate_model
    if escalate_model is None:
        return 0.0

    q_large = estimate_quality_single(step.step_type, escalate_model)

    quality_gain = (1 - p_accept) * (q_large - q_small) * step.omega

    # Extra energy cost for escalation (rough: difference in energy)
    extra_energy_wh = max(0.0, option.energy_wh_worst - option.energy_wh)
    carbon_penalty = extra_energy_wh * ci_g_per_kwh / 1000.0

    # Simple VoI: positive if quality gain outweighs carbon cost (using a fixed exchange rate)
    # Exchange rate: 1 quality unit ≈ 10 gCO2e worth tolerating
    quality_in_carbon_units = quality_gain * 10.0
    return quality_in_carbon_units - carbon_penalty
