"""
Energy profile estimator (Phase 1).

Energy = tokens_in * energy_per_tok_in + tokens_out * energy_per_tok_out
For local Ollama models, energy = device_power_w * duration_h
"""
from __future__ import annotations

from app.config import get_model_by_id, get_site_by_id


def estimate_energy(
    model_id: str,
    site_id: str,
    tokens_in: int,
    tokens_out: int,
    dur_expected_s: int,
    dur_worstcase_s: int,
) -> tuple[float, float]:
    """
    Returns (energy_wh_expected, energy_wh_worstcase).
    Cloud models: token-based formula.
    Local models: power × time formula.
    """
    model = get_model_by_id(model_id)
    if model is None:
        return 0.001, 0.003

    if model.get("provider") == "ollama":
        device_w: float = model.get("device_power_w", 35.0)
        energy_exp = device_w * (dur_expected_s / 3600.0)
        energy_worst = device_w * (dur_worstcase_s / 3600.0)
    else:
        e_in: float = model.get("energy_wh_per_tok_in", 0.00002)
        e_out: float = model.get("energy_wh_per_tok_out", 0.00005)
        energy_exp = tokens_in * e_in + tokens_out * e_out
        energy_worst = tokens_in * e_in * 1.2 + tokens_out * e_out * 1.5

    return round(energy_exp, 6), round(energy_worst, 6)
