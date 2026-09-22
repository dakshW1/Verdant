"""
Phase 3 tests — VoI decision, LLM clients, verifier, runner.
All tests run with MOCK_LLM=1 (via conftest.py env).
Run with: pytest backend/tests/test_phase3.py -v
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.executor.clock import VirtualClock
from app.executor.llm_clients import MockClient
from app.executor.verifier import _verify_code, _verify_schema, get_verifier_tau
from app.schemas import (
    ConfigOption,
    Constraints,
    Step,
    Weights,
    Workflow,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_step(step_id: str, depends_on: list[str] | None = None, **kwargs) -> Step:
    return Step(
        id=step_id,
        name=step_id.title(),
        step_type=kwargs.pop("step_type", "summarization"),
        prompt_template=f"Summarize: {{{{input.text}}}}",
        depends_on=depends_on or [],
        **kwargs,
    )


def _make_option(step_id: str = "A", mode: str = "single", **kwargs) -> ConfigOption:
    return ConfigOption(
        step_id=step_id,
        model=kwargs.pop("model", "small"),
        site=kwargs.pop("site", "gcp-mumbai"),
        mode=mode,  # type: ignore
        escalate_model=kwargs.pop("escalate_model", "medium" if mode == "cascade" else None),
        verifier_model="small",
        dur_expected_s=kwargs.pop("dur_expected_s", 5),
        dur_worstcase_s=kwargs.pop("dur_worstcase_s", 8),
        energy_wh=kwargs.pop("energy_wh", 0.001),
        energy_wh_worst=kwargs.pop("energy_wh_worst", 0.002),
        cost_usd=kwargs.pop("cost_usd", 0.0001),
        quality=kwargs.pop("quality", 0.85),
        p_accept=kwargs.pop("p_accept", 0.70),
        tokens_in=512,
        tokens_out=200,
    )


# ─── VirtualClock ──────────────────────────────────────────────────────────────

class TestVirtualClock:
    def test_starts_at_zero(self):
        clock = VirtualClock("virtual")
        assert clock.now() == 0.0

    @pytest.mark.asyncio
    async def test_sleep_advances_virtual_time(self):
        clock = VirtualClock("virtual")
        await clock.sleep(10)
        assert clock.now() == 10.0

    @pytest.mark.asyncio
    async def test_sleep_is_instant_in_virtual_mode(self):
        clock = VirtualClock("virtual")
        t0 = time.monotonic()
        await clock.sleep(100)
        elapsed = time.monotonic() - t0
        assert elapsed < 0.1  # Should be near-instant

    def test_advance_manual(self):
        clock = VirtualClock("virtual")
        clock.advance(42)
        assert clock.now() == 42.0

    def test_reset(self):
        clock = VirtualClock("virtual")
        clock.advance(99)
        clock.reset()
        assert clock.now() == 0.0


# ─── Mock LLM Client ──────────────────────────────────────────────────────────

class TestMockClient:
    @pytest.mark.asyncio
    async def test_returns_non_empty_text(self):
        client = MockClient()
        resp = await client.generate("Summarize this document.", "gemini-2.0-flash-lite", max_tokens=100)
        assert resp.text.strip()
        assert resp.tokens_out > 0
        assert resp.tokens_in > 0

    @pytest.mark.asyncio
    async def test_is_deterministic_same_prompt(self):
        client = MockClient()
        r1 = await client.generate("Hello world", "gemini-2.0-flash-lite")
        r2 = await client.generate("Hello world", "gemini-2.0-flash-lite")
        assert r1.text == r2.text
        assert r1.tokens_out == r2.tokens_out

    @pytest.mark.asyncio
    async def test_different_prompts_give_different_outputs(self):
        client = MockClient()
        r1 = await client.generate("Prompt A: apple", "gemini-2.0-flash-lite")
        r2 = await client.generate("Prompt B: banana banana banana", "gemini-2.0-flash-lite")
        # Token counts differ with prompt hash
        assert r1.tokens_out != r2.tokens_out or r1.tokens_in != r2.tokens_in

    @pytest.mark.asyncio
    async def test_respects_max_tokens(self):
        client = MockClient()
        resp = await client.generate("Test prompt", "gemini-2.0-flash-lite", max_tokens=50)
        assert resp.tokens_out <= 50


# ─── Verifier ─────────────────────────────────────────────────────────────────

class TestVerifier:
    def test_tau_in_range(self):
        tau = get_verifier_tau()
        assert 0.0 < tau < 1.0

    def test_schema_valid_json(self):
        score = _verify_schema('{"name": "Alice", "age": 30}', {"required": ["name", "age"]})
        assert score == 1.0

    def test_schema_missing_key(self):
        score = _verify_schema('{"name": "Alice"}', {"required": ["name", "age"]})
        assert score == 0.5  # 1/2 required keys

    def test_schema_invalid_json(self):
        score = _verify_schema("not json at all", {"required": ["name"]})
        assert score == 0.0

    def test_schema_no_required(self):
        score = _verify_schema('{"anything": 1}', {})
        assert score == 1.0

    def test_code_valid_python(self):
        score = _verify_code("def hello():\n    return 'world'")
        assert score > 0.5

    def test_code_syntax_error(self):
        score = _verify_code("def broken(:\n    pass")
        assert score == 0.0

    def test_code_with_fences(self):
        code = "```python\nprint('hello')\n```"
        score = _verify_code(code)
        assert score > 0.5

    @pytest.mark.asyncio
    async def test_verify_none_returns_one(self):
        from app.executor.verifier import verify_output
        score = await verify_output("any text", "none", "summarization", "prompt", None)
        assert score == 1.0


# ─── VoI Decision ─────────────────────────────────────────────────────────────

class TestVoI:
    def test_no_escalate_when_score_above_tau(self):
        from app.executor.voi import should_escalate
        step = _make_step("A", cascade_allowed=True)
        opt = _make_option(mode="cascade")
        # Score above tau (0.7) → should not escalate
        assert not should_escalate(step, opt, verifier_score=0.85, remaining_slack_s=0, ci_g_per_kwh=400.0)

    def test_escalate_when_below_min_quality(self):
        from app.executor.voi import should_escalate
        step = _make_step("A", cascade_allowed=True, min_quality=0.9)
        opt = _make_option(mode="cascade")
        # Score below step.min_quality → must escalate
        assert should_escalate(step, opt, verifier_score=0.5, remaining_slack_s=0, ci_g_per_kwh=400.0)

    def test_no_escalate_single_mode(self):
        from app.executor.voi import should_escalate
        step = _make_step("A")
        opt = _make_option(mode="single")
        # Single mode → cannot escalate even with low score
        assert not should_escalate(step, opt, verifier_score=0.2, remaining_slack_s=0, ci_g_per_kwh=400.0)

    def test_no_escalate_cascade_not_allowed(self):
        from app.executor.voi import should_escalate
        step = _make_step("A", cascade_allowed=False)
        opt = _make_option(mode="cascade")
        assert not should_escalate(step, opt, verifier_score=0.2, remaining_slack_s=0, ci_g_per_kwh=400.0)


# ─── Full Run Integration ─────────────────────────────────────────────────────

class TestRunnerIntegration:
    @pytest.mark.asyncio
    async def test_virtual_run_completes(self):
        """Create a plan and run it in virtual mode — should complete with results."""
        from app.scheduler.planner import plan

        wf = Workflow(
            id="run_test",
            name="Run Test",
            steps=[
                _make_step("A"),
                _make_step("B", ["A"]),
            ],
        )
        constraints = Constraints(deadline_s=300, quality_floor=0.5)
        plan_result = await plan(wf, constraints, solver="greedy")

        from app.executor.runner import start_run, get_run
        run_id = await start_run(plan_result.plan_id, "virtual")
        assert run_id

        # Wait for the run to complete (with timeout)
        for _ in range(50):
            await asyncio.sleep(0.1)
            summary = get_run(run_id)
            if summary and summary.status != "running":
                break

        summary = get_run(run_id)
        assert summary is not None
        assert summary.status == "completed"
        assert len(summary.steps) == 2
        assert summary.totals is not None
        assert summary.totals.carbon_g >= 0

    @pytest.mark.asyncio
    async def test_run_steps_have_output_text(self):
        """Each completed step should have non-empty output text."""
        from app.scheduler.planner import plan
        from app.executor.runner import start_run, get_run

        wf = Workflow(
            id="output_test",
            name="Output Test",
            steps=[_make_step("X")],
        )
        constraints = Constraints(deadline_s=300, quality_floor=0.5)
        plan_result = await plan(wf, constraints, solver="greedy")
        run_id = await start_run(plan_result.plan_id, "virtual")

        for _ in range(50):
            await asyncio.sleep(0.1)
            summary = get_run(run_id)
            if summary and summary.status != "running":
                break

        summary = get_run(run_id)
        assert summary and summary.status == "completed"
        assert all(sr.output_text.strip() for sr in summary.steps)

    @pytest.mark.asyncio
    async def test_run_api_endpoint(self):
        """Test POST /api/runs via TestClient."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.scheduler.planner import plan

        wf = Workflow(
            id="api_run_test",
            name="API Run Test",
            steps=[_make_step("A")],
        )
        constraints = Constraints(deadline_s=300, quality_floor=0.5)
        plan_result = await plan(wf, constraints, solver="greedy")

        client = TestClient(app)
        resp = client.post("/api/runs", json={"plan_id": plan_result.plan_id, "mode": "virtual"})
        assert resp.status_code == 200
        data = resp.json()
        assert "run_id" in data

    @pytest.mark.asyncio
    async def test_run_not_found_returns_404(self):
        """GET /api/runs/nonexistent should return 404."""
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        resp = client.get("/api/runs/does-not-exist")
        assert resp.status_code == 404
