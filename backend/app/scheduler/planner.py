"""
Planner facade (Phase 2) — POST /api/plan entry point.

Routes to:
  - greedy solver (Phase 2)
  - cpsat solver (Phase 4, stub for now)
  - auto: tries cpsat, falls back to greedy on timeout/error
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from app.schemas import (
    Constraints,
    PlanResult,
    SolverType,
    Totals,
    Weights,
    Workflow,
)

logger = logging.getLogger(__name__)


def _merge_preset(preset: str | None, weights: Weights | None) -> Weights:
    """Apply preset weight overrides on top of supplied weights."""
    base = weights or Weights()
    if preset is None:
        return base
    from app.config import get_weights_for_preset
    preset_w = get_weights_for_preset(preset)
    if preset_w is None:
        logger.warning("Unknown preset %r — using default weights", preset)
        return base
    return Weights(
        latency=preset_w.get("latency", base.latency),
        cost=preset_w.get("cost", base.cost),
        energy=preset_w.get("energy", base.energy),
        carbon=preset_w.get("carbon", base.carbon),
        quality=preset_w.get("quality", base.quality),
    )


async def plan(
    workflow: Workflow,
    constraints: Constraints,
    weights: Weights | None = None,
    preset: str | None = None,
    solver: SolverType = "auto",
) -> PlanResult:
    """
    Main planning entry point.

    Steps:
      1. Validate DAG
      2. Merge preset weights
      3. Get start_ts (now or parsed from constraints.start_time_iso)
      4. Dispatch to solver
      5. Compute baselines
      6. Persist plan to DB
      7. Return PlanResult
    """
    from app.dag.graph import validate_dag

    validation = validate_dag(workflow)
    if not validation.valid:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail={"errors": validation.errors})

    effective_weights = _merge_preset(preset, weights)

    # Determine start timestamp
    import time as _time
    if constraints.start_time_iso:
        import datetime
        try:
            dt = datetime.datetime.fromisoformat(constraints.start_time_iso.replace("Z", "+00:00"))
            start_ts = int(dt.timestamp())
        except ValueError:
            start_ts = int(_time.time())
    else:
        start_ts = int(_time.time())

    t0 = _time.monotonic()

    # Dispatch to solver
    if solver == "cpsat":
        step_plans, totals, actual_solver = await _run_cpsat(
            workflow, constraints, effective_weights, start_ts
        )
    elif solver == "auto":
        step_plans, totals, actual_solver = await _run_auto(
            workflow, constraints, effective_weights, start_ts
        )
    else:  # greedy
        step_plans, totals, actual_solver = await _run_greedy(
            workflow, constraints, effective_weights, start_ts
        )

    # Compute baselines — MUST use the same DAG-aware scheduling and real
    # carbon-intensity forecast as the solver above, or "naive" isn't a fair
    # yardstick (see app/receipt/baselines.py docstring).
    from app.receipt.baselines import build_fixed_model_plan, compute_baselines, find_default_site, find_tier_model
    baselines = await compute_baselines(workflow, start_ts)

    # ── Hard invariant: never return a plan with higher expected carbon than
    # naive, unless naive itself is infeasible (misses the deadline or the
    # quality floor). Naive is always a config the planner could have chosen,
    # so if the "optimized" result is dirtier, fall back to naive outright
    # rather than let a weighted objective (e.g. a fast/cheap preset) quietly
    # accept a dirtier plan. See tests/test_carbon_invariant.py.
    relaxations: list[dict] = []
    naive_totals = baselines["naive"]
    naive_feasible = (
        naive_totals.makespan_s <= constraints.deadline_s
        and naive_totals.quality >= constraints.quality_floor
    )
    if naive_feasible and totals.carbon_g > naive_totals.carbon_g + 1e-9:
        rejected_carbon_g = totals.carbon_g
        logger.warning(
            "Plan %s: %s-solver carbon (%.4fg) exceeded the naive baseline (%.4fg) — "
            "falling back to the naive configuration to preserve the no-worse-than-naive invariant.",
            workflow.id, actual_solver, rejected_carbon_g, naive_totals.carbon_g,
        )
        large_model = find_tier_model("L")
        default_site = find_default_site()
        step_plans, totals = await build_fixed_model_plan(
            workflow, large_model, default_site, start_ts, deadline_s=constraints.deadline_s,
        )
        relaxations.append({
            "constraint": "carbon_invariant",
            "note": (
                f"The weighted objective would have picked a plan using more carbon "
                f"({rejected_carbon_g}g) than always using the largest model "
                f"({naive_totals.carbon_g}g), so Verdant used the naive configuration instead."
            ),
        })

    solve_ms = round((_time.monotonic() - t0) * 1000)

    # Determine plan status
    if totals.makespan_s <= constraints.deadline_s:
        status = "optimal" if actual_solver == "cpsat" else "feasible"
    else:
        status = "relaxed"

    plan_id = str(uuid.uuid4())

    result = PlanResult(
        plan_id=plan_id,
        status=status,  # type: ignore
        steps=step_plans,
        totals=totals,
        baselines=baselines,
        relaxations=relaxations,
        pareto=[],
        solver=actual_solver,  # type: ignore
        solve_ms=solve_ms,
    )

    # Persist to DB
    _save_plan(plan_id, result, workflow)

    return result



async def _run_greedy(
    workflow: Workflow,
    constraints: Constraints,
    weights: Weights,
    start_ts: int,
) -> tuple:
    from app.scheduler.greedy import greedy_plan
    step_plans, totals = await greedy_plan(workflow, constraints, weights, start_ts)
    return step_plans, totals, "greedy"


async def _run_cpsat(
    workflow: Workflow,
    constraints: Constraints,
    weights: Weights,
    start_ts: int,
) -> tuple:
    """Phase 4 — stub: falls through to greedy."""
    try:
        from app.scheduler.cpsat import cpsat_plan
        step_plans, totals = await cpsat_plan(workflow, constraints, weights, start_ts)
        return step_plans, totals, "cpsat"
    except (ImportError, NotImplementedError):
        logger.info("CP-SAT not yet implemented — using greedy")
        return await _run_greedy(workflow, constraints, weights, start_ts)


async def _run_auto(
    workflow: Workflow,
    constraints: Constraints,
    weights: Weights,
    start_ts: int,
) -> tuple:
    """
    Try CP-SAT with a 30s timeout; fall back to greedy on timeout or import error.
    """
    try:
        result = await asyncio.wait_for(
            _run_cpsat(workflow, constraints, weights, start_ts),
            timeout=30.0,
        )
        return result
    except (asyncio.TimeoutError, Exception) as exc:
        logger.info("Auto: CP-SAT timed out or failed (%s) — using greedy", exc)
        return await _run_greedy(workflow, constraints, weights, start_ts)


def _save_plan(plan_id: str, result: PlanResult, workflow: Workflow | None = None) -> None:
    """Persist the plan to SQLite for later retrieval."""
    try:
        from app.db import save_plan
        save_plan(result, workflow)
    except Exception as exc:
        logger.warning("Could not persist plan %s: %s", plan_id, exc)

