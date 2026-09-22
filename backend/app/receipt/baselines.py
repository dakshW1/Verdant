"""
Baseline comparisons for the Carbon Receipt (Phase 2).

Three baselines:
  - naive: always choose the largest (L-tier) model on the default cloud site
  - fastest: always choose the M-tier model (best latency/quality tradeoff)
  - smallest: always choose the S-tier model on the default cloud site

IMPORTANT (regression fix): baselines MUST be computed with the exact same
DAG-respecting start-time scheduling and the exact same real carbon-intensity
forecast lookup that the real optimizer (`scheduler.greedy`) uses. Using a
flat placeholder CI made "naive" artificially cheaper or dearer than it
would really be, which let an optimized plan look like it used *more*
carbon than naive even when it never actually did (see
tests/test_carbon_invariant.py). `build_fixed_model_plan` is the shared
building block: it pins every step to one (model, site) pair but otherwise
schedules and prices it exactly like the real planner would.
"""
from __future__ import annotations

import logging
import time as _time

from app.config import get_models_registry, get_sites_registry
from app.dag.cpm import compute_cpm
from app.profiles.cost import estimate_cost
from app.profiles.energy import estimate_energy
from app.profiles.latency import estimate_latency, estimate_tokens_in, estimate_tokens_out
from app.profiles.quality import estimate_quality_single
from app.schemas import ConfigOption, StepPlan, Totals, Workflow

logger = logging.getLogger(__name__)


def find_tier_model(tier: str) -> str:
    """Return the first Gemini model id registered for the given tier (S/M/L)."""
    models_reg = get_models_registry()
    all_models = models_reg.get("models", [])
    for m in all_models:
        if m.get("tier") == tier and m.get("provider") == "gemini":
            return m["id"]
    return all_models[0]["id"] if all_models else "medium"


def find_default_site() -> str:
    """Return the first non-device (cloud) site, matching the planner's default."""
    sites_reg = get_sites_registry()
    all_sites = sites_reg.get("sites", [])
    for s in all_sites:
        if s.get("device"):
            continue
        return s["id"]
    return all_sites[0]["id"] if all_sites else "gcp-mumbai"


async def build_fixed_model_plan(
    workflow: Workflow,
    model_id: str,
    site_id: str,
    start_ts: int,
    deadline_s: int | None = None,
) -> tuple[list[StepPlan], Totals]:
    """
    Build a plan that pins every step to (model_id, site_id, single mode),
    scheduled with real DAG dependencies (parallel branches start together,
    not summed sequentially) and priced with the real per-window carbon
    intensity forecast at each step's actual start time -- i.e. exactly how
    the real planner would schedule it, minus the model/site choice.

    Used both for the Carbon Receipt baselines and for the planner's
    no-worse-than-naive fallback (Section 7.8 invariant).
    """
    # Reuse the exact same topo-sort / CI-fetch / CI-lookup helpers the real
    # greedy planner uses, so there is no formula drift between "naive" and
    # "optimized".
    from app.scheduler.greedy import _build_topo, _get_ci, _ci_at_window

    topo_order, preds = _build_topo(workflow)
    step_map = {s.id: s for s in workflow.steps}

    sites_reg = get_sites_registry()
    site_to_zone = {s["id"]: s["zone"] for s in sites_reg.get("sites", [])}
    zone = site_to_zone.get(site_id, "IN-WE")
    forecast = await _get_ci(zone, start_ts)

    step_end: dict[str, int] = {}
    durations_wc: dict[str, int] = {}
    per_step: dict[str, dict] = {}

    total_cost = 0.0
    total_energy = 0.0
    total_carbon = 0.0
    total_carbon_robust = 0.0
    total_quality_weighted = 0.0
    omega_sum = 0.0

    for sid in topo_order:
        step = step_map[sid]
        pred_ends = [step_end[p] for p in step.depends_on if p in step_end]
        start_s = max([step.release_s] + pred_ends)

        tok_in = estimate_tokens_in(step.step_type, step.est_tokens_in)
        tok_out = estimate_tokens_out(step.step_type, step.est_tokens_out, step.max_tokens_out)
        dur_exp, dur_worst = estimate_latency(model_id, site_id, tok_in, tok_out)
        energy_exp, energy_worst = estimate_energy(model_id, site_id, tok_in, tok_out, dur_exp, dur_worst)
        cost = estimate_cost(model_id, tok_in, tok_out)
        quality = estimate_quality_single(step.step_type, model_id)
        ci = _ci_at_window(forecast, start_s)

        step_end[sid] = start_s + dur_exp
        durations_wc[sid] = dur_worst

        carbon_exp = energy_exp * ci / 1000.0
        carbon_robust = energy_worst * ci / 1000.0 * 1.1

        per_step[sid] = {
            "start_s": start_s, "dur_exp": dur_exp, "dur_worst": dur_worst,
            "energy_exp": energy_exp, "energy_worst": energy_worst, "cost": cost,
            "quality": quality, "ci": ci, "carbon_exp": carbon_exp,
            "carbon_robust": carbon_robust, "tok_in": tok_in, "tok_out": tok_out,
        }

        total_cost += cost
        total_energy += energy_exp
        total_carbon += carbon_exp
        total_carbon_robust += carbon_robust
        total_quality_weighted += step.omega * quality
        omega_sum += step.omega

    makespan = max(step_end.values()) if step_end else 0
    horizon = deadline_s if deadline_s is not None else makespan
    cpm_nodes = compute_cpm(topo_order, durations_wc, preds, horizon)

    step_plans: list[StepPlan] = []
    for sid in topo_order:
        d = per_step[sid]
        node = cpm_nodes.get(sid)
        opt = ConfigOption(
            step_id=sid, model=model_id, site=site_id, mode="single",
            escalate_model=None, verifier_model=model_id,
            dur_expected_s=d["dur_exp"], dur_worstcase_s=d["dur_worst"],
            energy_wh=d["energy_exp"], energy_wh_worst=d["energy_worst"],
            cost_usd=d["cost"], quality=d["quality"], p_accept=None,
            tokens_in=d["tok_in"], tokens_out=d["tok_out"],
        )
        step_plans.append(StepPlan(
            step_id=sid,
            option=opt,
            start_s=d["start_s"],
            slack_s=node.slack if node else 0,
            is_critical=node.is_critical if node else True,
            carbon_g_expected=round(d["carbon_exp"], 4),
            carbon_g_robust=round(d["carbon_robust"], 4),
            ci_g_per_kwh=round(d["ci"], 2),
            rationale=f"Fixed baseline: always {model_id} @ {site_id}, no cascade or deferral.",
        ))

    avg_quality = total_quality_weighted / omega_sum if omega_sum > 0 else 0.5

    totals = Totals(
        makespan_s=makespan,
        cost_usd=round(total_cost, 6),
        energy_wh=round(total_energy, 6),
        carbon_g=round(total_carbon, 4),
        carbon_g_robust=round(total_carbon_robust, 4),
        quality=round(avg_quality, 4),
    )
    return step_plans, totals


async def compute_baselines(workflow: Workflow, start_ts: int | None = None) -> dict[str, Totals]:
    """
    Compute the three standard baselines for the given workflow, scheduled
    and priced with the exact same DAG-aware logic and real carbon-intensity
    forecast as the actual planner, so comparisons against an optimized plan
    are apples-to-apples.
    """
    if start_ts is None:
        start_ts = int(_time.time())

    large_model = find_tier_model("L")
    medium_model = find_tier_model("M")
    small_model = find_tier_model("S")
    default_site = find_default_site()

    _, naive = await build_fixed_model_plan(workflow, large_model, default_site, start_ts)
    _, fastest = await build_fixed_model_plan(workflow, medium_model, default_site, start_ts)
    _, smallest = await build_fixed_model_plan(workflow, small_model, default_site, start_ts)

    return {
        "naive": naive,
        "fastest": fastest,
        "smallest": smallest,
    }
