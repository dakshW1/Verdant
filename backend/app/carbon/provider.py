"""
Carbon provider factory — Phase 1.

Priority chain:
  1. ElectricityMaps (if ELECTRICITYMAPS_TOKEN set and not USE_SYNTHETIC_CARBON)
  2. UKGrid for GB zones (free, no key; only when not USE_SYNTHETIC_CARBON)
  3. Snapshot (offline disk cache)
  4. Synthetic (always-available fallback)

All real providers fall back to synthetic internally on error.
"""
from __future__ import annotations

from app.config import (
    CARBON_SNAPSHOT_PATH,
    ELECTRICITYMAPS_TOKEN,
    USE_SYNTHETIC_CARBON,
)
from app.schemas import CIForecast


class CarbonProvider:
    """Protocol-compatible base class."""

    async def forecast(
        self,
        zone: str,
        start_ts: int,
        horizon_s: int,
        window_s: int,
    ) -> CIForecast:
        raise NotImplementedError


class SnapshotProvider(CarbonProvider):
    """
    Offline fallback: serves the last saved carbon snapshot from disk.
    If no snapshot exists for the zone, delegates to synthetic.
    """

    async def forecast(
        self,
        zone: str,
        start_ts: int,
        horizon_s: int,
        window_s: int,
    ) -> CIForecast:
        from app.carbon.cache import load_snapshot
        from app.carbon.synthetic import SyntheticCarbonProvider

        raw = load_snapshot(zone)
        if raw is None:
            return await SyntheticCarbonProvider().forecast(zone, start_ts, horizon_s, window_s)

        # raw is a serialised CIForecast dict — reconstruct and refit to requested window
        cached = CIForecast(**raw)
        # If the cached forecast covers enough windows, reuse it; else fall through
        n_windows = max(1, horizon_s // window_s)
        if len(cached.mean) >= n_windows and cached.window_s == window_s:
            return CIForecast(
                zone=zone,
                window_s=window_s,
                start_ts=start_ts,
                mean=cached.mean[:n_windows],
                sigma=cached.sigma[:n_windows],
                source="snapshot",
            )
        # Window mismatch — use synthetic
        return await SyntheticCarbonProvider().forecast(zone, start_ts, horizon_s, window_s)


def get_carbon_provider() -> "CarbonProvider":
    """
    Factory: pick the best available provider for the current config.
    When USE_SYNTHETIC_CARBON=1, always returns SyntheticCarbonProvider.
    """
    if USE_SYNTHETIC_CARBON:
        from app.carbon.synthetic import SyntheticCarbonProvider
        return SyntheticCarbonProvider()

    if ELECTRICITYMAPS_TOKEN:
        from app.carbon.electricitymaps import ElectricityMapsProvider
        return ElectricityMapsProvider(ELECTRICITYMAPS_TOKEN)

    if CARBON_SNAPSHOT_PATH.exists():
        return SnapshotProvider()

    from app.carbon.synthetic import SyntheticCarbonProvider
    return SyntheticCarbonProvider()
