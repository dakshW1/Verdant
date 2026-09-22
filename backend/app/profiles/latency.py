"""
Latency profile estimator (Phase 1).

Estimates expected and worst-case duration for a step-model-site combination.
Formula: dur = ttft + (tokens_out / tokens_per_s)
Worst-case = dur * latency_factor (from sites registry, e.g. 2.0 for cloud)
"""
from __future__ import annotations

from app.config import get_model_by_id, get_site_by_id, get_step_types_registry


def estimate_tokens_in(step_type: str, est_tokens_in: int | None) -> int:
    """Tokens in: use explicit override, else step_type prior."""
    if est_tokens_in is not None:
        return est_tokens_in
    reg = get_step_types_registry()
    st = reg.get("step_types", {}).get(step_type)
    if st is None:
        return 512
    return st.get("tok_in", 512)


def estimate_tokens_out(step_type: str, est_tokens_out: int | None, max_tokens_out: int = 800) -> int:
    """Tokens out: use explicit override, else step_type prior (capped by max_tokens_out)."""
    if est_tokens_out is not None:
        return min(est_tokens_out, max_tokens_out)
    reg = get_step_types_registry()
    st = reg.get("step_types", {}).get(step_type)
    if st is None:
        return min(200, max_tokens_out)
    prior = st.get("tok_out", 200)
    return min(prior, max_tokens_out)


def estimate_latency(
    model_id: str,
    site_id: str,
    tokens_in: int,
    tokens_out: int,
) -> tuple[int, int]:
    """
    Returns (dur_expected_s, dur_worstcase_s).
    dur = ttft + tokens_out / tokens_per_s
    worst = dur * site.latency_factor
    """
    model = get_model_by_id(model_id)
    site = get_site_by_id(site_id)

    if model is None or site is None:
        # Safe fallback
        return 10, 30

    rtt_s: float = site.get("rtt_s", 0.0)

    if model.get("provider") == "ollama":
        ttft = model.get("ttft_s", 0.3) + rtt_s
        tps = model.get("tokens_per_s", 25)
    else:
        ttft = model.get("ttft_s", 0.6) + rtt_s
        tps = model.get("tokens_per_s", 120)

    dur = ttft + tokens_out / max(tps, 1)

    # Worst-case multiplier from step_types registry (default 1.3)
    from app.config import get_step_types_registry
    wc = get_step_types_registry().get("wc_multiplier", 1.3)
    dur_worst = dur * wc

    return max(1, round(dur)), max(1, round(dur_worst))
