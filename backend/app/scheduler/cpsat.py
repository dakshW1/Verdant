"""
CP-SAT joint boolean scheduler (Phase 4).

Formulates the scheduling problem as a CP-SAT MIP:
  - Boolean variable x[step, option] = 1 iff option is chosen for step
  - Integer variable start[step] = planned start time (seconds)
  - Objective: minimize weighted sum of latency + cost + energy + carbon - quality
  - Constraints:
      * Exactly one option per step
      * Dependency ordering: start[j] >= start[i] + dur[i] for all (i→j) edges
      * Deadline: start[step] + dur[step] <= deadline_s
      * Quality floor: quality[chosen option] >= quality_floor per step
      * (optional) Carbon budget
      * (optional) Cost budget

Integer scaling: SC = 10_000 to convert floats to integers.
Pareto: solve repeatedly sweeping carbon/latency trade-off on the Pareto frontier.
"""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from app.profiles.options import build_options
from app.scheduler.greedy import _build_topo, _get_ci
from app.schemas import (
    ConfigOption,
    Constraints,
    StepPlan,
    Totals,
    Weights,
    Workflow,
)

logger = logging.getLogger(__name__)

SC = 10_000  # integer scaling constant
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cpsat")


def _solve_cpsat(
    topo_order: list[str],
    preds: dict[str, list[str]],
    step_options: dict[str, list[ConfigOption]],
    ci_map: dict[str, float],          # step_id → CI gCO2e/kWh at planned window
    constraints: Constraints,
    weights: Weights,
    step_map: dict,
) -> tuple[dict[str, ConfigOption], dict[str, int]] | None:
    """
    Run CP-SAT. Returns (chosen_options, start_times) or None if infeasible.
    This function is CPU-bound and must be called in a thread pool.
    """
    from ortools.sat.python import cp_model  # type: ignore

    model = cp_model.CpModel()

    # ── Decision variables ───────────────────────────────────────────────
    # x[step_id][opt_idx] = BoolVar
    x: dict[str, list] = {}
    for sid in topo_order:
        opts = step_options.get(sid, [])
        x[sid] = [model.new_bool_var(f"x_{sid}_{i}") for i in range(len(opts))]

    # start[step_id] = IntVar in [0, deadline_s]
    deadline = constraints.deadline_s
    start: dict[str, object] = {}
    for sid in topo_order:
        start[sid] = model.new_int_var(0, deadline, f"start_{sid}")

    # ── Exactly-one constraint per step ─────────────────────────────────
    for sid in topo_order:
        model.add_exactly_one(x[sid])

    # ── Duration based on chosen option ─────────────────────────────────
    # dur[step] = sum(x[sid][i] * dur_expected_s[i])
    # We encode this as: start[j] >= start[i] + chosen_dur[i] for deps
    # Use a linearized form with aux var: chosen_dur[sid]
    chosen_dur: dict[str, object] = {}
    for sid in topo_order:
        opts = step_options.get(sid, [])
        if not opts:
            chosen_dur[sid] = model.new_int_var(1, deadline, f"dur_{sid}")
            continue
        max_dur = max(o.dur_worstcase_s for o in opts)
        d = model.new_int_var(1, max(max_dur, 1), f"dur_{sid}")
        chosen_dur[sid] = d
        model.add(d == sum(
            x[sid][i] * opts[i].dur_worstcase_s for i in range(len(opts))
        ))

    # ── Dependency ordering ──────────────────────────────────────────────
    for sid in topo_order:
        for pred_id in preds.get(sid, []):
            if pred_id in start and sid in start:
                model.add(start[sid] >= start[pred_id] + chosen_dur[pred_id])

    # ── Deadline constraint ──────────────────────────────────────────────
    for sid in topo_order:
        model.add(start[sid] + chosen_dur[sid] <= deadline)

    # ── Quality floor per step ───────────────────────────────────────────
    for sid in topo_order:
        opts = step_options.get(sid, [])
        step = step_map.get(sid)
        if step is None or not opts:
            continue
        qfloor = max(step.min_quality, constraints.quality_floor)
        qfloor_sc = int(qfloor * SC)
        # sum(x[sid][i] * quality[i] * SC) >= qfloor_sc
        model.add(
            sum(x[sid][i] * int(opts[i].quality * SC) for i in range(len(opts))) >= qfloor_sc
        )

    # ── Objective ────────────────────────────────────────────────────────
    from app.scheduler.objective import normalize_weights
    wn = normalize_weights(weights)

    obj_terms = []
    for sid in topo_order:
        opts = step_options.get(sid, [])
        if not opts:
            continue
        ci = ci_map.get(sid, 400.0)
        for i, opt in enumerate(opts):
            # Carbon = energy_wh * CI / 1000  (gCO2e)
            carbon_sc = int(opt.energy_wh * ci / 1000.0 * SC)
            lat_sc = int(opt.dur_expected_s / deadline * SC)
            cost_sc = int(opt.cost_usd * 1e6)          # scale cost to microdollars
            quality_sc = int(opt.quality * SC)

            # Composite: minimize lat + cost + carbon - quality (all positive)
            composite = (
                int(wn["latency"] * lat_sc)
                + int(wn["cost"] * cost_sc)
                + int(wn["carbon"] * carbon_sc)
                - int(wn["quality"] * quality_sc)
            )
            obj_terms.append(composite * x[sid][i])

    model.minimize(sum(obj_terms))

    # ── Solve ─────────────────────────────────────────────────────────────
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 25.0
    solver.parameters.num_workers = 2
    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    # ── Extract solution ─────────────────────────────────────────────────
    chosen: dict[str, ConfigOption] = {}
    starts: dict[str, int] = {}
    for sid in topo_order:
        opts = step_options.get(sid, [])
        for i, opt in enumerate(opts):
            if solver.value(x[sid][i]):
                chosen[sid] = opt
                break
        starts[sid] = int(solver.value(start[sid]))

    return chosen, starts


async def cpsat_plan(
    workflow: Workflow,
    constraints: Constraints,
    weights: Weights,
    start_ts: int,
) -> tuple[list[StepPlan], Totals]:
    """
    CP-SAT planner entry point. Falls back to greedy on solver failure.
    """
    from app.config import get_sites_registry
    from app.scheduler.explain import explain_step
    from app.dag.cpm import compute_cpm

    topo_order, preds = _build_topo(workflow)
    step_map = {s.id: s for s in workflow.steps}

    # Pre-fetch CI
    sites_reg = get_sites_registry()
    site_to_zone = {s["id"]: s["zone"] for s in sites_reg.get("sites", [])}
    unique_zones = list({s["zone"] for s in sites_reg.get("sites", [])})
    forecasts = await asyncio.gather(*[_get_ci(z, start_ts) for z in unique_zones])
    zone_fc = dict(zip(unique_zones, forecasts))

    # Build options for all steps
    step_options: dict[str, list[ConfigOption]] = {}
    for sid in topo_order:
        step_options[sid] = build_options(step_map[sid], constraints)

    # CI per step: use first option's site as representative
    ci_map: dict[str, float] = {}
    for sid in topo_order:
        opts = step_options.get(sid, [])
        if opts:
            zone = site_to_zone.get(opts[0].site, "IN-WE")
            fc = zone_fc.get(zone)
            ci_map[sid] = fc.mean[0] if fc else 400.0
        else:
            ci_map[sid] = 400.0

    # Run CP-SAT in thread pool (CPU-bound)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _EXECUTOR,
        _solve_cpsat,
        topo_order, preds, step_options, ci_map, constraints, weights, step_map,
    )

    if result is None:
        logger.warning("CP-SAT infeasible — falling back to greedy")
        from app.scheduler.greedy import greedy_plan
        return await greedy_plan(workflow, constraints, weights, start_ts)

    chosen, starts = result

    # Build CPM for slack/critical
    durations_wc = {sid: chosen[sid].dur_worstcase_s for sid in topo_order if sid in chosen}
    cpm_nodes = compute_cpm(topo_order, durations_wc, preds, constraints.deadline_s)

    step_plans: list[StepPlan] = []
    for sid in topo_order:
        if sid not in chosen:
            continue
        opt = chosen[sid]
        start_s = starts.get(sid, 0)
        ci = ci_map.get(sid, 400.0)
        node = cpm_nodes.get(sid)
        slack_s = node.slack if node else 0
        is_critical = node.is_critical if node else True

        carbon_exp = opt.energy_wh * ci / 1000.0
        carbon_robust = opt.energy_wh_worst * ci / 1000.0 * (1 + constraints.robust_z * 0.1)

        rationale = explain_step(
            step=step_map[sid], option=opt, start_s=start_s,
            slack_s=slack_s, is_critical=is_critical, ci_g_per_kwh=ci,
        )
        step_plans.append(StepPlan(
            step_id=sid, option=opt, start_s=start_s, slack_s=slack_s,
            is_critical=is_critical, carbon_g_expected=round(carbon_exp, 4),
            carbon_g_robust=round(carbon_robust, 4), ci_g_per_kwh=round(ci, 2),
            rationale=rationale,
        ))

    # Totals
    makespan = max((starts[sid] + chosen[sid].dur_expected_s for sid in topo_order if sid in chosen), default=0)
    omega_sum = sum(step_map[sid].omega for sid in topo_order)
    total_quality = (
        sum(step_map[sid].omega * chosen[sid].quality for sid in topo_order if sid in chosen) / omega_sum
        if omega_sum > 0 else 0.0
    )

    totals = Totals(
        makespan_s=makespan,
        cost_usd=round(sum(chosen[sid].cost_usd for sid in topo_order if sid in chosen), 6),
        energy_wh=round(sum(chosen[sid].energy_wh for sid in topo_order if sid in chosen), 6),
        carbon_g=round(sum(sp.carbon_g_expected for sp in step_plans), 4),
        carbon_g_robust=round(sum(sp.carbon_g_robust for sp in step_plans), 4),
        quality=round(total_quality, 4),
    )

    return step_plans, totals
