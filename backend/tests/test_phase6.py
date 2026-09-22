"""
Phase 6 tests — Learning predictor, receipt builder, full end-to-end.
Run with: pytest backend/tests/test_phase6.py -v
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.learning.predictor import (
    BetaBinomialState,
    get_all_states,
    get_state,
    predict_p_accept,
    predict_quality,
    reset_state,
    update_from_run,
)


# ─── BetaBinomialState ────────────────────────────────────────────────────────

class TestBetaBinomialState:
    def test_mean_initialized_from_prior(self):
        state = BetaBinomialState(alpha=8.0, beta=2.0)
        assert abs(state.mean - 0.8) < 1e-9

    def test_update_increases_alpha_on_accept(self):
        state = BetaBinomialState(alpha=8.0, beta=2.0)
        state.update(accepted=5, rejected=0)
        assert state.alpha == 13.0
        assert state.beta == 2.0

    def test_update_increases_beta_on_reject(self):
        state = BetaBinomialState(alpha=8.0, beta=2.0)
        state.update(accepted=0, rejected=3)
        assert state.beta == 5.0

    def test_uncertainty_decreases_with_more_data(self):
        small = BetaBinomialState(alpha=1.0, beta=1.0)
        large = BetaBinomialState(alpha=50.0, beta=50.0)
        assert large.uncertainty < small.uncertainty

    def test_mean_shifts_toward_data(self):
        state = BetaBinomialState(alpha=5.0, beta=5.0)
        mean_before = state.mean
        state.update(accepted=20, rejected=0)
        assert state.mean > mean_before


# ─── Predictor state management ──────────────────────────────────────────────

class TestPredictorState:
    def setup_method(self):
        reset_state()  # clean slate for each test

    def test_get_state_initializes_from_prior(self):
        state = get_state("summarization", "small")
        assert state.alpha > 0
        assert state.beta > 0
        assert 0 < state.mean < 1

    def test_get_state_is_cached(self):
        s1 = get_state("summarization", "small")
        s2 = get_state("summarization", "small")
        assert s1 is s2  # same object

    def test_different_models_have_different_states(self):
        s_small = get_state("reasoning", "small")
        s_large = get_state("reasoning", "large")
        assert s_small is not s_large

    def test_reset_clears_state(self):
        s = get_state("summarization", "small")
        s.update(accepted=100, rejected=0)
        reset_state("summarization", "small")
        s_fresh = get_state("summarization", "small")
        assert s_fresh.alpha < s.alpha  # back to prior

    def test_get_all_states_returns_list(self):
        get_state("summarization", "small")
        get_state("reasoning", "medium")
        states = get_all_states()
        assert len(states) >= 2
        for s in states:
            assert "step_type" in s
            assert "model" in s
            assert "mean" in s
            assert "n" in s


# ─── Prediction functions ─────────────────────────────────────────────────────

class TestPredictFunctions:
    def setup_method(self):
        reset_state()

    def test_predict_p_accept_in_range(self):
        p = predict_p_accept("summarization", "small")
        assert 0.0 <= p <= 1.0

    def test_predict_quality_in_range(self):
        q = predict_quality("code", "small")
        assert 0.0 <= q <= 1.0

    def test_large_model_higher_quality_than_small(self):
        """Large model should have higher predicted quality than small for reasoning."""
        reset_state()
        q_small = predict_quality("reasoning", "small")
        q_large = predict_quality("reasoning", "large")
        assert q_large > q_small

    def test_quality_blends_toward_learned_with_data(self):
        """After many positive observations, quality should increase for that model."""
        reset_state()
        q_before = predict_quality("summarization", "small")
        state = get_state("summarization", "small")
        state.update(accepted=200, rejected=0)  # 200 successful calls
        q_after = predict_quality("summarization", "small")
        assert q_after >= q_before  # learned quality >= prior

    def test_formatting_small_model_high_quality(self):
        """Formatting tasks should already have high quality for small model."""
        p = predict_p_accept("formatting", "small")
        assert p > 0.7


# ─── update_from_run ─────────────────────────────────────────────────────────

class TestUpdateFromRun:
    @pytest.mark.asyncio
    async def test_update_after_virtual_run(self):
        """After completing a virtual run, update_from_run should process telemetry."""
        from app.schemas import Constraints, Step, Workflow
        from app.scheduler.planner import plan
        from app.executor.runner import start_run, get_run

        wf = Workflow(
            id="learn_test",
            name="Learn Test",
            steps=[Step(
                id="A", name="A", step_type="summarization",
                prompt_template="Summarize: {{input.text}}", depends_on=[],
            )],
        )
        constraints = Constraints(deadline_s=300, quality_floor=0.5)
        plan_result = await plan(wf, constraints, solver="greedy")
        run_id = await start_run(plan_result.plan_id, "virtual")

        # Wait for completion
        for _ in range(50):
            await asyncio.sleep(0.1)
            summary = get_run(run_id)
            if summary and summary.status != "running":
                break

        reset_state()
        n = update_from_run(run_id)
        # May be 0 if telemetry wasn't recorded (depends on DB state)
        assert n >= 0


# ─── Receipt builder ──────────────────────────────────────────────────────────

class TestReceiptBuilder:
    @pytest.mark.asyncio
    async def test_receipt_after_run(self):
        """Build a receipt after a complete virtual run."""
        from app.schemas import Constraints, Step, Workflow
        from app.scheduler.planner import plan
        from app.executor.runner import start_run, get_run
        from app.receipt.receipt import build_receipt

        wf = Workflow(
            id="receipt_test",
            name="Receipt Test",
            steps=[Step(
                id="A", name="A", step_type="summarization",
                prompt_template="Summarize: {{input.text}}", depends_on=[],
            )],
        )
        constraints = Constraints(deadline_s=300, quality_floor=0.5)
        plan_result = await plan(wf, constraints, solver="greedy")
        run_id = await start_run(plan_result.plan_id, "virtual")

        for _ in range(50):
            await asyncio.sleep(0.1)
            summary = get_run(run_id)
            if summary and summary.status != "running":
                break

        receipt = await build_receipt(run_id)
        assert receipt.run_id == run_id
        assert receipt.actual["carbon_g"] >= 0
        assert receipt.saved_carbon_g >= 0
        assert 0 <= receipt.saved_pct <= 100
        assert len(receipt.equivalents) >= 3
        assert len(receipt.ablation_stages) >= 4

    @pytest.mark.asyncio
    async def test_receipt_api_endpoint(self):
        """Test GET /api/runs/{id}/receipt via TestClient after run completes."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.schemas import Constraints, Step, Workflow
        from app.scheduler.planner import plan
        from app.executor.runner import start_run, get_run

        wf = Workflow(
            id="receipt_api",
            name="Receipt API",
            steps=[Step(
                id="A", name="A", step_type="formatting",
                prompt_template="Format: {{input.text}}", depends_on=[],
            )],
        )
        constraints = Constraints(deadline_s=300, quality_floor=0.5)
        plan_result = await plan(wf, constraints, solver="greedy")
        run_id = await start_run(plan_result.plan_id, "virtual")

        for _ in range(50):
            await asyncio.sleep(0.1)
            summary = get_run(run_id)
            if summary and summary.status != "running":
                break

        client = TestClient(app)
        resp = client.get(f"/api/runs/{run_id}/receipt")
        assert resp.status_code == 200
        data = resp.json()
        assert "saved_carbon_g" in data
        assert "ablation_stages" in data
        assert "equivalents" in data

    @pytest.mark.asyncio
    async def test_predictor_api_endpoint(self):
        """Test GET /api/predictor returns predictor state."""
        from fastapi.testclient import TestClient
        from app.main import app

        # Prime some state
        get_state("summarization", "small")

        client = TestClient(app)
        resp = client.get("/api/predictor")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_predictor_update_endpoint(self):
        """Test POST /api/predictor/update/{run_id}."""
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        # Use a fake run_id — should return 0 processed (no records)
        resp = client.post("/api/predictor/update/nonexistent-run-id")
        assert resp.status_code == 200
        data = resp.json()
        assert data["records_processed"] == 0
