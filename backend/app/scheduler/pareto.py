"""
Pareto frontier solver (Phase 4).

Sweeps the carbon/latency trade-off space by solving CP-SAT with varying
weight vectors. Returns a set of non-dominated (Pareto-optimal) Totals points.

Uses ThreadPoolExecutor since OR-Tools releases the GIL.
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from app.schemas import Constraints, PlanRequest, Totals, Weights

logger = logging.getLogger(__name__)

_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pareto")

# Sweep points: (carbon_weight, latency_weight) pairs summing with fixed cost+energy+quality
_SWEEP_POINTS = [
    (0.8, 0.05),
    (0.6, 0.2),
    (0.4, 0.4),
    (0.2, 0.6),
    (0.05, 0.8),
    (0.3, 0.3),
    (0.1, 0.7),
    (0.7, 0.1),
]


async def compute_pareto(request: PlanRequest) -> list[Totals]:
    """
    Compute the Pareto frontier by solving with multiple weight vectors.

    Returns a list of non-dominated Totals points (carbon vs latency trade-off).
    """
    import time as _t
    start_ts = int(_t.time())

    results: list[Totals] = []

    async def _solve_one(carbon_w: float, lat_w: float) -> Totals | None:
        # Remaining weight split between cost, energy, quality
        remaining = max(0.0, 1.0 - carbon_w - lat_w)
        weights = Weights(
            carbon=carbon_w,
            latency=lat_w,
            cost=remaining * 0.3,
            energy=remaining * 0.3,
            quality=remaining * 0.4,
        )
        try:
            from app.scheduler.cpsat import cpsat_plan
            _, totals = await cpsat_plan(
                request.workflow,
                request.constraints,
                weights,
                start_ts,
            )
            return totals
        except Exception as exc:
            logger.debug(
                "Pareto point (C=%.2f, L=%.2f) CP-SAT unavailable (%s) — falling back to greedy",
                carbon_w, lat_w, exc,
            )
            try:
                from app.scheduler.greedy import greedy_plan
                _, totals = await greedy_plan(
                    request.workflow,
                    request.constraints,
                    weights,
                    start_ts,
                )
                return totals
            except Exception as exc2:
                logger.debug("Pareto point (C=%.2f, L=%.2f) greedy fallback also failed: %s", carbon_w, lat_w, exc2)
                return None

    tasks = [_solve_one(c, l) for c, l in _SWEEP_POINTS]
    sweep_results = await asyncio.gather(*tasks)

    for r in sweep_results:
        if r is not None:
            results.append(r)

    # Prune dominated points
    pareto = _prune_dominated(results)
    # Sort by carbon ascending
    pareto.sort(key=lambda t: t.carbon_g)
    return pareto


def _prune_dominated(points: list[Totals]) -> list[Totals]:
    """
    Remove dominated points (carbon ≥ other AND makespan ≥ other).
    A point is non-dominated if no other point is strictly better in all objectives.
    """
    if not points:
        return []

    pareto: list[Totals] = []
    for p in points:
        dominated = False
        for q in points:
            if q is p:
                continue
            # q dominates p if q is strictly better in at least one dim and no worse in all
            if q.carbon_g <= p.carbon_g and q.makespan_s <= p.makespan_s:
                if q.carbon_g < p.carbon_g or q.makespan_s < p.makespan_s:
                    dominated = True
                    break
        if not dominated:
            pareto.append(p)

    return pareto
