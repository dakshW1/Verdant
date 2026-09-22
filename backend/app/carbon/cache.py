"""
Carbon cache + forecast module.
Caches CI forecasts in memory (15 min TTL) and on disk.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.config import CARBON_SNAPSHOT_PATH
from app.schemas import CIForecast

# In-memory cache: key=(zone, start_bucket, horizon_s, window_s) -> (fetched_ts, CIForecast)
_CACHE: dict[tuple, tuple[float, CIForecast]] = {}
_CACHE_TTL_S = 900  # 15 minutes


def _cache_key(zone: str, start_ts: int, horizon_s: int, window_s: int) -> tuple:
    # Bucket start_ts to the nearest 30 min to avoid cache misses on small time diffs
    bucket = (start_ts // 1800) * 1800
    return (zone, bucket, horizon_s, window_s)


def get_cached(zone: str, start_ts: int, horizon_s: int, window_s: int) -> CIForecast | None:
    key = _cache_key(zone, start_ts, horizon_s, window_s)
    entry = _CACHE.get(key)
    if entry is None:
        return None
    fetched_ts, forecast = entry
    if time.time() - fetched_ts > _CACHE_TTL_S:
        del _CACHE[key]
        return None
    return forecast


def set_cached(zone: str, start_ts: int, horizon_s: int, window_s: int, forecast: CIForecast) -> None:
    key = _cache_key(zone, start_ts, horizon_s, window_s)
    _CACHE[key] = (time.time(), forecast)


# ---------------------------------------------------------------------------
# Disk snapshot (for offline demo)
# ---------------------------------------------------------------------------


def load_snapshot(zone: str) -> list[dict] | None:
    """Load a previously snapshotted CI curve for a zone from disk."""
    if not CARBON_SNAPSHOT_PATH.exists():
        return None
    try:
        with open(CARBON_SNAPSHOT_PATH) as f:
            data = json.load(f)
        return data.get(zone)
    except Exception:
        return None


def save_snapshot(zone: str, forecast: CIForecast) -> None:
    """Append a CI curve to the on-disk snapshot file."""
    existing: dict[str, Any] = {}
    if CARBON_SNAPSHOT_PATH.exists():
        try:
            with open(CARBON_SNAPSHOT_PATH) as f:
                existing = json.load(f)
        except Exception:
            pass
    existing[zone] = forecast.model_dump()
    CARBON_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CARBON_SNAPSHOT_PATH, "w") as f:
        json.dump(existing, f, indent=2)
