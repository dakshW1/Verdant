"""
Phase 0 smoke tests:
- Schemas parse correctly from fixture JSON
- DAG validation works (cycle detection, missing deps)
- Synthetic carbon provider works
- /api/health endpoint responds
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import (
    Constraints,
    PlanResult,
    Step,
    Workflow,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_fixture_parses(plan_fixture):
    """The hand-written fixture must parse into a valid PlanResult."""
    assert plan_fixture.plan_id == "fixture-market-brief-001"
    assert len(plan_fixture.steps) == 10
    assert plan_fixture.totals.carbon_g > 0
    assert plan_fixture.totals.quality > 0


def test_step_schema_defaults():
    s = Step(id="test", name="Test", step_type="planning", prompt_template="Hello")
    assert s.omega == 1.0
    assert s.depends_on == []
    assert s.cascade_allowed is True
    assert s.verifier == "llm_judge"


def test_constraints_defaults():
    c = Constraints()
    assert c.deadline_s == 600
    assert c.quality_floor == 0.85
    assert c.robust_z == 1.28


# ---------------------------------------------------------------------------
# DAG validation tests (Phase 0 stub version)
# ---------------------------------------------------------------------------


def test_validate_valid_workflow(market_brief_workflow):
    from app.dag.graph import validate_dag
    result = validate_dag(market_brief_workflow)
    assert result.valid is True
    assert result.errors == []


def test_validate_missing_dependency():
    from app.dag.graph import validate_dag
    wf = Workflow(
        id="bad",
        name="Bad",
        steps=[
            Step(
                id="step_a",
                name="A",
                step_type="planning",
                prompt_template="hello",
                depends_on=["nonexistent"],
            )
        ],
    )
    result = validate_dag(wf)
    assert result.valid is False
    assert any("nonexistent" in e for e in result.errors)


def test_validate_cycle_detection():
    from app.dag.graph import validate_dag
    wf = Workflow(
        id="cyclic",
        name="Cyclic",
        steps=[
            Step(id="a", name="A", step_type="planning", prompt_template="p", depends_on=["b"]),
            Step(id="b", name="B", step_type="extraction", prompt_template="p", depends_on=["a"]),
        ],
    )
    result = validate_dag(wf)
    assert result.valid is False
    assert any("cycle" in e.lower() for e in result.errors)


def test_validate_empty_workflow():
    from app.dag.graph import validate_dag
    wf = Workflow(id="empty", name="Empty", steps=[])
    result = validate_dag(wf)
    assert result.valid is False


# ---------------------------------------------------------------------------
# Synthetic carbon provider
# ---------------------------------------------------------------------------


def test_synthetic_carbon_finland():
    """Finland should have lower CI than India zones."""
    import asyncio
    import time

    from app.carbon.synthetic import SyntheticCarbonProvider

    provider = SyntheticCarbonProvider()
    now = int(time.time())
    fi = asyncio.run(provider.forecast("FI", now, 86400, 1800))
    in_we = asyncio.run(provider.forecast("IN-WE", now, 86400, 1800))

    assert fi.source == "synthetic"
    assert in_we.source == "synthetic"
    assert sum(fi.mean) < sum(in_we.mean), "Finland should have lower total CI than Western India"


def test_synthetic_sigma_grows_with_horizon():
    """Forecast uncertainty should increase for future windows."""
    from app.carbon.synthetic import SyntheticCarbonProvider
    import asyncio, time

    provider = SyntheticCarbonProvider()
    now = int(time.time())
    fc = asyncio.run(provider.forecast("IN-SO", now, 86400, 1800))

    # Sigma at window 0 should be less than sigma at window 40 (20 hours ahead)
    assert fc.sigma[0] < fc.sigma[40], "Sigma must increase with forecast horizon"


def test_synthetic_deterministic():
    """Same seed, same forecast."""
    from app.carbon.synthetic import SyntheticCarbonProvider
    import asyncio, time

    provider = SyntheticCarbonProvider()
    now = int(time.time())
    fc1 = asyncio.run(provider.forecast("SG", now, 3600, 1800))
    fc2 = asyncio.run(provider.forecast("SG", now, 3600, 1800))
    assert fc1.mean == fc2.mean


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


def test_health_endpoint():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["mock_llm"] is True
    assert data["db_ok"] is True


def test_models_endpoint():
    resp = client.get("/api/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "models" in data
    model_ids = [m["id"] for m in data["models"]]
    assert "small" in model_ids
    assert "medium" in model_ids
    assert "large" in model_ids


def test_sites_endpoint():
    resp = client.get("/api/sites")
    assert resp.status_code == 200
    data = resp.json()
    assert "sites" in data
    site_ids = [s["id"] for s in data["sites"]]
    assert "gcp-finland" in site_ids
    assert "gcp-mumbai" in site_ids


def test_validate_workflow_endpoint(market_brief_workflow):
    resp = client.post(
        "/api/workflows/validate",
        json=market_brief_workflow.model_dump(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True


def test_plan_endpoint_not_yet_implemented():
    """Phase 0: plan endpoint returns 501 until Phase 2."""
    from app.schemas import PlanRequest
    resp = client.post(
        "/api/plan",
        json=PlanRequest(
            workflow=Workflow(
                id="test", name="Test",
                steps=[Step(id="s1", name="S1", step_type="planning", prompt_template="hi")]
            )
        ).model_dump(),
    )
    # Phase 2 implemented — /api/plan now returns 200 OK with a PlanResult
    assert resp.status_code == 200
    data = resp.json()
    assert "plan_id" in data
    assert "steps" in data
    assert "totals" in data
