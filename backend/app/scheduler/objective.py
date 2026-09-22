"""
Normalized multi-objective function J (Phase 2).

J = w_latency * f_lat + w_cost * f_cost + w_energy * f_energy
  + w_carbon * f_carbon - w_quality * f_quality

All sub-objectives normalized to [0,1] using min-max over the option set.
This is used by the greedy scheduler to rank options at each step.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.schemas import ConfigOption, Weights


@dataclass
class ObjectiveScores:
    latency: float
    cost: float
    energy: float
    carbon: float
    quality: float
    total: float  # weighted sum (lower = better for latency/cost/energy/carbon; quality inverted)


def normalize_weights(w: Weights) -> dict[str, float]:
    """Return weights summing to 1.0."""
    total = w.latency + w.cost + w.energy + w.carbon + w.quality
    if total == 0:
        return {"latency": 0.2, "cost": 0.1, "energy": 0.1, "carbon": 0.4, "quality": 0.2}
    return {
        "latency": w.latency / total,
        "cost": w.cost / total,
        "energy": w.energy / total,
        "carbon": w.carbon / total,
        "quality": w.quality / total,
    }


def score_options(
    options: list[ConfigOption],
    weights: Weights,
    ci_g_per_kwh: float,
    robust_z: float = 1.28,
) -> list[tuple[ConfigOption, ObjectiveScores]]:
    """
    Score all options for a single step and return sorted (best first) list.

    ci_g_per_kwh: carbon intensity at the chosen site/window (gCO2e/kWh).
    robust_z: z-score for chance-constrained carbon (0 = mean, 1.28 ≈ 90%).
    """
    if not options:
        return []

    # Compute raw values
    lats = [o.dur_expected_s for o in options]
    costs = [o.cost_usd for o in options]
    energies = [o.energy_wh for o in options]
    # Carbon = energy_wh * CI [gCO2e/kWh] / 1000 + robust margin
    carbons = [
        o.energy_wh * ci_g_per_kwh / 1000.0
        + robust_z * (o.energy_wh_worst - o.energy_wh) * ci_g_per_kwh / 1000.0
        for o in options
    ]
    qualities = [o.quality for o in options]

    def _minmax(vals: list[float], v: float) -> float:
        mn, mx = min(vals), max(vals)
        if mx == mn:
            return 0.0
        return (v - mn) / (mx - mn)

    wn = normalize_weights(weights)
    scored: list[tuple[ConfigOption, ObjectiveScores]] = []

    for i, opt in enumerate(options):
        f_lat = _minmax(lats, lats[i])
        f_cost = _minmax(costs, costs[i])
        f_energy = _minmax(energies, energies[i])
        f_carbon = _minmax(carbons, carbons[i])
        f_quality = 1.0 - _minmax(qualities, qualities[i])  # invert: higher quality = lower penalty

        total = (
            wn["latency"] * f_lat
            + wn["cost"] * f_cost
            + wn["energy"] * f_energy
            + wn["carbon"] * f_carbon
            + wn["quality"] * f_quality
        )

        scored.append((
            opt,
            ObjectiveScores(
                latency=f_lat,
                cost=f_cost,
                energy=f_energy,
                carbon=f_carbon,
                quality=f_quality,
                total=total,
            ),
        ))

    # Sort best (lowest J) first
    scored.sort(key=lambda x: x[1].total)
    return scored
