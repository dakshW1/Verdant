"""
UK National Grid ESO carbon intensity provider (Phase 1).

Uses the free National Grid ESO API:
  GET https://api.carbonintensity.org.uk/intensity/date (no auth required)
  GET https://api.carbonintensity.org.uk/intensity/date/{from}/{to}

Only covers the GB zone. Falls back to synthetic for other zones.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.carbon.provider import CarbonProvider
from app.schemas import CIForecast

logger = logging.getLogger(__name__)

_BASE = "https://api.carbonintensity.org.uk"
_TIMEOUT = 10.0
_GB_ZONES = {"GB", "GB-GB", "GB-NIR"}  # zones this provider handles


class UKGridProvider(CarbonProvider):
    """National Grid ESO carbon intensity — GB only, no API key needed."""

    async def forecast(
        self,
        zone: str,
        start_ts: int,
        horizon_s: int,
        window_s: int,
    ) -> CIForecast:
        if zone not in _GB_ZONES:
            # Delegate to synthetic for non-GB zones
            from app.carbon.synthetic import SyntheticCarbonProvider
            return await SyntheticCarbonProvider().forecast(zone, start_ts, horizon_s, window_s)

        try:
            return await self._fetch_gb(zone, start_ts, horizon_s, window_s)
        except Exception as exc:
            logger.warning("UKGrid error for %s: %s — falling back to synthetic", zone, exc)
            from app.carbon.synthetic import SyntheticCarbonProvider
            return await SyntheticCarbonProvider().forecast(zone, start_ts, horizon_s, window_s)

    async def _fetch_gb(
        self,
        zone: str,
        start_ts: int,
        horizon_s: int,
        window_s: int,
    ) -> CIForecast:
        import datetime

        n_windows = max(1, horizon_s // window_s)

        # National Grid returns 30-min slots; request today + tomorrow
        from_dt = datetime.datetime.utcfromtimestamp(start_ts)
        to_dt = datetime.datetime.utcfromtimestamp(start_ts + horizon_s)
        from_str = from_dt.strftime("%Y-%m-%dT%H:%MZ")
        to_str = to_dt.strftime("%Y-%m-%dT%H:%MZ")

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_BASE}/intensity/{from_str}/{to_str}",
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        slots = data.get("data", [])
        if not slots:
            raise ValueError("Empty response from National Grid ESO")

        # Parse into (ts_mid, actual_or_forecast) pairs
        points: list[tuple[float, float]] = []
        for slot in slots:
            try:
                from_iso = slot["from"].replace("Z", "+00:00")
                to_iso = slot["to"].replace("Z", "+00:00")
                dt_from = datetime.datetime.fromisoformat(from_iso)
                dt_to = datetime.datetime.fromisoformat(to_iso)
                ts_mid = (dt_from.timestamp() + dt_to.timestamp()) / 2
                intensity = slot["intensity"]
                # Prefer forecast if actual is not yet available
                ci = intensity.get("actual") or intensity.get("forecast") or 200.0
                points.append((ts_mid, float(ci)))
            except Exception:
                continue

        if not points:
            raise ValueError("Could not parse National Grid ESO response")

        points.sort(key=lambda x: x[0])
        ts_arr = [p[0] for p in points]
        ci_arr = [p[1] for p in points]

        mean_vals: list[float] = []
        sigma_vals: list[float] = []
        for w in range(n_windows):
            t_mid = start_ts + w * window_s + window_s / 2
            ci_val = _interp(ts_arr, ci_arr, t_mid)
            hours_ahead = (w * window_s) / 3600.0
            sigma = 12.0 + 2.5 * hours_ahead
            mean_vals.append(round(max(20.0, ci_val), 2))
            sigma_vals.append(round(sigma, 2))

        return CIForecast(
            zone=zone,
            window_s=window_s,
            start_ts=start_ts,
            mean=mean_vals,
            sigma=sigma_vals,
            source="live",
        )


def _interp(xs: list[float], ys: list[float], x: float) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            frac = (x - xs[i]) / (xs[i + 1] - xs[i])
            return ys[i] + frac * (ys[i + 1] - ys[i])
    return ys[-1]
