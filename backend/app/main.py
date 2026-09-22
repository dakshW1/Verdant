"""
Verdant backend — FastAPI application entrypoint.
Serves the REST API and SSE streams defined in Section 10 of AGENTS.md.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import (
    MOCK_LLM,
    USE_SYNTHETIC_CARBON,
    validate_model_ids,
)
from app.db import create_db_and_tables
from app.schemas import (
    CIForecast,
    Constraints,
    HealthCheck,
    PlanRequest,
    PlanResult,
    RunMode,
    RunRequest,
    ValidationResult,
    Weights,
    Workflow,
)

logger = logging.getLogger("verdant")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Verdant backend starting …")
    create_db_and_tables()
    ok, missing = validate_model_ids()
    if missing:
        logger.warning("Configured model IDs not found in Gemini API: %s", missing)
    else:
        logger.info("All configured model IDs verified: %s", ok or ["(mock mode)"])
    if MOCK_LLM:
        logger.info("MOCK_LLM=1 — all LLM calls are simulated.")
    if USE_SYNTHETIC_CARBON:
        logger.info("USE_SYNTHETIC_CARBON=1 — using synthetic CI model.")
    yield
    logger.info("Verdant backend shutting down.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Verdant",
    description="Carbon & Latency-Aware Agent Workflow Scheduler",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"title": "Internal Server Error", "detail": str(exc)},
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/api/health", response_model=HealthCheck, tags=["meta"])
async def health() -> HealthCheck:
    ok, missing = validate_model_ids()
    carbon_source = "synthetic" if USE_SYNTHETIC_CARBON else "snapshot"
    # Try to reach a live carbon API if not synthetic
    if not USE_SYNTHETIC_CARBON:
        try:
            from app.carbon.provider import get_carbon_provider  # type: ignore

            provider = get_carbon_provider()
            carbon_source = "live"
        except Exception:
            carbon_source = "snapshot"

    llm_reachable = MOCK_LLM or bool(ok)

    from app.db import engine
    from sqlmodel import text
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return HealthCheck(
        status="ok",
        mock_llm=MOCK_LLM,
        carbon_source=carbon_source,  # type: ignore
        llm_reachable=llm_reachable,
        db_ok=db_ok,
        models_ok=ok,
        models_missing=missing,
    )


# ---------------------------------------------------------------------------
# Registry endpoints
# ---------------------------------------------------------------------------


@app.get("/api/models", tags=["registry"])
async def list_models() -> dict:
    from app.config import get_models_registry
    return get_models_registry()


@app.get("/api/sites", tags=["registry"])
async def list_sites() -> dict:
    from app.config import get_sites_registry
    return get_sites_registry()


# ---------------------------------------------------------------------------
# Carbon forecast
# ---------------------------------------------------------------------------


@app.get("/api/carbon/forecast", response_model=list[CIForecast], tags=["carbon"])
async def carbon_forecast(
    zones: str = "IN-SO,IN-WE,IN-NO,SG,FI",
    horizon_s: int = 86400,
    window_s: int = 1800,
) -> list[CIForecast]:
    import time as _time
    from app.carbon.provider import get_carbon_provider

    provider = get_carbon_provider()
    zone_list = [z.strip() for z in zones.split(",") if z.strip()]
    now_ts = int(_time.time())
    results = []
    for zone in zone_list:
        forecast = await provider.forecast(zone, now_ts, horizon_s, window_s)
        results.append(forecast)
    return results


# ---------------------------------------------------------------------------
# Workflow validation
# ---------------------------------------------------------------------------


@app.post("/api/workflows/validate", response_model=ValidationResult, tags=["workflows"])
async def validate_workflow(workflow: Workflow) -> ValidationResult:
    from app.dag.graph import validate_dag

    return validate_dag(workflow)


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


@app.post("/api/plan", response_model=PlanResult, tags=["planning"])
async def create_plan(request: PlanRequest) -> PlanResult:
    # Lazy import to allow the module to load before Phase 2 implementation
    try:
        from app.scheduler.planner import plan
    except ImportError:
        raise HTTPException(status_code=501, detail="Scheduler not yet implemented (Phase 2).")

    result = await plan(
        workflow=request.workflow,
        constraints=request.constraints,
        weights=request.weights,
        preset=request.preset,
        solver=request.solver,
    )
    return result


@app.get("/api/plan/{plan_id}", response_model=PlanResult, tags=["planning"])
async def get_plan(plan_id: str) -> PlanResult:
    from app.db import load_plan
    data = load_plan(plan_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Plan {plan_id!r} not found.")
    return PlanResult(**data)


@app.post("/api/pareto", tags=["planning"])
async def pareto_frontier(request: PlanRequest) -> dict:
    try:
        from app.scheduler.pareto import compute_pareto
    except ImportError:
        raise HTTPException(status_code=501, detail="Pareto not yet implemented (Phase 4).")
    points = await compute_pareto(request)
    return {"points": [p.model_dump() for p in points]}


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@app.post("/api/runs", tags=["runs"])
async def create_run(request: RunRequest) -> dict:
    try:
        from app.executor.runner import start_run
    except ImportError:
        raise HTTPException(status_code=501, detail="Executor not yet implemented (Phase 3).")
    try:
        run_id = await start_run(request.plan_id, request.mode)
        return {"run_id": run_id}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to start run for plan %s: %s", request.plan_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to start run: {exc}")



@app.get("/api/runs/{run_id}/events", tags=["runs"])
async def run_events(run_id: str, request: Request):
    """SSE stream of run events."""
    from sse_starlette.sse import EventSourceResponse

    try:
        from app.executor.events import get_event_stream
    except ImportError:
        raise HTTPException(status_code=501, detail="Executor not yet implemented (Phase 3).")

    return EventSourceResponse(get_event_stream(run_id, request))


class QuickAnswerRequest(BaseModel):
    question: str
    quality_floor: float = 0.80
    mode: RunMode = "virtual"


@app.post("/api/quick-answer", tags=["runs"])
async def quick_answer(req: QuickAnswerRequest) -> dict:
    """Run a 3-step green question answering workflow (understand -> answer -> check)."""
    import json
    from pathlib import Path
    from app.schemas import Workflow, Constraints
    from app.scheduler.planner import plan
    from app.executor.runner import start_run

    wf_paths = [
        Path("workflows/quick_answer.json"),
        Path(__file__).resolve().parent.parent.parent / "workflows" / "quick_answer.json",
    ]
    wf_data = None
    for p in wf_paths:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                wf_data = json.load(f)
            break
    if not wf_data:
        raise HTTPException(status_code=500, detail="quick_answer workflow template not found")

    wf_data["inputs"]["question"] = req.question
    workflow = Workflow.model_validate(wf_data)

    plan_res = await plan(
        workflow=workflow,
        constraints=Constraints(deadline_s=180, quality_floor=req.quality_floor),
        solver="greedy",
    )

    run_id = await start_run(plan_res.plan_id, mode=req.mode)
    return {
        "plan_id": plan_res.plan_id,
        "run_id": run_id,
        "workflow": workflow.model_dump(),
        "totals": plan_res.totals.model_dump(),
    }


@app.get("/api/runs/{run_id}", tags=["runs"])
async def get_run(run_id: str) -> dict:
    from app.db import get_session, RunRecord, StepRunRecord
    from sqlmodel import select
    with get_session() as session:
        record = session.get(RunRecord, run_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found.")
        d = record.model_dump()
        step_records = session.exec(select(StepRunRecord).where(StepRunRecord.run_id == run_id)).all()
        d["steps"] = [
            {
                "step_id": s.step_id,
                "step_type": s.step_type,
                "model": s.model,
                "model_used": s.model_used,
                "site": s.site,
                "output_text": s.output_text,
                "dur_s": s.dur_s,
                "energy_wh": s.energy_wh,
                "carbon_g": s.carbon_g,
                "cost_usd": s.cost_usd,
                "verifier_score": s.verifier_score,
                "verifier_note": s.verifier_note,
                "escalated": s.escalated,
            }
            for s in step_records
        ]
        return d


@app.post("/api/runs/{run_id}/replan", tags=["runs"])
async def manual_replan(run_id: str) -> dict:
    try:
        from app.executor.replan import trigger_replan
    except ImportError:
        raise HTTPException(status_code=501, detail="Replanning not yet implemented (Phase 6).")
    result = await trigger_replan(run_id)
    return result


@app.get("/api/runs/{run_id}/receipt", tags=["runs"])
async def get_receipt(run_id: str) -> dict:
    try:
        from app.receipt.receipt import build_receipt
    except ImportError:
        raise HTTPException(status_code=501, detail="Receipt not yet implemented (Phase 2).")
    receipt = await build_receipt(run_id)
    return receipt.model_dump()


# ---------------------------------------------------------------------------
# Telemetry / learning
# ---------------------------------------------------------------------------


@app.get("/api/telemetry/stats", tags=["learning"])
async def telemetry_stats(step_type: str | None = None, model: str | None = None) -> list[dict]:
    from app.learning.predictor import get_all_states
    states = get_all_states()
    if step_type:
        states = [s for s in states if s["step_type"] == step_type]
    if model:
        states = [s for s in states if s["model"] == model]
    return states


@app.get("/api/predictor", tags=["learning"])
async def predictor_state() -> list[dict]:
    """Return all Beta-Binomial predictor states (Phase 6)."""
    from app.learning.predictor import get_all_states
    return get_all_states()


@app.post("/api/predictor/update/{run_id}", tags=["learning"])
async def predictor_update(run_id: str) -> dict:
    """Trigger learning update from a completed run's telemetry."""
    from app.learning.predictor import update_from_run
    n = update_from_run(run_id)
    return {"run_id": run_id, "records_processed": n}


@app.post("/api/calibrate", tags=["dev"])
async def trigger_calibration() -> dict:
    return {"message": "Run 'python scripts/calibrate.py' directly. (Phase 6)"}
