"""
Rationale string generator (Phase 2).

Produces human-readable explanations for each step plan decision.
These appear in the Plan page and the Carbon Receipt.
"""
from __future__ import annotations

from app.schemas import ConfigOption, Step


def explain_step(
    step: Step,
    option: ConfigOption,
    start_s: int,
    slack_s: int,
    is_critical: bool,
    ci_g_per_kwh: float,
) -> str:
    """
    Generate a 1–2 sentence rationale for why this (model, site, mode) was chosen.
    """
    parts: list[str] = []

    # Model + mode selection rationale
    if option.mode == "cascade":
        parts.append(
            f"Using cascade ({option.model} → {option.escalate_model}): "
            f"the small model accepts ~{int((option.p_accept or 0.65) * 100)}% of outputs "
            f"at lower cost and energy, escalating to {option.escalate_model} only when needed."
        )
    else:
        tier_label = {"small": "S-tier (fastest/cheapest)", "medium": "M-tier (balanced)",
                      "large": "L-tier (highest quality)", "local-3b": "local 3B (zero cost)"}.get(
            option.model, option.model
        )
        parts.append(f"Chose {tier_label} model '{option.model}' on site '{option.site}'.")

    # Carbon intensity context
    ci_label = _ci_label(ci_g_per_kwh)
    parts.append(
        f"Grid carbon intensity at {option.site}: {ci_g_per_kwh:.0f} gCO₂e/kWh ({ci_label})."
    )

    # Timing rationale
    if is_critical:
        parts.append(
            f"This step is on the critical path — no deferral possible "
            f"(scheduled at t+{start_s}s with 0s slack)."
        )
    elif slack_s > 0:
        m, s = divmod(slack_s, 60)
        slack_str = f"{m}m {s}s" if m else f"{s}s"
        parts.append(
            f"Non-critical with {slack_str} slack; "
            f"{'deferred to a lower-CI window.' if start_s > 0 else 'starts immediately.'}"
        )

    # Step type hint
    notes = {
        "reasoning": "Reasoning steps often need a larger model for reliability.",
        "code": "Code generation has high small-model failure rates; cascade or large model preferred.",
        "formatting": "Formatting is mechanical — small model usually sufficient.",
        "extraction": "Extraction from context is mostly lookup; small models competitive.",
    }
    if step.step_type in notes:
        parts.append(notes[step.step_type])

    return " ".join(parts)


def _ci_label(ci: float) -> str:
    if ci < 150:
        return "very low 🌿"
    elif ci < 300:
        return "low 🟢"
    elif ci < 500:
        return "moderate 🟡"
    elif ci < 700:
        return "high 🟠"
    else:
        return "very high 🔴"
