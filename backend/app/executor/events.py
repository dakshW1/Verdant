"""
Event bus + SSE stream for live run updates (Phase 3).

Events are emitted by the runner for each step lifecycle:
  - run_started
  - step_started
  - step_completed
  - step_failed
  - run_completed
  - run_failed

SSE clients receive a JSON-encoded event object.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

# Global event bus: run_id → asyncio.Queue of event dicts
_BUS: dict[str, asyncio.Queue] = defaultdict(lambda: asyncio.Queue(maxsize=256))

# Track which run_ids are still active (set to False on completion/failure)
_ACTIVE: dict[str, bool] = {}

_SENTINEL = object()  # signals end of stream


@dataclass
class RunEvent:
    run_id: str
    event_type: str            # run_started | step_started | step_completed | step_failed | run_completed | run_failed
    step_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


def emit(event: RunEvent) -> None:
    """Emit an event to the bus for the given run_id (non-blocking)."""
    try:
        q = _BUS[event.run_id]
        q.put_nowait(event)
    except asyncio.QueueFull:
        logger.warning("Event bus full for run %s — dropping event %s", event.run_id, event.event_type)


def mark_active(run_id: str) -> None:
    _ACTIVE[run_id] = True


def mark_done(run_id: str) -> None:
    _ACTIVE[run_id] = False
    # Put sentinel so the SSE generator can exit
    try:
        _BUS[run_id].put_nowait(_SENTINEL)
    except asyncio.QueueFull:
        pass


async def get_event_stream(run_id: str, request: Any) -> AsyncIterator[dict]:
    """
    AsyncIterator that yields SSE-compatible dicts for a given run_id.
    Stops when the run completes (sentinel received) or client disconnects.
    """
    q = _BUS[run_id]

    while True:
        # Check client disconnect (starlette request)
        if hasattr(request, "is_disconnected") and await request.is_disconnected():
            logger.info("SSE client disconnected for run %s", run_id)
            break

        try:
            item = await asyncio.wait_for(q.get(), timeout=30.0)
        except asyncio.TimeoutError:
            # Send keepalive comment
            yield {"data": ": keepalive", "event": "keepalive"}
            continue

        if item is _SENTINEL:
            break

        event: RunEvent = item
        payload = {
            "run_id": event.run_id,
            "event_type": event.event_type,
            "step_id": event.step_id,
            **event.data,
        }
        yield {
            "data": json.dumps(payload),
            "event": event.event_type,
        }


def cleanup_run(run_id: str) -> None:
    """Remove bus entry after SSE stream is consumed."""
    _BUS.pop(run_id, None)
    _ACTIVE.pop(run_id, None)
