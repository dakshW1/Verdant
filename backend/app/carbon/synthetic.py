"""
Synthetic carbon intensity forecast model (Section 7.10 of AGENTS.md).

CI(t) = base * (1 - solar_dip*solar(h) - wind_night_dip*night(h)) + AR(1) noise
sigma(t) = sigma0 + kappa_per_h * hours_ahead

This is always available as a fallback when live/snapshot data is unavailable.
UI shows source badge = "synthetic".
"""
from __future__ import annotations

import math
import time as _time
from functools import lru_cache
from typing import Any

import numpy as np

from app.carbon.provider import CarbonProvider
from app.config import SEED, get_sites_registry
from app.schemas import CIForecast


def _solar(h: float) -> float:
    """Solar generation shape: peaks at 12:00, zero at 06:00 and 18:00."""
    val = math.sin(math.pi * (h - 6) / 12)
    return max(0.0, val)


def _night(h: float) -> float:
    """Night-wind bonus window: 22:00–05:00."""
    return 1.0 if (h >= 22 or h < 5) else 0.0


@lru_cache(maxsize=1)
def _get_synthetic_params() -> dict[str, dict[str, Any]]:
    reg = get_sites_registry()
    return reg.get("synthetic_ci", {})


def synthetic_ci_mean(zone: str, t: float) -> float:
    """
    Compute expected CI (gCO2e/kWh) for a given zone at Unix timestamp t.
    Deterministic (no noise); noise is added separately for forecast sigma.
    """
    params = _get_synthetic_params().get(zone)
    if params is None:
        # Unknown zone — return a mid-range value
        return 400.0

    utc_offset_h: float = params.get("utc_offset_h", 0.0)
    h_local = ((t / 3600.0) + utc_offset_h) % 24.0

    base: float = params["base"]
    solar_dip: float = params.get("solar_dip", 0.0)
    wind_night_dip: float = params.get("wind_night_dip", 0.0)

    ci = base * (1.0 - solar_dip * _solar(h_local) - wind_night_dip * _night(h_local))
    return max(20.0, ci)  # clip to minimum 20 gCO2e/kWh


def synthetic_ci_sigma(zone: str, hours_ahead: float) -> float:
    """
    Forecast uncertainty: sigma grows linearly with hours-ahead.
    sigma(t) = sigma0 + kappa_per_h * hours_ahead
    """
    params = _get_synthetic_params().get(zone)
    if params is None:
        return 30.0
    sigma0: float = params.get("sigma0", 20.0)
    kappa: float = params.get("kappa_per_h", 4.0)
    return sigma0 + kappa * hours_ahead


def _ar1_noise(n: int, sigma: float, seed: int | None = None) -> np.ndarray:
    """AR(1) noise: n_t = 0.8 * n_{t-1} + N(0, (0.3*sigma)^2)."""
    rng = np.random.default_rng(seed)
    noise = np.zeros(n)
    innov_std = 0.3 * sigma
    for i in range(n):
        prev = noise[i - 1] if i > 0 else 0.0
        noise[i] = 0.8 * prev + rng.normal(0, innov_std)
    return noise


class SyntheticCarbonProvider(CarbonProvider):
    """
    Always-available synthetic carbon intensity provider.
    Uses the diurnal model from Section 7.10 with AR(1) noise (seeded).
    """

    async def forecast(
        self,
        zone: str,
        start_ts: int,
        horizon_s: int,
        window_s: int,
    ) -> CIForecast:
        n_windows = max(1, horizon_s // window_s)
        mean_vals: list[float] = []
        sigma_vals: list[float] = []

        # Compute AR(1) noise seed from zone + start_ts for determinism
        noise_seed = (SEED + hash(zone) + start_ts // 3600) % (2**31)
        base_sigma = synthetic_ci_sigma(zone, 0)
        noise = _ar1_noise(n_windows, base_sigma, seed=noise_seed)

        for w in range(n_windows):
            t_w = start_ts + w * window_s + window_s / 2  # midpoint of window
            hours_ahead = (w * window_s) / 3600.0
            mu = synthetic_ci_mean(zone, t_w)
            sig = synthetic_ci_sigma(zone, hours_ahead)
            # Clip to minimum 20; add AR(1) noise (noisy mean, but sigma is forecast-only)
            mu_noisy = max(20.0, mu + noise[w])
            mean_vals.append(round(mu_noisy, 2))
            sigma_vals.append(round(sig, 2))

        return CIForecast(
            zone=zone,
            window_s=window_s,
            start_ts=start_ts,
            mean=mean_vals,
            sigma=sigma_vals,
            source="synthetic",
        )
