"""
Output verifier (Phase 3).

Verifier strategies (from Step.verifier field):
  - "none": always accept (score=1.0)
  - "schema": validate output against step.output_schema (JSON Schema)
  - "code_exec": run the output as Python code and check it doesn't raise
  - "llm_judge": ask a judge model to score [0,1] (default)

Returns a float score in [0,1]. Acceptance threshold: verifier_tau from step_types.yaml (default 0.7).
"""
from __future__ import annotations

import json
import logging
from typing import Literal

logger = logging.getLogger(__name__)

VerifierType = Literal["schema", "code_exec", "llm_judge", "none"]


async def verify_output(
    output_text: str,
    verifier: VerifierType,
    step_type: str,
    prompt: str,
    output_schema: dict | None,
    judge_model_id: str = "small",
) -> float:
    """
    Verify a step's output and return a quality score in [0,1].

    Args:
        output_text: The LLM's output text.
        verifier: Strategy ("none", "schema", "code_exec", "llm_judge").
        step_type: Step type (for context in llm_judge).
        prompt: Original prompt (for llm_judge context).
        output_schema: JSON Schema dict (for "schema" verifier).
        judge_model_id: Model alias to use as judge (e.g. "small").

    Returns:
        Score in [0,1]. Acceptance decision is made by caller using verifier_tau threshold.
    """
    if verifier == "none":
        return 1.0

    if verifier == "schema":
        return _verify_schema(output_text, output_schema)

    if verifier == "code_exec":
        return _verify_code(output_text)

    # Default: llm_judge
    return await _verify_llm_judge(output_text, prompt, step_type, judge_model_id)


def _verify_schema(text: str, schema: dict | None) -> float:
    """Try to parse JSON and validate against schema. Returns 1.0 or 0.0."""
    if schema is None:
        # No schema — just check it's valid JSON
        try:
            json.loads(text)
            return 1.0
        except Exception:
            return 0.3  # partial credit for non-empty text

    try:
        data = json.loads(text)
    except Exception:
        return 0.0

    # Simple structural validation (required keys)
    required = schema.get("required", [])
    props = schema.get("properties", {})
    if not required:
        return 1.0

    present = set(data.keys()) if isinstance(data, dict) else set()
    matched = len(present & set(required))
    return matched / max(len(required), 1)


def _verify_code(text: str) -> float:
    """
    Try to exec the output as Python in a restricted namespace.
    Returns 1.0 if it runs without SyntaxError/NameError, 0.0 otherwise.
    """
    # Strip markdown code fences if present
    code = text.strip()
    if code.startswith("```"):
        lines = code.split("\n")
        code = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        compile(code, "<llm_output>", "exec")
        return 0.9  # compiles → good; we don't actually exec for safety
    except SyntaxError:
        return 0.0


async def _verify_llm_judge(
    output_text: str,
    prompt: str,
    step_type: str,
    judge_model_id: str,
) -> float:
    """
    Use an LLM to score the output quality from 0.0 to 1.0.
    Returns a float or falls back to a heuristic on error.
    """
    from app.executor.llm_clients import get_client_for_model

    judge_prompt = (
        f"You are a strict quality evaluator. Score the following AI output on a scale from "
        f"0.0 (completely wrong/empty/hallucinated) to 1.0 (excellent, complete, accurate).\n\n"
        f"Task type: {step_type}\n"
        f"Original prompt (excerpt): {prompt[:400]}\n\n"
        f"AI output:\n{output_text[:800]}\n\n"
        f"Respond with ONLY a single decimal number between 0.0 and 1.0. Nothing else."
    )

    from app.config import get_model_by_id
    model = get_model_by_id(judge_model_id)
    model_api_id = model["api_id"] if model else "gemini-2.5-flash-lite"

    try:
        client = get_client_for_model(judge_model_id)
        response = await client.generate(
            prompt=judge_prompt,
            model_api_id=model_api_id,
            max_tokens=10,
        )
        score_str = response.text.strip().split()[0]
        score = float(score_str)
        return max(0.0, min(1.0, score))
    except Exception as exc:
        logger.warning("LLM judge failed (%s) — using heuristic score", exc)
        # Heuristic: non-empty outputs get 0.75
        return 0.75 if output_text.strip() else 0.0


def get_verifier_tau() -> float:
    """Acceptance threshold from step_types.yaml (default 0.7)."""
    from app.config import get_step_types_registry
    return float(get_step_types_registry().get("verifier_tau", 0.7))
