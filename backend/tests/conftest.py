"""
Pytest configuration and shared fixtures for all Verdant backend tests.
All tests run with MOCK_LLM=1, USE_SYNTHETIC_CARBON=1, SEED=42.
"""
from __future__ import annotations

import os

import pytest

# Ensure test environment variables are set before any imports
os.environ.setdefault("MOCK_LLM", "1")
os.environ.setdefault("USE_SYNTHETIC_CARBON", "1")
os.environ.setdefault("SEED", "42")


@pytest.fixture(scope="session")
def market_brief_workflow():
    """Load the market_brief workflow fixture."""
    import json
    from pathlib import Path

    path = Path(__file__).parent.parent.parent / "workflows" / "market_brief.json"
    with open(path) as f:
        data = json.load(f)
    from app.schemas import Workflow
    return Workflow(**data)


@pytest.fixture(scope="session")
def plan_fixture():
    """Load the hand-written PlanResult fixture."""
    import json
    from pathlib import Path

    path = Path(__file__).parent.parent.parent / "fixtures" / "plan_market_brief.json"
    with open(path) as f:
        data = json.load(f)
    from app.schemas import PlanResult
    return PlanResult(**data)


@pytest.fixture(scope="session")
def default_constraints():
    from app.schemas import Constraints
    return Constraints(
        deadline_s=600,
        quality_floor=0.85,
        allow_deferral=True,
        allow_cascade=True,
    )
