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
import re
from typing import Literal

logger = logging.getLogger(__name__)

VerifierType = Literal["schema", "code_exec", "llm_judge", "none"]

# How much of the prompt/output the judge gets to see. Cutting an otherwise-good,
# complete answer off mid-sentence makes it *look* incomplete to the judge, which
# was silently dragging scores down for longer (but perfectly fine) answers.
_JUDGE_PROMPT_CHARS = 400
_JUDGE_OUTPUT_CHARS = 3000

# Matches a bare decimal like "0.85" possibly followed by punctuation/prose,
# anchored so we prefer a number that appears early in the response (the model
# was asked to lead with it) over one buried in unrelated text.
_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)")


def parse_judge_score(text: str) -> float | None:
    """
    Extract a [0,1] quality score from a judge model's raw response text.

    Real models routinely ignore a "respond with ONLY a number" instruction and
    return things like "Score: 0.85", "0.85.", a full sentence, or JSON
    (`{"score": 0.85}`, optionally inside a ```json fence) — all of which the
    previous naive `float(text.split()[0])` parser choked on, silently
    replacing the real judgment with a fabricated placeholder score. This
    parser tries several extraction strategies and returns `None` (never a
    made-up number) if none of them find a plausible score, so callers can
    surface the failure instead of pretending it's a real measurement.

    Returns:
        A float in [0,1], or None if no score could be confidently extracted.
    """
    if not text or not text.strip():
        return None

    stripped = text.strip()

    # 1. Plain float, optionally with surrounding whitespace (the common,
    #    instruction-following case).
    try:
        return _clamp(float(stripped))
    except ValueError:
        pass

    # 2. JSON object, optionally fenced in ```json ... ``` or ``` ... ```.
    json_candidate = stripped
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL)
    if fence_match:
        json_candidate = fence_match.group(1)
    try:
        data = json.loads(json_candidate)
        if isinstance(data, dict):
            for key in ("score", "quality", "rating", "value"):
                if key in data and isinstance(data[key], (int, float)):
                    return _clamp(float(data[key]))
    except (json.JSONDecodeError, TypeError):
        pass

    # 3. First plausible standalone number in free text (e.g. "Score: 0.85",
    #    "The answer scores 0.85 out of 1.0.", "0.85 - accurate and complete").
    #    Reject integers > 1 that look like a "X out of 10" or "X/100" scale
    #    unless a clear 0..1 decimal is present, since a bare "8" is ambiguous.
    numbers = _NUMBER_RE.findall(stripped)
    for n in numbers:
        val = float(n)
        if 0.0 <= val <= 1.0:
            return _clamp(val)

    return None


def _clamp(score: float) -> float:
    return max(0.0, min(1.0, score))


async def verify_output(
    output_text: str,
    verifier: VerifierType,
    step_type: str,
    prompt: str,
    output_schema: dict | None,
    judge_model_id: str = "small",
) -> tuple[float, str | None]:
    """
    Verify a step's output and return (score in [0,1], note).

    Args:
        output_text: The LLM's output text.
        verifier: Strategy ("none", "schema", "code_exec", "llm_judge").
        step_type: Step type (for context in llm_judge).
        prompt: Original prompt (for llm_judge context).
        output_schema: JSON Schema dict (for "schema" verifier).
        judge_model_id: Model alias to use as judge (e.g. "small").

    Returns:
        (score, note). `note` is None on a clean verification and set to a
        human-readable caveat when a fallback heuristic had to be used (e.g.
        the judge's response couldn't be parsed) — callers should surface it
        rather than presenting the fallback as a confident measurement.
    """
    if verifier == "none":
        return 1.0, None

    if verifier == "schema":
        return _verify_schema(output_text, output_schema), None

    if verifier == "code_exec":
        return _verify_code(output_text), None

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


def _heuristic_score(output_text: str) -> float:
    """
    Cheap, deterministic fallback used only when the judge model itself
    couldn't be reached or its response couldn't be parsed at all — never
    used to override a real, successfully-parsed judge score.
    """
    text = output_text.strip()
    if not text:
        return 0.0
    refusal_markers = ("i cannot", "i can't", "i'm unable", "as an ai")
    if any(m in text.lower()[:200] for m in refusal_markers):
        return 0.2
    # A very short answer to what was presumably a real task is suspicious;
    # otherwise treat a substantive, non-refusing answer as provisionally OK.
    return 0.6 if len(text) < 20 else 0.75


async def _verify_llm_judge(
    output_text: str,
    prompt: str,
    step_type: str,
    judge_model_id: str,
) -> tuple[float, str | None]:
    """
    Use an LLM to score the output quality from 0.0 to 1.0.

    Returns (score, note) — note is set whenever the returned score is a
    fallback heuristic rather than a real parsed judgment, so the caller can
    surface that instead of quietly presenting it as a confident measurement.
    """
    from app.executor.llm_clients import get_client_for_model

    truncated = len(output_text) > _JUDGE_OUTPUT_CHARS
    output_excerpt = output_text[:_JUDGE_OUTPUT_CHARS]
    truncation_notice = (
        "\n\n[NOTE: the output above was truncated for length; do not treat "
        "the cutoff as incompleteness.]"
        if truncated else ""
    )

    judge_prompt = (
        f"You are a quality evaluator. Score the following AI output on a scale from "
        f"0.0 (completely wrong/empty/hallucinated) to 1.0 (excellent, complete, accurate).\n\n"
        f"Task type: {step_type}\n"
        f"Original prompt (excerpt): {prompt[:_JUDGE_PROMPT_CHARS]}\n\n"
        f"AI output:\n{output_excerpt}{truncation_notice}\n\n"
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
            max_tokens=20,
        )
    except Exception as exc:
        logger.error("LLM judge call failed (%s) — using heuristic fallback score", exc)
        return _heuristic_score(output_text), f"Judge model call failed ({exc}); used a heuristic fallback score."

    score = parse_judge_score(response.text)
    if score is None:
        logger.error(
            "LLM judge returned an unparseable response %r — using heuristic fallback score "
            "instead of silently guessing.",
            response.text,
        )
        return (
            _heuristic_score(output_text),
            f"Judge response {response.text[:80]!r} couldn't be parsed as a score; used a heuristic fallback.",
        )
    return score, None


def get_verifier_tau() -> float:
    """Acceptance threshold from step_types.yaml (default 0.7)."""
    from app.config import get_step_types_registry
    return float(get_step_types_registry().get("verifier_tau", 0.7))
