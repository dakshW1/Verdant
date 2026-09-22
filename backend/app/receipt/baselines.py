"""
Baseline comparisons for the Carbon Receipt (Phase 2).

Three baselines:
  - naive: always choose the largest (L-tier) model on the highest-CI local/default site
  - fastest: always choose the option with minimum expected latency (ignoring carbon)
  - smallest: always choose the S-tier model on the default cloud site

These let the Receipt compute: carbon_saved_vs_naive, cost_delta, latency_delta.
"""
from __future__ import annotations

import logging

from app.config import get_models_registry, get_sites_registry
from app.profiles.cost import estimate_cost
from app.profiles.energy import estimate_energy
from app.profiles.latency import estimate_latency, estimate_tokens_in, estimate_tokens_out
from app.profiles.quality import estimate_quality_single
from app.schemas import Constraints, Step, Totals, Weights, Workflow

logger = logging.getLogger(__name__)

_WINDOW_S = 1800
_DEFAULT_CI = 400.0  # gCO2e/kWh — used for baselines (India average-ish)


def _step_totals_for_model(
    steps: list[Step],
    model_id: str,
    site_id: str,
    ci: float,
) -> Totals:
    """Compute totals assuming all steps use (model_id, site_id, single mode)."""
    makespan = 0
    total_cost = 0.0
    total_energy = 0.0
    total_carbon = 0.0
    total_carbon_robust = 0.0
    total_quality_weighted = 0.0
    omega_sum = 0.0

    # Sequential worst-case makespan (conservative baseline)
    for step in steps:
        tok_in = estimate_tokens_in(step.step_type, step.est_tokens_in)
        tok_out = estimate_tokens_out(step.step_type, step.est_tokens_out, step.max_tokens_out)
        dur_exp, dur_worst = estimate_latency(model_id, site_id, tok_in, tok_out)
        energy_exp, energy_worst = estimate_energy(model_id, site_id, tok_in, tok_out, dur_exp, dur_worst)
        cost = estimate_cost(model_id, tok_in, tok_out)
        quality = estimate_quality_single(step.step_type, model_id)

        makespan += dur_exp
        total_cost += cost
        total_energy += energy_exp
        carbon_exp = energy_exp * ci / 1000.0
        total_carbon += carbon_exp
        total_carbon_robust += energy_worst * ci / 1000.0 * 1.1
        total_quality_weighted += step.omega * quality
        omega_sum += step.omega

    avg_quality = total_quality_weighted / omega_sum if omega_sum > 0 else 0.5

    return Totals(
        makespan_s=makespan,
        cost_usd=round(total_cost, 6),
        energy_wh=round(total_energy, 6),
        carbon_g=round(total_carbon, 4),
        carbon_g_robust=round(total_carbon_robust, 4),
        quality=round(avg_quality, 4),
    )


def compute_baselines(workflow: Workflow, ci: float = _DEFAULT_CI) -> dict[str, Totals]:
    """
    Compute the three standard baselines for the given workflow.

    Returns dict with keys: "naive", "fastest", "smallest".
    """
    models_reg = get_models_registry()
    sites_reg = get_sites_registry()

    all_models = models_reg.get("models", [])
    all_sites = sites_reg.get("sites", [])

    # Find tier representatives
    def _find_model(tier: str) -> str:
        for m in all_models:
            if m.get("tier") == tier and m.get("provider") == "gemini":
                return m["id"]
        return all_models[0]["id"] if all_models else "medium"

    def _find_site(exclude_device: bool = True) -> str:
        for s in all_sites:
            if exclude_device and s.get("device"):
                continue
            return s["id"]
        return all_sites[0]["id"] if all_sites else "gcp-mumbai"

    large_model = _find_model("L")
    medium_model = _find_model("M")
    small_model = _find_model("S")
    default_site = _find_site()

    steps = workflow.steps

    # naive: largest model, default cloud site
    naive = _step_totals_for_model(steps, large_model, default_site, ci)

    # fastest: medium model (best latency/quality tradeoff), default site
    fastest = _step_totals_for_model(steps, medium_model, default_site, ci)

    # smallest: smallest model, default site
    smallest = _step_totals_for_model(steps, small_model, default_site, ci)

    return {
        "naive": naive,
        "fastest": fastest,
        "smallest": smallest,
    }
