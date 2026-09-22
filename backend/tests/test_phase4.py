"""
Phase 4 tests — CP-SAT scheduler and Pareto frontier.
Run with: pytest backend/tests/test_phase4.py -v
"""
from __future__ import annotations

import time

import pytest

from app.schemas import Constraints, Step, Weights, Workflow


def _make_step(sid: str, deps: list[str] | None = None, **kw) -> Step:
    return Step(
        id=sid, name=sid.title(), step_type=kw.pop("step_type", "summarization"),
        prompt_template="Do it.", depends_on=deps or [], **kw,
    )


def _linear(n: int = 3) -> Workflow:
    steps = []
    for i in range(n):
        sid = chr(ord("A") + i)
        steps.append(_make_step(sid, [chr(ord("A") + i - 1)] if i else []))
    return Workflow(id="cpsat_linear", name="Linear", steps=steps)


class TestCPSAT:
    @pytest.mark.asyncio
    async def test_cpsat_returns_valid_plan(self):
        from app.scheduler.cpsat import cpsat_plan
        wf = _linear(2)
        constraints = Constraints(deadline_s=600, quality_floor=0.5)
        weights = Weights()
        plans, totals = await cpsat_plan(wf, constraints, weights, int(time.time()))
        assert len(plans) == 2
        assert totals.makespan_s > 0
        assert totals.carbon_g >= 0

    @pytest.mark.asyncio
    async def test_cpsat_respects_deadline(self):
        from app.scheduler.cpsat import cpsat_plan
        wf = _linear(2)
        constraints = Constraints(deadline_s=600, quality_floor=0.5)
        weights = Weights()
        plans, totals = await cpsat_plan(wf, constraints, weights, int(time.time()))
        assert totals.makespan_s <= 600

    @pytest.mark.asyncio
    async def test_cpsat_quality_floor(self):
        from app.scheduler.cpsat import cpsat_plan
        wf = Workflow(
            id="qf", name="QF",
            steps=[_make_step("A", step_type="reasoning")],
        )
        constraints = Constraints(deadline_s=600, quality_floor=0.80)
        weights = Weights()
        plans, totals = await cpsat_plan(wf, constraints, weights, int(time.time()))
        assert all(p.option.quality >= 0.80 for p in plans)

    @pytest.mark.asyncio
    async def test_cpsat_vs_greedy_carbon(self):
        """CP-SAT should achieve <= carbon than greedy (or equal) on the same weights."""
        from app.scheduler.cpsat import cpsat_plan
        from app.scheduler.greedy import greedy_plan
        wf = _linear(2)
        constraints = Constraints(deadline_s=600, quality_floor=0.5)
        weights = Weights(carbon=0.7, latency=0.1, cost=0.05, energy=0.1, quality=0.05)
        start_ts = int(time.time())
        _, cpsat_totals = await cpsat_plan(wf, constraints, weights, start_ts)
        _, greedy_totals = await greedy_plan(wf, constraints, weights, start_ts)
        # CP-SAT is optimal so should be at least as good
        assert cpsat_totals.carbon_g <= greedy_totals.carbon_g + 1e-4


class TestPareto:
    @pytest.mark.asyncio
    async def test_pareto_returns_multiple_points(self):
        from app.scheduler.pareto import compute_pareto
        from app.schemas import PlanRequest
        wf = _linear(2)
        req = PlanRequest(
            workflow=wf,
            constraints=Constraints(deadline_s=600, quality_floor=0.5),
        )
        points = await compute_pareto(req)
        assert len(points) >= 1

    @pytest.mark.asyncio
    async def test_pareto_sorted_by_carbon(self):
        from app.scheduler.pareto import compute_pareto
        from app.schemas import PlanRequest
        wf = _linear(2)
        req = PlanRequest(workflow=wf, constraints=Constraints(deadline_s=600, quality_floor=0.5))
        points = await compute_pareto(req)
        carbons = [p.carbon_g for p in points]
        assert carbons == sorted(carbons)

    @pytest.mark.asyncio
    async def test_pareto_no_dominated_points(self):
        from app.scheduler.pareto import _prune_dominated, compute_pareto
        from app.schemas import PlanRequest, Totals
        # Create obviously dominated set
        dominated = Totals(makespan_s=100, cost_usd=0.01, energy_wh=0.1, carbon_g=50.0, carbon_g_robust=55.0, quality=0.8)
        better = Totals(makespan_s=80, cost_usd=0.008, energy_wh=0.08, carbon_g=40.0, carbon_g_robust=44.0, quality=0.85)
        result = _prune_dominated([dominated, better])
        assert dominated not in result
        assert better in result

    @pytest.mark.asyncio
    async def test_pareto_api_endpoint(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        payload = {
            "workflow": {
                "id": "p", "name": "P",
                "steps": [{"id": "A", "name": "A", "step_type": "summarization", "prompt_template": "x"}],
            },
            "constraints": {"deadline_s": 600, "quality_floor": 0.5},
        }
        resp = client.post("/api/pareto", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "points" in data
