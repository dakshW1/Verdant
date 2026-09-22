"""
ConfigOption builder + pruning (Phase 1).

Generates the full set of feasible (model, site, mode) combinations for each
step in a workflow, subject to:
  - site whitelist (step.allowed_sites, constraints.allowed_sites)
  - cascade_allowed per step
  - quality floor per step (step.min_quality)
  - cascade only when step.cascade_allowed and constraints.allow_cascade
"""
from __future__ import annotations

from app.config import get_models_registry, get_sites_registry
from app.profiles.cost import estimate_cost
from app.profiles.energy import estimate_energy
from app.profiles.latency import estimate_latency, estimate_tokens_in, estimate_tokens_out
from app.profiles.quality import (
    estimate_p_accept,
    estimate_quality_cascade,
    estimate_quality_single,
)
from app.schemas import ConfigOption, Constraints, Step


def build_options(step: Step, constraints: Constraints) -> list[ConfigOption]:
    """
    Build all feasible ConfigOption rows for a step given constraints.
    Called once per step during planning.
    """
    models_reg = get_models_registry()
    sites_reg = get_sites_registry()

    all_models = models_reg.get("models", [])
    all_sites = sites_reg.get("sites", [])

    # Site whitelist = intersection of step-level and constraint-level whitelists
    allowed_sites: set[str] | None = None
    if constraints.allowed_sites:
        allowed_sites = set(constraints.allowed_sites)
    if step.allowed_sites:
        step_sites = set(step.allowed_sites)
        allowed_sites = step_sites if allowed_sites is None else allowed_sites & step_sites

    tokens_in = estimate_tokens_in(step.step_type, step.est_tokens_in)
    tokens_out = estimate_tokens_out(step.step_type, step.est_tokens_out, step.max_tokens_out)

    options: list[ConfigOption] = []

    for site in all_sites:
        site_id: str = site["id"]
        if allowed_sites is not None and site_id not in allowed_sites:
            continue

        for model in all_models:
            model_id: str = model["id"]

            # ── Single mode ──────────────────────────────────────────────
            quality = estimate_quality_single(step.step_type, model_id)
            if quality >= step.min_quality:
                dur_exp, dur_worst = estimate_latency(model_id, site_id, tokens_in, tokens_out)
                energy_exp, energy_worst = estimate_energy(
                    model_id, site_id, tokens_in, tokens_out, dur_exp, dur_worst
                )
                cost = estimate_cost(model_id, tokens_in, tokens_out)

                options.append(ConfigOption(
                    step_id=step.id,
                    model=model_id,
                    site=site_id,
                    mode="single",
                    escalate_model=None,
                    verifier_model=model_id,
                    dur_expected_s=dur_exp,
                    dur_worstcase_s=dur_worst,
                    energy_wh=energy_exp,
                    energy_wh_worst=energy_worst,
                    cost_usd=cost,
                    quality=quality,
                    p_accept=None,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                ))

            # ── Cascade mode ─────────────────────────────────────────────
            if not step.cascade_allowed or not constraints.allow_cascade:
                continue
            if model.get("tier") != "S":
                continue  # cascade uses small as the first stage

            # Find the medium or large escalation model (pick smallest L-tier)
            escalate_model = _pick_escalation_model(all_models, model_id)
            if escalate_model is None:
                continue

            q_casc, p_accept = estimate_quality_cascade(
                step.step_type, model_id, escalate_model
            )
            if q_casc < step.min_quality:
                continue

            # Energy/latency: expected uses small stats; worst-case uses large stats
            dur_exp_s, dur_worst_s = estimate_latency(model_id, site_id, tokens_in, tokens_out)
            dur_exp_l, dur_worst_l = estimate_latency(escalate_model, site_id, tokens_in, tokens_out)
            # cascade expected: p_accept * small_dur + (1-p_accept) * (small+large)_dur
            dur_exp_c = round(
                p_accept * dur_exp_s + (1 - p_accept) * (dur_exp_s + dur_exp_l)
            )
            dur_worst_c = dur_worst_s + dur_worst_l  # assume escalation always happens

            energy_s_exp, energy_s_worst = estimate_energy(
                model_id, site_id, tokens_in, tokens_out, dur_exp_s, dur_worst_s
            )
            energy_l_exp, energy_l_worst = estimate_energy(
                escalate_model, site_id, tokens_in, tokens_out, dur_exp_l, dur_worst_l
            )
            energy_c_exp = round(
                p_accept * energy_s_exp + (1 - p_accept) * (energy_s_exp + energy_l_exp), 6
            )
            energy_c_worst = round(energy_s_worst + energy_l_worst, 6)

            cost_s = estimate_cost(model_id, tokens_in, tokens_out)
            cost_l = estimate_cost(escalate_model, tokens_in, tokens_out)
            cost_c = round(p_accept * cost_s + (1 - p_accept) * (cost_s + cost_l), 8)

            options.append(ConfigOption(
                step_id=step.id,
                model=model_id,
                site=site_id,
                mode="cascade",
                escalate_model=escalate_model,
                verifier_model=model_id,
                dur_expected_s=dur_exp_c,
                dur_worstcase_s=dur_worst_c,
                energy_wh=energy_c_exp,
                energy_wh_worst=energy_c_worst,
                cost_usd=cost_c,
                quality=q_casc,
                p_accept=p_accept,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            ))

    return options


def _pick_escalation_model(all_models: list[dict], small_model_id: str) -> str | None:
    """Return the cheapest M-tier model as escalation target, or L-tier if no M."""
    m_tiers = [m for m in all_models if m.get("tier") == "M" and m["id"] != small_model_id]
    if m_tiers:
        return m_tiers[0]["id"]
    l_tiers = [m for m in all_models if m.get("tier") == "L" and m["id"] != small_model_id]
    if l_tiers:
        return l_tiers[0]["id"]
    return None
