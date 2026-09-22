"""
Greedy scheduler with slack reclamation (Phase 2).

Algorithm:
  1. Build ConfigOptions for all steps via profiles.options
  2. For each step in topological order:
     a. Get CI at the step's site and planned window
     b. Score all options via objective.score_options
     c. Pick the best option that satisfies:
        - step deadline (if any)
        - step min_quality floor
        - worst-case start + dur <= project deadline
     d. Assign start_s = max(release_s, max(pred.end_s))
  3. After assignment, run CPM to get slack/critical path
  4. Slack reclamation: if a non-critical step has slack,
     try to defer it to a lower-CI window (greedy improvement pass)
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict

from app.carbon.provider import get_carbon_provider
from app.dag.cpm import CPMNode, compute_cpm
from app.profiles.options import build_options
from app.scheduler.objective import score_options
from app.schemas import (
    CIForecast,
    ConfigOption,
    Constraints,
    Step,
    StepPlan,
    Totals,
    Weights,
    Workflow,
)

logger = logging.getLogger(__name__)

_WINDOW_S = 1800  # 30-min CI windows
_HORIZON_S = 86400  # 24h forecast


async def _get_ci(zone: str, start_ts: int) -> CIForecast:
    """Fetch CI forecast with caching."""
    from app.carbon.cache import get_cached, set_cached

    cached = get_cached(zone, start_ts, _HORIZON_S, _WINDOW_S)
    if cached:
        return cached
    provider = get_carbon_provider()
    forecast = await provider.forecast(zone, start_ts, _HORIZON_S, _WINDOW_S)
    set_cached(zone, start_ts, _HORIZON_S, _WINDOW_S, forecast)
    return forecast


def _ci_at_window(forecast: CIForecast, offset_s: int) -> float:
    """Get CI value at a given second offset from start_ts."""
    idx = min(offset_s // forecast.window_s, len(forecast.mean) - 1)
    return forecast.mean[idx]


def _build_topo(workflow: Workflow) -> tuple[list[str], dict[str, list[str]]]:
    """Return (topo_order, predecessors_map)."""
    from collections import deque

    step_map = {s.id: s for s in workflow.steps}
    in_degree: dict[str, int] = {s.id: 0 for s in workflow.steps}
    adj: dict[str, list[str]] = {s.id: [] for s in workflow.steps}

    for step in workflow.steps:
        for dep in step.depends_on:
            if dep in adj:
                adj[dep].append(step.id)
                in_degree[step.id] += 1

    queue = deque([sid for sid, deg in in_degree.items() if deg == 0])
    order: list[str] = []
    while queue:
        sid = queue.popleft()
        order.append(sid)
        for succ in adj[sid]:
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)

    preds: dict[str, list[str]] = {s.id: list(s.depends_on) for s in workflow.steps}
    return order, preds


async def greedy_plan(
    workflow: Workflow,
    constraints: Constraints,
    weights: Weights,
    start_ts: int,
) -> tuple[list[StepPlan], Totals]:
    """
    Run the greedy scheduling pass.

    Returns:
        (step_plans, totals)
    """
    topo_order, preds = _build_topo(workflow)
    step_map = {s.id: s for s in workflow.steps}

    # ── Pre-fetch CI for all unique zones ────────────────────────────────
    from app.config import get_sites_registry
    sites_reg = get_sites_registry()
    site_to_zone: dict[str, str] = {s["id"]: s["zone"] for s in sites_reg.get("sites", [])}

    zone_forecasts: dict[str, CIForecast] = {}
    unique_zones = list({s["zone"] for s in sites_reg.get("sites", [])})
    forecasts = await asyncio.gather(*[_get_ci(z, start_ts) for z in unique_zones])
    zone_forecasts = dict(zip(unique_zones, forecasts))

    # ── Greedy assignment ─────────────────────────────────────────────────
    step_end: dict[str, int] = {}   # step_id → actual end_s
    assignments: dict[str, tuple[ConfigOption, int, float]] = {}  # step_id → (option, start_s, ci)

    for sid in topo_order:
        step = step_map[sid]

        # Earliest start = max(release_s, predecessor ends)
        pred_ends = [step_end[p] for p in step.depends_on if p in step_end]
        earliest = max([step.release_s] + pred_ends)

        # Build options and filter by site whitelist
        options = build_options(step, constraints)
        if not options:
            logger.warning("No options for step %s — using fallback", sid)
            # Use the first available model/site combo regardless of quality floor
            from app.profiles.options import build_options as _bo
            from app.schemas import Constraints as C
            relaxed = C(
                deadline_s=constraints.deadline_s,
                quality_floor=0.0,
                allow_cascade=constraints.allow_cascade,
                allow_deferral=constraints.allow_deferral,
            )
            options = _bo(step, relaxed)
        if not options:
            raise ValueError(f"Cannot build any option for step '{sid}'")

        # Compute CI at the earliest_start window for each option's site
        def _ci_for_option(opt: ConfigOption, offset: int) -> float:
            zone = site_to_zone.get(opt.site, "IN-WE")
            fc = zone_forecasts.get(zone)
            if fc is None:
                return 400.0
            return _ci_at_window(fc, offset)

        # Score options using CI at each option's site at earliest start
        # Use the single best CI value per option for scoring
        ci_for_scoring = _ci_for_option(options[0], earliest)
        scored = score_options(options, weights, ci_for_scoring, constraints.robust_z)

        # Pick first option satisfying hard constraints
        chosen_opt: ConfigOption | None = None
        chosen_start = earliest
        chosen_ci = ci_for_scoring

        for opt, _ in scored:
            start_s = max(earliest, step.release_s)
            end_s = start_s + opt.dur_worstcase_s

            # Check project deadline
            if end_s > constraints.deadline_s:
                continue
            # Check per-step deadline
            if step.deadline_s is not None and end_s > step.deadline_s:
                continue
            # Check quality floor
            if opt.quality < max(step.min_quality, constraints.quality_floor):
                continue

            ci = _ci_for_option(opt, start_s)
            chosen_opt = opt
            chosen_start = start_s
            chosen_ci = ci
            break

        if chosen_opt is None:
            # Relax deadline — pick best quality option regardless
            logger.warning("Step %s: no option within deadline; picking best-quality option", sid)
            chosen_opt = max(options, key=lambda o: o.quality)
            chosen_start = earliest
            chosen_ci = _ci_for_option(chosen_opt, earliest)

        step_end[sid] = chosen_start + chosen_opt.dur_expected_s
        assignments[sid] = (chosen_opt, chosen_start, chosen_ci)

    # ── Slack reclamation pass ────────────────────────────────────────────
    # Re-run CPM and try to defer non-critical steps to lower-CI windows
    durations_wc = {sid: assignments[sid][0].dur_worstcase_s for sid in topo_order}
    cpm_nodes = compute_cpm(topo_order, durations_wc, preds, constraints.deadline_s)

    assignments = _reclaim_slack(
        topo_order, assignments, cpm_nodes, zone_forecasts, site_to_zone,
        step_map, step_end, preds, constraints, weights,
    )

    # ── Build StepPlan list ───────────────────────────────────────────────
    step_plans: list[StepPlan] = []
    for sid in topo_order:
        opt, start_s, ci = assignments[sid]
        node = cpm_nodes.get(sid)
        slack_s = node.slack if node else 0
        is_critical = node.is_critical if node else True

        energy_wh = opt.energy_wh
        carbon_exp = energy_wh * ci / 1000.0
        carbon_robust = (
            opt.energy_wh_worst * ci / 1000.0 * (1 + constraints.robust_z * 0.1)
        )

        from app.scheduler.explain import explain_step
        rationale = explain_step(
            step=step_map[sid],
            option=opt,
            start_s=start_s,
            slack_s=slack_s,
            is_critical=is_critical,
            ci_g_per_kwh=ci,
        )

        step_plans.append(StepPlan(
            step_id=sid,
            option=opt,
            start_s=start_s,
            slack_s=slack_s,
            is_critical=is_critical,
            carbon_g_expected=round(carbon_exp, 4),
            carbon_g_robust=round(carbon_robust, 4),
            ci_g_per_kwh=round(ci, 2),
            rationale=rationale,
        ))

    # ── Compute totals ────────────────────────────────────────────────────
    makespan = max(a[1] + a[0].dur_expected_s for a in assignments.values())
    total_cost = sum(a[0].cost_usd for a in assignments.values())
    total_energy = sum(a[0].energy_wh for a in assignments.values())
    total_carbon = sum(sp.carbon_g_expected for sp in step_plans)
    total_carbon_robust = sum(sp.carbon_g_robust for sp in step_plans)

    # Weighted quality (by omega)
    omega_sum = sum(step_map[sid].omega for sid in topo_order)
    if omega_sum > 0:
        total_quality = sum(
            step_map[sid].omega * assignments[sid][0].quality
            for sid in topo_order
        ) / omega_sum
    else:
        total_quality = sum(a[0].quality for a in assignments.values()) / max(len(assignments), 1)

    totals = Totals(
        makespan_s=makespan,
        cost_usd=round(total_cost, 6),
        energy_wh=round(total_energy, 6),
        carbon_g=round(total_carbon, 4),
        carbon_g_robust=round(total_carbon_robust, 4),
        quality=round(total_quality, 4),
    )

    return step_plans, totals


def _reclaim_slack(
    topo_order: list[str],
    assignments: dict[str, tuple[ConfigOption, int, float]],
    cpm_nodes: dict[str, CPMNode],
    zone_forecasts: dict[str, CIForecast],
    site_to_zone: dict[str, str],
    step_map: dict[str, Step],
    step_end: dict[str, int],
    preds: dict[str, list[str]],
    constraints: Constraints,
    weights: Weights,
) -> dict[str, tuple[ConfigOption, int, float]]:
    """
    For each non-critical step, check if deferring it to a lower-CI window
    within its slack window reduces carbon without violating deadlines.
    Updates assignments in-place and returns the modified dict.
    """
    if not constraints.allow_deferral:
        return assignments

    for sid in topo_order:
        node = cpm_nodes.get(sid)
        if node is None or node.is_critical or node.slack <= 0:
            continue

        opt, start_s, ci = assignments[sid]
        zone = site_to_zone.get(opt.site, "IN-WE")
        fc = zone_forecasts.get(zone)
        if fc is None:
            continue

        # Search windows within slack
        best_start = start_s
        best_ci = ci
        window_s = fc.window_s

        for delta in range(0, node.slack + 1, window_s):
            candidate_start = start_s + delta
            candidate_end = candidate_start + opt.dur_worstcase_s
            if candidate_end > constraints.deadline_s:
                break
            step = step_map[sid]
            if step.deadline_s is not None and candidate_end > step.deadline_s:
                break
            candidate_ci = _ci_at_window(fc, candidate_start)
            if candidate_ci < best_ci:
                best_ci = candidate_ci
                best_start = candidate_start

        if best_start != start_s:
            logger.debug(
                "Slack reclaim: step %s deferred +%ds → CI %.1f→%.1f gCO2e/kWh",
                sid, best_start - start_s, ci, best_ci,
            )
            assignments[sid] = (opt, best_start, best_ci)

    return assignments
