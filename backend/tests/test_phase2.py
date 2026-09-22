"""
Phase 2 tests — DAG validation, CPM, greedy scheduler, baselines.
Run with: pytest backend/tests/test_phase2.py -v
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.dag.cpm import compute_cpm
from app.dag.graph import validate_dag
from app.receipt.baselines import compute_baselines
from app.schemas import (
    Constraints,
    Step,
    Totals,
    Weights,
    Workflow,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

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


def _linear_workflow(n: int = 3) -> Workflow:
    """A → B → C → ... linear chain of n steps."""
    steps = []
    for i in range(n):
        sid = chr(ord("A") + i)
        deps = [chr(ord("A") + i - 1)] if i > 0 else []
        steps.append(_make_step(sid, deps))
    return Workflow(id="test_linear", name="Linear Test", steps=steps)


def _diamond_workflow() -> Workflow:
    """A → B, A → C, B+C → D (diamond DAG)."""
    steps = [
        _make_step("A"),
        _make_step("B", ["A"]),
        _make_step("C", ["A"]),
        _make_step("D", ["B", "C"]),
    ]
    return Workflow(id="test_diamond", name="Diamond Test", steps=steps)


# ─── DAG validation ───────────────────────────────────────────────────────────

class TestDAGValidation:
    def test_valid_linear_dag(self):
        wf = _linear_workflow(3)
        result = validate_dag(wf)
        assert result.valid
        assert len(result.errors) == 0

    def test_valid_diamond_dag(self):
        result = validate_dag(_diamond_workflow())
        assert result.valid

    def test_missing_dependency(self):
        steps = [_make_step("A", ["X"])]  # X doesn't exist
        wf = Workflow(id="bad", name="Bad", steps=steps)
        result = validate_dag(wf)
        assert not result.valid
        assert any("X" in e for e in result.errors)

    def test_cycle_detected(self):
        steps = [
            _make_step("A", ["B"]),
            _make_step("B", ["A"]),
        ]
        wf = Workflow(id="cycle", name="Cycle", steps=steps)
        result = validate_dag(wf)
        assert not result.valid
        assert any("cycle" in e.lower() for e in result.errors)

    def test_empty_workflow(self):
        wf = Workflow(id="empty", name="Empty", steps=[])
        result = validate_dag(wf)
        assert not result.valid

    def test_topo_levels_correct(self):
        """Diamond: level 0=[A], level 1=[B,C], level 2=[D]."""
        result = validate_dag(_diamond_workflow())
        assert result.valid
        assert result.topo_levels[0] == ["A"]
        assert set(result.topo_levels[1]) == {"B", "C"}
        assert result.topo_levels[2] == ["D"]


# ─── CPM ──────────────────────────────────────────────────────────────────────

class TestCPM:
    def test_linear_chain_critical_path(self):
        """A(2s) → B(3s) → C(1s): all steps critical, makespan=6."""
        topo = ["A", "B", "C"]
        durations = {"A": 2, "B": 3, "C": 1}
        preds = {"A": [], "B": ["A"], "C": ["B"]}
        nodes = compute_cpm(topo, durations, preds, deadline_s=6)

        assert nodes["A"].es == 0
        assert nodes["A"].ef == 2
        assert nodes["B"].es == 2
        assert nodes["B"].ef == 5
        assert nodes["C"].es == 5
        assert nodes["C"].ef == 6

        for n in nodes.values():
            assert n.is_critical, f"Step {n.step_id} should be critical"

    def test_parallel_steps_have_slack(self):
        """A(1s) → B(5s), A → C(2s): C has 3s slack."""
        topo = ["A", "B", "C"]
        durations = {"A": 1, "B": 5, "C": 2}
        preds = {"A": [], "B": ["A"], "C": ["A"]}
        nodes = compute_cpm(topo, durations, preds, deadline_s=6)

        assert nodes["C"].slack == 3
        assert not nodes["C"].is_critical
        assert nodes["B"].is_critical

    def test_diamond_critical_path(self):
        """A(1)→B(4), A→C(2), B+C→D(1). Critical: A-B-D."""
        topo = ["A", "B", "C", "D"]
        durations = {"A": 1, "B": 4, "C": 2, "D": 1}
        preds = {"A": [], "B": ["A"], "C": ["A"], "D": ["B", "C"]}
        nodes = compute_cpm(topo, durations, preds, deadline_s=6)

        assert nodes["A"].is_critical
        assert nodes["B"].is_critical
        assert not nodes["C"].is_critical
        assert nodes["D"].is_critical
        assert nodes["C"].slack == 2

    def test_single_step(self):
        nodes = compute_cpm(["X"], {"X": 5}, {"X": []}, deadline_s=10)
        assert nodes["X"].es == 0
        assert nodes["X"].ef == 5
        assert nodes["X"].slack == 5
        assert not nodes["X"].is_critical


# ─── Greedy scheduler ─────────────────────────────────────────────────────────

class TestGreedyScheduler:
    @pytest.mark.asyncio
    async def test_single_step_plan(self):
        from app.scheduler.greedy import greedy_plan
        wf = Workflow(
            id="single",
            name="Single Step",
            steps=[_make_step("A", step_type="summarization")],
        )
        constraints = Constraints(deadline_s=300, quality_floor=0.5)
        weights = Weights()
        start_ts = int(time.time())

        plans, totals = await greedy_plan(wf, constraints, weights, start_ts)
        assert len(plans) == 1
        assert plans[0].step_id == "A"
        assert plans[0].start_s >= 0
        assert totals.makespan_s > 0
        assert totals.carbon_g >= 0
        assert totals.cost_usd >= 0

    @pytest.mark.asyncio
    async def test_linear_chain_respects_dependencies(self):
        from app.scheduler.greedy import greedy_plan
        wf = _linear_workflow(3)
        constraints = Constraints(deadline_s=600, quality_floor=0.5)
        weights = Weights()
        start_ts = int(time.time())

        plans, totals = await greedy_plan(wf, constraints, weights, start_ts)
        assert len(plans) == 3

        # Each step must end before the next begins
        by_id = {p.step_id: p for p in plans}
        assert by_id["B"].start_s >= by_id["A"].start_s + by_id["A"].option.dur_expected_s
        assert by_id["C"].start_s >= by_id["B"].start_s + by_id["B"].option.dur_expected_s

    @pytest.mark.asyncio
    async def test_totals_are_sum_of_steps(self):
        from app.scheduler.greedy import greedy_plan
        wf = _linear_workflow(2)
        constraints = Constraints(deadline_s=600, quality_floor=0.0)
        weights = Weights()
        start_ts = int(time.time())

        plans, totals = await greedy_plan(wf, constraints, weights, start_ts)
        computed_cost = sum(p.option.cost_usd for p in plans)
        assert abs(totals.cost_usd - computed_cost) < 1e-6

    @pytest.mark.asyncio
    async def test_quality_floor_respected(self):
        from app.scheduler.greedy import greedy_plan
        wf = Workflow(
            id="qfloor",
            name="Quality Floor",
            steps=[_make_step("A", step_type="reasoning")],
        )
        # High quality floor should force medium or large model
        constraints = Constraints(deadline_s=600, quality_floor=0.85)
        weights = Weights()
        start_ts = int(time.time())

        plans, _ = await greedy_plan(wf, constraints, weights, start_ts)
        assert plans[0].option.quality >= 0.85

    @pytest.mark.asyncio
    async def test_green_preset_picks_lower_carbon(self):
        """Green preset (high carbon weight) should have lower carbon than latency preset."""
        from app.scheduler.greedy import greedy_plan
        wf = _linear_workflow(2)
        constraints = Constraints(deadline_s=3600, quality_floor=0.5, allow_deferral=True)
        start_ts = int(time.time())

        green_weights = Weights(latency=0.05, cost=0.05, energy=0.1, carbon=0.75, quality=0.05)
        fast_weights = Weights(latency=0.7, cost=0.05, energy=0.05, carbon=0.1, quality=0.1)

        _, green_totals = await greedy_plan(wf, constraints, green_weights, start_ts)
        _, fast_totals = await greedy_plan(wf, constraints, fast_weights, start_ts)

        # Green should have ≤ carbon vs fast-weighted (may be equal if same option chosen)
        assert green_totals.carbon_g <= fast_totals.carbon_g + 1e-4


# ─── Baselines ────────────────────────────────────────────────────────────────

class TestBaselines:
    async def test_baselines_keys(self):
        wf = _linear_workflow(2)
        baselines = await compute_baselines(wf, start_ts=int(time.time()))
        assert set(baselines.keys()) == {"naive", "fastest", "smallest"}

    async def test_naive_has_highest_cost(self):
        """Naive uses largest model → highest cost."""
        wf = _linear_workflow(2)
        baselines = await compute_baselines(wf, start_ts=int(time.time()))
        assert baselines["naive"].cost_usd >= baselines["smallest"].cost_usd

    async def test_naive_has_highest_quality(self):
        """Naive uses largest model → highest quality."""
        wf = _linear_workflow(2)
        baselines = await compute_baselines(wf, start_ts=int(time.time()))
        assert baselines["naive"].quality >= baselines["smallest"].quality

    async def test_all_baselines_positive_makespan(self):
        wf = _linear_workflow(3)
        baselines = await compute_baselines(wf, start_ts=int(time.time()))
        for name, b in baselines.items():
            assert b.makespan_s > 0, f"Baseline {name} has zero makespan"
            assert b.energy_wh > 0, f"Baseline {name} has zero energy"


# ─── Full planner integration ─────────────────────────────────────────────────

class TestPlannerIntegration:
    @pytest.mark.asyncio
    async def test_plan_returns_valid_result(self):
        from app.scheduler.planner import plan
        wf = _linear_workflow(2)
        constraints = Constraints(deadline_s=600, quality_floor=0.5)
        result = await plan(wf, constraints, solver="greedy")

        assert result.plan_id
        assert result.status in {"optimal", "feasible", "relaxed"}
        assert result.solver == "greedy"
        assert len(result.steps) == 2
        assert "naive" in result.baselines
        assert result.solve_ms >= 0

    @pytest.mark.asyncio
    async def test_plan_preset_green(self):
        from app.scheduler.planner import plan
        wf = _linear_workflow(2)
        constraints = Constraints(deadline_s=600, quality_floor=0.5)
        result = await plan(wf, constraints, preset="green", solver="greedy")
        assert result.plan_id

    @pytest.mark.asyncio
    async def test_plan_invalid_dag_raises(self):
        from app.scheduler.planner import plan
        steps = [_make_step("A", ["NONEXISTENT"])]
        wf = Workflow(id="bad", name="Bad", steps=steps)
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            await plan(wf, Constraints(), solver="greedy")
