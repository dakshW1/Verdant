"""
Async DAG runner — Phase 3.

Executes a planned workflow asynchronously, respecting DAG dependencies.
Each step runs in its own asyncio Task. Steps whose predecessors are all
done are dispatched concurrently.

Flow per step:
  1. Render prompt (substitute {{upstream.X}} and {{input.Y}} variables)
  2. Call LLM client (MockClient / GeminiClient / OllamaClient)
  3. Run verifier on output
  4. If cascade mode and verifier fails: VoI decision → maybe escalate to large model
  5. Record telemetry in DB
  6. Emit SSE events
  7. Store output for downstream steps
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from typing import Any

from app.executor.clock import VirtualClock
from app.executor.events import RunEvent, emit, mark_active, mark_done
from app.schemas import (
    ConfigOption,
    PlanResult,
    RunMode,
    RunSummary,
    Step,
    StepPlan,
    StepRunResult,
    Totals,
)

logger = logging.getLogger(__name__)

# In-memory run registry: run_id → RunSummary (updated in real time)
_RUNS: dict[str, RunSummary] = {}


async def start_run(plan_id: str, mode: RunMode) -> str:
    """
    Launch a run for the given plan_id. Returns the new run_id immediately.
    The actual execution happens in the background.
    """
    from app.db import load_plan

    plan_data = load_plan(plan_id)
    if plan_data is None:
        raise ValueError(f"Plan {plan_id!r} not found")

    plan = PlanResult(**plan_data)
    run_id = str(uuid.uuid4())

    # Register run in DB
    _register_run(run_id, plan_id, mode)

    # Start background task
    asyncio.create_task(_execute_run(run_id, plan, mode))

    return run_id


def get_run(run_id: str) -> RunSummary | None:
    return _RUNS.get(run_id)


def _register_run(run_id: str, plan_id: str, mode: RunMode) -> None:
    from app.db import RunRecord, get_session
    from datetime import datetime, timezone

    summary = RunSummary(run_id=run_id, plan_id=plan_id, status="running", mode=mode)
    _RUNS[run_id] = summary
    mark_active(run_id)

    with get_session() as session:
        record = RunRecord(
            id=run_id,
            plan_id=plan_id,
            workflow_id="unknown",
            mode=mode,
            status="running",
        )
        session.add(record)
        session.commit()


async def _execute_run(run_id: str, plan: PlanResult, mode: RunMode) -> None:
    """
    Core async DAG executor.
    Builds a dependency graph from the plan steps and runs them concurrently
    where possible.
    """
    import os
    import json
    from pathlib import Path
    from app.schemas import Workflow
    from app.db import load_plan_record

    clock = VirtualClock(mode=mode)
    step_plans = {sp.step_id: sp for sp in plan.steps}
    outputs: dict[str, str] = {}   # step_id → output text
    results: list[StepRunResult] = []

    # Attempt to load workflow definition
    workflow: Workflow | None = None
    try:
        record = load_plan_record(plan.plan_id)
        if record and record.workflow_json:
            workflow = Workflow.model_validate_json(record.workflow_json)
        elif record and record.workflow_id:
            wf_path = Path("workflows") / f"{record.workflow_id}.json"
            if not wf_path.exists():
                wf_path = Path(__file__).resolve().parent.parent.parent.parent / "workflows" / f"{record.workflow_id}.json"
            if wf_path.exists():
                with open(wf_path, "r", encoding="utf-8") as f:
                    workflow = Workflow.model_validate(json.load(f))
    except Exception as exc:
        logger.debug("Could not load full workflow for plan %s: %s", plan.plan_id, exc)

    # Fallback to market_brief if plan matches fixture
    if workflow is None and (plan.plan_id == "fixture-market-brief-001" or any(s.step_id in ("r1", "r2", "r3", "fmt") for s in plan.steps)):
        try:
            wf_path = Path("workflows/market_brief.json")
            if not wf_path.exists():
                wf_path = Path(__file__).resolve().parent.parent.parent.parent / "workflows" / "market_brief.json"
            if wf_path.exists():
                with open(wf_path, "r", encoding="utf-8") as f:
                    workflow = Workflow.model_validate(json.load(f))
        except Exception:
            pass

    step_by_id = {s.id: s for s in workflow.steps} if workflow else {}

    emit(RunEvent(run_id=run_id, event_type="run_started", data={"plan_id": plan.plan_id}))

    try:
        completed: set[str] = set()
        pending: dict[str, asyncio.Task] = {}

        def _ready() -> list[StepPlan]:
            """Return steps whose predecessors are all completed and not yet running."""
            result = []
            running = set(pending.keys())
            for sp in plan.steps:
                if sp.step_id in completed or sp.step_id in running:
                    continue
                # If we have workflow step metadata, check exact depends_on
                st = step_by_id.get(sp.step_id)
                if st is not None:
                    if all(dep in completed for dep in st.depends_on):
                        result.append(sp)
                else:
                    # Fallback ordering heuristic: a step is ready if all earlier steps in plan.steps are done
                    idx = next(i for i, s in enumerate(plan.steps) if s.step_id == sp.step_id)
                    earlier = {plan.steps[j].step_id for j in range(idx)}
                    if all(eid in completed for eid in earlier):
                        result.append(sp)
            return result

        while len(completed) < len(plan.steps):
            ready_steps = _ready()
            for sp in ready_steps:
                if sp.step_id not in pending:
                    task = asyncio.create_task(
                        _run_step(run_id, sp, outputs, clock, mode, step=step_by_id.get(sp.step_id), workflow=workflow),
                        name=f"step-{sp.step_id}",
                    )
                    pending[sp.step_id] = task

            if not pending:
                # Deadlock guard
                logger.error("Run %s: no steps pending but %d not completed — deadlock", run_id, len(plan.steps) - len(completed))
                break

            # Wait for any pending step to complete
            done_tasks, _ = await asyncio.wait(
                pending.values(), return_when=asyncio.FIRST_COMPLETED
            )

            for task in done_tasks:
                # Find which step this task belongs to
                step_id = next(sid for sid, t in pending.items() if t is task)
                try:
                    result: StepRunResult = task.result()
                    results.append(result)
                    outputs[step_id] = result.output_text
                    completed.add(step_id)
                    emit(RunEvent(
                        run_id=run_id,
                        event_type="step_completed",
                        step_id=step_id,
                        data=result.model_dump(),
                    ))
                except Exception as exc:
                    logger.error("Step %s failed: %s", step_id, exc)
                    completed.add(step_id)  # mark done to avoid deadlock
                    emit(RunEvent(
                        run_id=run_id,
                        event_type="step_failed",
                        step_id=step_id,
                        data={"error": str(exc)},
                    ))
                del pending[step_id]

        # Determine terminal deliverable output
        terminal_step_id = plan.steps[-1].step_id if plan.steps else ""
        if workflow:
            non_sinks = {dep for s in workflow.steps for dep in s.depends_on}
            sinks = [s.id for s in workflow.steps if s.id not in non_sinks]
            if sinks and sinks[-1] in outputs:
                terminal_step_id = sinks[-1]

        final_output = outputs.get(terminal_step_id, "")
        if not final_output and outputs:
            final_output = list(outputs.values())[-1]

        # Compute final totals
        totals = _aggregate_totals(results)

        # Update run record
        summary = _RUNS[run_id]
        summary.status = "completed"
        summary.steps = results
        summary.totals = totals
        summary.final_output = final_output
        _update_run_db(run_id, "completed", totals, final_output=final_output)

        emit(RunEvent(
            run_id=run_id,
            event_type="run_completed",
            data={"totals": totals.model_dump(), "final_output": final_output},
        ))

        # Phase 6 — trigger online learning update from telemetry
        try:
            from app.learning.predictor import update_from_run as _update_predictor
            _update_predictor(run_id)
        except Exception as exc:
            logger.debug("Predictor update skipped: %s", exc)

    except Exception as exc:
        logger.exception("Run %s failed: %s", run_id, exc)
        if run_id in _RUNS:
            _RUNS[run_id].status = "failed"
        _update_run_db(run_id, "failed", None)
        emit(RunEvent(run_id=run_id, event_type="run_failed", data={"error": str(exc)}))
    finally:
        mark_done(run_id)


async def _run_step(
    run_id: str,
    sp: StepPlan,
    outputs: dict[str, str],
    clock: VirtualClock,
    mode: RunMode,
    step: Step | None = None,
    workflow: Workflow | None = None,
) -> StepRunResult:
    """Execute a single step, handling cascade escalation and telemetry."""
    from app.executor.llm_clients import get_client_for_model
    from app.executor.verifier import get_verifier_tau, verify_output
    from app.executor.voi import should_escalate
    from app.carbon.synthetic import synthetic_ci_mean

    opt = sp.option
    step_id = sp.step_id
    step_type = step.step_type if step else "summarization"
    verifier_kind = (step.verifier or "llm_judge") if step else "llm_judge"
    output_schema = step.output_schema if step else None

    from app.scheduler.explain import explain_option_search

    emit(RunEvent(
        run_id=run_id,
        event_type="step_started",
        step_id=step_id,
        data={
            "model": opt.model,
            "site": opt.site,
            "mode": opt.mode,
            "rationale": sp.rationale,
            "search_note": explain_option_search(step, opt) if step else None,
            "is_critical": sp.is_critical,
            "slack_s": sp.slack_s,
            "ci_g_per_kwh": sp.ci_g_per_kwh,
        },
    ))

    start_s = int(clock.now())

    # Render prompt with inputs, upstream outputs, and corpus data
    prompt = _render_prompt(opt, outputs, step=step, workflow=workflow)

    # Get LLM client and generate
    client = get_client_for_model(opt.model)
    from app.config import get_model_by_id
    model_config = get_model_by_id(opt.model)
    api_id = model_config["api_id"] if model_config else opt.model

    t0 = time.monotonic()
    llm_resp = await client.generate(
        prompt=prompt,
        model_api_id=api_id,
        max_tokens=opt.tokens_out,
    )

    # Simulate duration in virtual mode
    await clock.sleep(opt.dur_expected_s)

    # Verify output
    tau = get_verifier_tau()
    verifier_score, verifier_note = await verify_output(
        output_text=llm_resp.text,
        verifier=verifier_kind,
        step_type=step_type,
        prompt=prompt,
        output_schema=output_schema,
        judge_model_id="small",
    )

    escalated = False
    final_text = llm_resp.text
    model_used = opt.model
    model_api_id_used = llm_resp.model_used or api_id

    # Required quality is the stricter of the global acceptance threshold (tau)
    # and this step's own quality floor — so a step with min_quality=0.90 is held
    # to 90%, not just the generic 70% acceptance bar.
    required_quality = max(tau, step.min_quality if step else 0.0)
    verifier_failed = verifier_score < required_quality

    # Escalation target: the planned cascade partner if this is a cascade config,
    # otherwise fall back to the "large" tier directly so that ANY step (not just
    # cascade-mode ones) gets a real second chance at meeting its quality floor.
    escalate_target = None
    if verifier_failed:
        if opt.mode == "cascade" and opt.escalate_model:
            escalate_target = opt.escalate_model
        elif opt.model != "large":
            escalate_target = "large"

    # Stream the accept/escalate reasoning live, the moment the decision is
    # made -- before the (possibly slow) escalation call, not only after the
    # step finishes -- so the Run page can show *why* in real time.
    from app.scheduler.explain import explain_verification
    if step:
        emit(RunEvent(
            run_id=run_id,
            event_type="step_reasoning",
            step_id=step_id,
            data={
                "text": explain_verification(
                    step, opt, verifier_score, required_quality, tau,
                    will_escalate=bool(escalate_target), escalate_target=escalate_target,
                ),
                "escalating": bool(escalate_target),
                "verifier_score": verifier_score,
                "required_quality": required_quality,
            },
        ))

    if escalate_target:
        escalated = True
        escalate_model_config = get_model_by_id(escalate_target)
        escalate_api_id = escalate_model_config["api_id"] if escalate_model_config else escalate_target
        escalate_client = get_client_for_model(escalate_target)

        logger.info(
            "Step %s: score %.2f < required %.2f → escalating to %s",
            step_id, verifier_score, required_quality, escalate_target,
        )
        escalated_resp = await escalate_client.generate(
            prompt=prompt,
            model_api_id=escalate_api_id,
            max_tokens=opt.tokens_out,
        )
        await clock.sleep(opt.dur_expected_s // 2)  # extra time for escalation
        final_text = escalated_resp.text
        model_used = escalate_target
        model_api_id_used = escalated_resp.model_used or escalate_api_id

        verifier_score, verifier_note = await verify_output(
            output_text=final_text,
            verifier=verifier_kind,
            step_type=step_type,
            prompt=prompt,
            output_schema=output_schema,
            judge_model_id="small",
        )

    end_s = int(clock.now())

    # Compute actuals
    actual_tokens_in = llm_resp.tokens_in
    actual_tokens_out = llm_resp.tokens_out

    import time as _t
    ci = synthetic_ci_mean("IN-WE", _t.time())  # use current CI for actuals
    energy_wh = opt.energy_wh * (1 + (0.1 if escalated else 0))
    carbon_g = energy_wh * ci / 1000.0
    cost_usd = opt.cost_usd * (1 + (0.5 if escalated else 0))

    # Save telemetry with actual step output
    _save_telemetry(
        run_id=run_id,
        step_id=step_id,
        step_type=step_type,
        model=model_used,
        model_used=model_api_id_used,
        site=opt.site,
        tokens_in=actual_tokens_in,
        tokens_out=actual_tokens_out,
        dur_s=float(end_s - start_s),
        energy_wh=energy_wh,
        carbon_g=carbon_g,
        cost_usd=cost_usd,
        verifier_score=verifier_score,
        verifier_note=verifier_note,
        accepted=verifier_score >= tau,
        escalated=escalated,
        output_text=final_text,
    )

    return StepRunResult(
        step_id=step_id,
        option_used=opt,
        escalated=escalated,
        start_s=start_s,
        end_s=end_s,
        tokens_in=actual_tokens_in,
        tokens_out=actual_tokens_out,
        energy_wh=round(energy_wh, 6),
        carbon_g=round(carbon_g, 4),
        cost_usd=round(cost_usd, 8),
        verifier_score=verifier_score,
        output_text=final_text,
        model_used=model_api_id_used,
        verifier_note=verifier_note,
    )


def _render_prompt(
    opt: ConfigOption,
    outputs: dict[str, str],
    step: Step | None = None,
    workflow: Workflow | None = None,
) -> str:
    """
    Render prompt template with upstream outputs, inputs, and corpus data.
    Substitutes {{upstream.STEP_ID}}, {{input.KEY}}, and {{corpus.KEY}} placeholders.
    """
    import re
    from pathlib import Path

    if step and step.prompt_template:
        prompt = step.prompt_template

        # 1. Substitute inputs
        inputs = workflow.inputs if (workflow and workflow.inputs) else {}
        for k, v in inputs.items():
            prompt = prompt.replace(f"{{{{input.{k}}}}}", str(v))

        # 2. Substitute upstream step outputs
        # Supports both {{upstream.STEP_ID}} (canonical) and {{STEP_ID.output}}
        # (shorthand used by the frontend Builder's free-form workflows).
        for sid, out_text in outputs.items():
            prompt = prompt.replace(f"{{{{upstream.{sid}}}}}", out_text)
            prompt = prompt.replace(f"{{{{{sid}.output}}}}", out_text)

        # 3. Substitute corpus files if present
        corpus_matches = re.findall(r"\{\{corpus\.([a-zA-Z0-9_\-]+)\}\}", prompt)
        for ckey in corpus_matches:
            c_text = ""
            data_paths = [
                Path("workflows/data") / f"{ckey}.txt",
                Path(__file__).resolve().parent.parent.parent.parent / "workflows" / "data" / f"{ckey}.txt",
            ]
            for dp in data_paths:
                if dp.exists():
                    try:
                        with open(dp, "r", encoding="utf-8") as f:
                            c_text = f.read()
                        break
                    except Exception:
                        pass
            prompt = prompt.replace(f"{{{{corpus.{ckey}}}}}", c_text)

        return prompt

    # Fallback generic prompt if no template provided
    prompt = f"Complete the following {opt.mode} task using model {opt.model}:\n"
    if outputs:
        context = "\n\n".join(f"[{sid}]: {text[:300]}" for sid, text in outputs.items())
        prompt += f"\nContext from previous steps:\n{context}\n"
    prompt += "\nProvide a thorough and accurate response."
    return prompt


def _aggregate_totals(results: list[StepRunResult]) -> Totals:
    if not results:
        return Totals(makespan_s=0, cost_usd=0, energy_wh=0, carbon_g=0, carbon_g_robust=0, quality=0)
    makespan = max(r.end_s for r in results)
    return Totals(
        makespan_s=makespan,
        cost_usd=round(sum(r.cost_usd for r in results), 6),
        energy_wh=round(sum(r.energy_wh for r in results), 6),
        carbon_g=round(sum(r.carbon_g for r in results), 4),
        carbon_g_robust=round(sum(r.carbon_g for r in results) * 1.1, 4),
        quality=round(sum(r.verifier_score or 0 for r in results) / len(results), 4),
    )


def _save_telemetry(
    run_id: str, step_id: str, step_type: str, model: str, site: str,
    tokens_in: int, tokens_out: int, dur_s: float, energy_wh: float,
    carbon_g: float, cost_usd: float, verifier_score: float | None,
    accepted: bool | None, escalated: bool, output_text: str | None = None,
    model_used: str | None = None, verifier_note: str | None = None,
) -> None:
    try:
        from app.db import StepRunRecord, get_session
        with get_session() as session:
            record = StepRunRecord(
                run_id=run_id, step_id=step_id, step_type=step_type,
                model=model, model_used=model_used, site=site, tokens_in=tokens_in, tokens_out=tokens_out,
                dur_s=dur_s, energy_wh=energy_wh, carbon_g=carbon_g, cost_usd=cost_usd,
                verifier_score=verifier_score, verifier_note=verifier_note,
                accepted=accepted, escalated=escalated,
                output_text=output_text,
            )
            session.add(record)
            session.commit()
    except Exception as exc:
        logger.warning("Could not save telemetry for step %s: %s", step_id, exc)


def _update_run_db(run_id: str, status: str, totals: Totals | None, final_output: str | None = None) -> None:
    try:
        from app.db import RunRecord, get_session
        from datetime import datetime, timezone
        with get_session() as session:
            record = session.get(RunRecord, run_id)
            if record:
                record.status = status
                record.finished_at = datetime.now(timezone.utc).isoformat()
                if totals:
                    record.totals_json = totals.model_dump_json()
                if final_output:
                    record.final_output = final_output
                session.add(record)
                session.commit()
    except Exception as exc:
        logger.warning("Could not update run DB for %s: %s", run_id, exc)
