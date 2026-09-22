"""
VirtualClock — Phase 3.

In virtual mode, time is simulated: each step's duration is "elapsed" instantly
but tracked as simulated seconds. In live mode, real wall-clock time is used.

The clock is used by the runner to record start/end times for each step.
"""
from __future__ import annotations

import asyncio
import time as _real_time
from typing import Literal


class VirtualClock:
    """
    A simple monotonic clock that either runs in real time (live mode)
    or advances by step durations (virtual mode).
    """

    def __init__(self, mode: Literal["virtual", "live"] = "virtual") -> None:
        self._mode = mode
        self._sim_now: float = 0.0          # virtual seconds elapsed
        self._real_start: float = _real_time.monotonic()

    @property
    def mode(self) -> str:
        return self._mode

    def now(self) -> float:
        """Current time in seconds from t0."""
        if self._mode == "live":
            return _real_time.monotonic() - self._real_start
        return self._sim_now

    async def sleep(self, seconds: float) -> None:
        """
        In virtual mode: advance sim clock instantly (no actual sleep).
        In live mode: sleep for real.
        """
        if self._mode == "virtual":
            self._sim_now += seconds
            # Yield control to the event loop so other tasks can run
            await asyncio.sleep(0)
        else:
            await asyncio.sleep(seconds)

    def advance(self, seconds: float) -> None:
        """Manually advance the virtual clock (virtual mode only)."""
        if self._mode == "virtual":
            self._sim_now += seconds

    def reset(self) -> None:
        self._sim_now = 0.0
        self._real_start = _real_time.monotonic()
