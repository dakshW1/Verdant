"""
ElectricityMaps carbon provider (Phase 1).

Uses the ElectricityMaps API v3 (Free tier: /v3/carbon-intensity/history and /v3/forecast).
Falls back to the synthetic provider on any error or if no token is configured.
Free tier only returns 24h history for a single zone; adjust accordingly.
"""
from __future__ import annotations

import logging
import time as _time
from typing import Any

import httpx

from app.carbon.provider import CarbonProvider
from app.config import ELECTRICITYMAPS_TOKEN
from app.schemas import CIForecast

logger = logging.getLogger(__name__)

_BASE = "https://api.electricitymap.org/v3"
_TIMEOUT = 10.0


class ElectricityMapsProvider(CarbonProvider):
    """Live carbon intensity from ElectricityMaps API v3."""

    def __init__(self, token: str) -> None:
        self._token = token
        self._headers = {"auth-token": token}

    async def forecast(
        self,
        zone: str,
        start_ts: int,
        horizon_s: int,
        window_s: int,
    ) -> CIForecast:
        """
        Fetch from ElectricityMaps and downsample to window_s-sized windows.
        Falls back to synthetic on error.
        """
        try:
            return await self._fetch(zone, start_ts, horizon_s, window_s)
        except Exception as exc:
            logger.warning("ElectricityMaps error for %s: %s — falling back to synthetic", zone, exc)
            from app.carbon.synthetic import SyntheticCarbonProvider
            return await SyntheticCarbonProvider().forecast(zone, start_ts, horizon_s, window_s)

    async def _fetch(
        self,
        zone: str,
        start_ts: int,
        horizon_s: int,
        window_s: int,
    ) -> CIForecast:
        n_windows = max(1, horizon_s // window_s)
        mean_vals: list[float] = []
        sigma_vals: list[float] = []

        # Try the forecast endpoint first (may not be available on free tier)
        forecast_data = await self._get_forecast(zone)
        if forecast_data:
            # Map forecast data to our windows
            windows = self._resample(forecast_data, start_ts, n_windows, window_s)
            for mean, sigma in windows:
                mean_vals.append(round(mean, 2))
                sigma_vals.append(round(sigma, 2))
            return CIForecast(
                zone=zone,
                window_s=window_s,
                start_ts=start_ts,
                mean=mean_vals,
                sigma=sigma_vals,
                source="live",
            )

        # Fall back to latest point estimate (fills all windows with same value)
        ci_now = await self._get_latest(zone)
        for _ in range(n_windows):
            mean_vals.append(round(ci_now, 2))
            sigma_vals.append(30.0)  # unknown uncertainty

        return CIForecast(
            zone=zone,
            window_s=window_s,
            start_ts=start_ts,
            mean=mean_vals,
            sigma=sigma_vals,
            source="live",
        )

    async def _get_latest(self, zone: str) -> float:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_BASE}/carbon-intensity/latest",
                params={"zone": zone},
                headers=self._headers,
            )
            resp.raise_for_status()
            data = resp.json()
            return float(data["carbonIntensity"])

    async def _get_forecast(self, zone: str) -> list[dict[str, Any]] | None:
        """Returns list of {datetime: str, carbonIntensity: float} or None."""
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    f"{_BASE}/carbon-intensity/forecast",
                    params={"zone": zone},
                    headers=self._headers,
                )
                if resp.status_code == 402:  # payment required (not on free tier)
                    return None
                resp.raise_for_status()
                data = resp.json()
                return data.get("forecast", [])
        except httpx.HTTPStatusError:
            return None

    def _resample(
        self,
        forecast: list[dict[str, Any]],
        start_ts: int,
        n_windows: int,
        window_s: int,
    ) -> list[tuple[float, float]]:
        """Map forecast points to our window grid via linear interpolation."""
        import datetime

        # Parse forecast into (ts, ci) pairs
        points: list[tuple[float, float]] = []
        for pt in forecast:
            try:
                dt = datetime.datetime.fromisoformat(pt["datetime"].replace("Z", "+00:00"))
                ts = dt.timestamp()
                ci = float(pt["carbonIntensity"])
                points.append((ts, ci))
            except Exception:
                continue

        if not points:
            return [(300.0, 30.0)] * n_windows

        points.sort(key=lambda x: x[0])
        ts_arr = [p[0] for p in points]
        ci_arr = [p[1] for p in points]

        result: list[tuple[float, float]] = []
        for w in range(n_windows):
            t_mid = start_ts + w * window_s + window_s / 2
            # Linear interpolation
            if t_mid <= ts_arr[0]:
                ci_val = ci_arr[0]
            elif t_mid >= ts_arr[-1]:
                ci_val = ci_arr[-1]
            else:
                for i in range(len(ts_arr) - 1):
                    if ts_arr[i] <= t_mid <= ts_arr[i + 1]:
                        frac = (t_mid - ts_arr[i]) / (ts_arr[i + 1] - ts_arr[i])
                        ci_val = ci_arr[i] + frac * (ci_arr[i + 1] - ci_arr[i])
                        break
                else:
                    ci_val = ci_arr[-1]

            hours_ahead = (w * window_s) / 3600.0
            sigma = 15.0 + 3.0 * hours_ahead  # growing uncertainty
            result.append((max(20.0, ci_val), sigma))

        return result


def make_electricitymaps_provider() -> ElectricityMapsProvider | None:
    """Return provider if token is configured, else None."""
    if not ELECTRICITYMAPS_TOKEN:
        return None
    return ElectricityMapsProvider(ELECTRICITYMAPS_TOKEN)
