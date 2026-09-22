"""
Regression tests for Bug 1: an optimized plan must never report higher
expected carbon than the naive baseline, unless naive itself is infeasible.

Root cause (fixed in app/receipt/baselines.py + app/scheduler/planner.py):
`compute_baselines()` priced "naive" using a flat placeholder carbon
intensity (400 gCO2e/kWh) instead of the real per-site/per-time synthetic
forecast the actual scheduler uses, and assumed a purely sequential
(non-DAG-aware) start-time for every step. Since the default baseline site's
real intensity floor is well above 400, "naive" was silently cheaper than it
would really be, so an honestly-priced optimized plan could look dirtier
than it by comparison. Fixed by pricing all baselines with the exact same
DAG-aware scheduling and real CI lookup as the planner
(`build_fixed_model_plan`), plus a hard invariant in `planner.plan()` that
falls back to the naive configuration if a solver's result is ever dirtier
than a feasible naive baseline.
"""
from __future__ import annotations

import time

import pytest

from app.schemas import Constraints, Step, Weights, Workflow

pytestmark = pytest.mark.asyncio


def _make_step(step_id: str, depends_on: list[str] | None = None, **kwargs) -> Step:
    return Step(
        id=step_id,
        name=step_id.replace("_", " ").title(),
        step_type=kwargs.pop("step_type", "summarization"),
        prompt_template=f"Do {step_id}: {{{{input.text}}}}",
        depends_on=depends_on or [],
        omega=kwargs.pop("omega", 1.0),
        **kwargs,
    )


def _linear_workflow(n: int, **step_kwargs) -> Workflow:
    steps = []
    for i in range(n):
        sid = chr(ord("A") + i)
        deps = [chr(ord("A") + i - 1)] if i > 0 else []
        steps.append(_make_step(sid, deps, **step_kwargs))
    return Workflow(id=f"invariant_test_{n}", name="Invariant Test", steps=steps)


async def _assert_never_worse_than_naive(workflow: Workflow, constraints: Constraints, weights: Weights | None = None, preset: str | None = None):
    from app.scheduler.planner import plan

    result = await plan(workflow, constraints, weights=weights, preset=preset, solver="greedy")
    naive = result.baselines["naive"]
    naive_feasible = (
        naive.makespan_s <= constraints.deadline_s
        and naive.quality >= constraints.quality_floor
    )
    if naive_feasible:
        assert result.totals.carbon_g <= naive.carbon_g + 1e-6, (
            f"Optimized carbon {result.totals.carbon_g}g exceeds feasible naive "
            f"baseline {naive.carbon_g}g"
        )
    return result


class TestCarbonNeverExceedsNaive:
    """Five constraint scenarios, each asserting optimized carbon <= naive carbon."""

    async def test_scenario_1_high_quality_floor_single_site(self):
        """
        The original repro: a single step whose quality floor forces the
        "large" tier on the same site naive would use — the exact case that
        used to fail because naive was priced at a fictional flat 400 CI.
        """
        wf = Workflow(
            id="scenario1", name="High quality floor",
            inputs={"text": "x"},
            steps=[_make_step(
                "analyze", step_type="reasoning", omega=1.0,
                min_quality=0.93, allowed_sites=["gcp-mumbai"],
            )],
        )
        constraints = Constraints(
            deadline_s=3600, quality_floor=0.90,
            allow_deferral=False, allow_cascade=False,
            allowed_sites=["gcp-mumbai"],
        )
        await _assert_never_worse_than_naive(wf, constraints)

    async def test_scenario_2_fast_preset_low_carbon_weight(self):
        """A latency-dominant weighting is the most likely to tempt a dirtier pick."""
        wf = _linear_workflow(3)
        constraints = Constraints(deadline_s=1200, quality_floor=0.7, allow_deferral=True, allow_cascade=True)
        await _assert_never_worse_than_naive(wf, constraints, preset="fast")

    async def test_scenario_3_green_preset_long_deadline(self):
        """Long deadline gives lots of deferral slack — should never regress vs naive."""
        wf = _linear_workflow(4)
        constraints = Constraints(deadline_s=21600, quality_floor=0.8, allow_deferral=True, allow_cascade=True)
        await _assert_never_worse_than_naive(wf, constraints, preset="green")

    async def test_scenario_4_tight_deadline_parallel_branches(self):
        """Parallel branches (market_brief-shaped) with a tight deadline."""
        steps = [
            _make_step("plan", step_type="planning", omega=0.2),
            _make_step("r1", ["plan"], step_type="extraction", omega=0.3),
            _make_step("r2", ["plan"], step_type="extraction", omega=0.3),
            _make_step("fmt", ["r1", "r2"], step_type="formatting", omega=0.2),
        ]
        wf = Workflow(id="scenario4", name="Parallel branches", inputs={"text": "x"}, steps=steps)
        constraints = Constraints(deadline_s=120, quality_floor=0.75, allow_deferral=True, allow_cascade=True)
        await _assert_never_worse_than_naive(wf, constraints, preset="balanced")

    async def test_scenario_5_cascade_enabled_cheap_preset(self):
        """Cheap preset with cascades allowed — expected-value cascade carbon must not exceed naive."""
        wf = _linear_workflow(3, step_type="extraction")
        constraints = Constraints(deadline_s=1800, quality_floor=0.6, allow_deferral=True, allow_cascade=True)
        await _assert_never_worse_than_naive(wf, constraints, preset="cheap")

    async def test_baselines_use_same_ci_lookup_as_greedy(self):
        """
        Direct unit check on the root cause: pricing the SAME (model, site)
        pair via build_fixed_model_plan and via greedy_plan (constrained to
        the identical single option) must agree, since both must use the
        same real carbon-intensity forecast.
        """
        from app.receipt.baselines import build_fixed_model_plan, find_default_site, find_tier_model
        from app.scheduler.greedy import greedy_plan

        wf = Workflow(
            id="scenario6", name="CI agreement",
            inputs={"text": "x"},
            steps=[_make_step("only", step_type="reasoning", min_quality=0.93, allowed_sites=["gcp-mumbai"])],
        )
        start_ts = int(time.time())
        large_model = find_tier_model("L")
        default_site = find_default_site()

        _, baseline_totals = await build_fixed_model_plan(wf, large_model, default_site, start_ts)

        constraints = Constraints(
            deadline_s=3600, quality_floor=0.90, allow_deferral=False,
            allow_cascade=False, allowed_sites=[default_site],
        )
        weights = Weights(latency=0.2, cost=0.1, energy=0.1, carbon=0.4, quality=0.2)
        _, greedy_totals = await greedy_plan(wf, constraints, weights, start_ts)

        assert greedy_totals.model_dump()["carbon_g"] == pytest.approx(baseline_totals.carbon_g, abs=1e-4), (
            "Same (model, site) pair priced differently by the baseline builder vs the real planner — "
            "CI lookup or energy formula has drifted apart again."
        )
