"""
Verdant DB — SQLite engine + table definitions via SQLModel.
Tables: plans, runs, step_runs (telemetry).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlmodel import Field, Session, SQLModel, create_engine, text

from app.config import DB_PATH

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False, connect_args={"check_same_thread": False})


# ---------------------------------------------------------------------------
# Table models
# ---------------------------------------------------------------------------


class PlanRecord(SQLModel, table=True):
    __tablename__ = "plans"  # type: ignore

    id: str = Field(primary_key=True)
    workflow_id: str
    status: str
    solver: str
    solve_ms: int
    totals_json: str  # JSON-serialized Totals
    plan_json: str  # full PlanResult JSON (compressed)
    workflow_json: Optional[str] = None  # Workflow definition (prompts, inputs)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class RunRecord(SQLModel, table=True):
    __tablename__ = "runs"  # type: ignore

    id: str = Field(primary_key=True)
    plan_id: str
    workflow_id: str
    mode: str
    status: str
    totals_json: Optional[str] = None
    final_output: Optional[str] = None  # text deliverable produced by terminal step
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    finished_at: Optional[str] = None


class StepRunRecord(SQLModel, table=True):
    """Telemetry table — one row per executed step (Section 8.9)."""

    __tablename__ = "step_runs"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str
    step_id: str
    step_type: str
    model: str
    model_used: Optional[str] = None  # exact real API model id (e.g. "gemini-3.5-flash-lite")
    site: str
    tokens_in: int
    tokens_out: int
    dur_s: float  # actual duration (seconds)
    energy_wh: float
    carbon_g: float
    cost_usd: float
    verifier_score: Optional[float] = None
    accepted: Optional[bool] = None
    escalated: bool = False
    teacher_agree: Optional[bool] = None  # used by learning predictor
    features_json: Optional[str] = None  # JSON trait vector (for predictor)
    output_text: Optional[str] = None  # text produced by this step
    ts: str = Field(default_factory=lambda: datetime.utcnow().isoformat())



# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


def _seed_fixture_if_needed() -> None:
    """Ensure the default fixture plan is available in the database."""
    with get_session() as session:
        existing = session.get(PlanRecord, "fixture-market-brief-001")
        if existing is not None:
            return

    from pathlib import Path
    fixture_paths = [
        Path(__file__).resolve().parent.parent.parent / "fixtures" / "plan_market_brief.json",
        Path("fixtures/plan_market_brief.json"),
        Path("../fixtures/plan_market_brief.json"),
    ]
    for p in fixture_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    from app.schemas import PlanResult
                    pr = PlanResult(**data)
                    save_plan(pr)
                    break
            except Exception:
                pass


def get_session() -> Session:
    return Session(engine)


def _migrate_and_seed() -> None:
    SQLModel.metadata.create_all(engine)
    with engine.connect() as conn:
        for stmt in [
            "ALTER TABLE plans ADD COLUMN workflow_json TEXT",
            "ALTER TABLE runs ADD COLUMN final_output TEXT",
            "ALTER TABLE step_runs ADD COLUMN output_text TEXT",
            "ALTER TABLE step_runs ADD COLUMN model_used TEXT",
        ]:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # column already exists or table freshly created
    _seed_fixture_if_needed()


# Run once on module import
_migrate_and_seed()


def create_db_and_tables() -> None:
    _migrate_and_seed()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def save_plan(plan_result: "PlanResult", workflow: Optional["Workflow"] = None) -> None:  # noqa: F821
    from app.schemas import PlanResult, Workflow  # avoid circular at module level

    with get_session() as session:
        record = PlanRecord(
            id=plan_result.plan_id,
            workflow_id=workflow.id if workflow else "unknown",
            status=plan_result.status,
            solver=plan_result.solver,
            solve_ms=plan_result.solve_ms,
            totals_json=plan_result.totals.model_dump_json(),
            plan_json=plan_result.model_dump_json(),
            workflow_json=workflow.model_dump_json() if workflow else None,
        )
        session.merge(record)
        session.commit()


def load_plan(plan_id: str) -> Optional[dict]:
    with get_session() as session:
        record = session.get(PlanRecord, plan_id)
        if record is not None:
            return json.loads(record.plan_json)

    # Check fixtures directory fallback
    from pathlib import Path
    fixture_paths = [
        Path(__file__).resolve().parent.parent.parent / "fixtures" / "plan_market_brief.json",
        Path("fixtures/plan_market_brief.json"),
        Path("../fixtures/plan_market_brief.json"),
    ]
    for p in fixture_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("plan_id") == plan_id or plan_id.startswith("fixture-"):
                        from app.schemas import PlanResult
                        pr = PlanResult(**data)
                        save_plan(pr)
                        return data
            except Exception:
                pass
    return None


def load_plan_record(plan_id: str) -> Optional[PlanRecord]:
    with get_session() as session:
        return session.get(PlanRecord, plan_id)


