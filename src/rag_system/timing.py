"""Per-request stage timers for logs and the chat timing event."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from contextvars import Context, ContextVar, copy_context
from typing import Iterator

logger = logging.getLogger(__name__)
_active_timings: ContextVar[tuple[str, dict[str, float]] | None] = ContextVar(
    "rag_stage_timings", default=None
)


class ContextBoundIterator:
    """Resume a synchronous stream in one Context across Starlette worker calls."""

    def __init__(self, iterator: Iterator[str]):
        self._iterator = iter(iterator)
        self._context: Context = copy_context()

    def __iter__(self):
        return self

    def __next__(self) -> str:
        return self._context.run(next, self._iterator)


@contextmanager
def capture_stage_timings(request_id: str) -> Iterator[dict[str, float]]:
    timings: dict[str, float] = {}
    token = _active_timings.set((request_id, timings))
    try:
        yield timings
    finally:
        _active_timings.reset(token)


@contextmanager
def timed_stage(name: str) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        active = _active_timings.get()
        if active is not None:
            request_id, timings = active
            timings[name] = round(timings.get(name, 0.0) + elapsed_ms, 2)
            logger.info(
                "stage_timing request_id=%s stage=%s duration_ms=%.2f",
                request_id, name, elapsed_ms,
            )
