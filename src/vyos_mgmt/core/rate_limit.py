"""Small in-process sliding-window rate limiter.

Suitable for a single-process deployment (the default for this app).  If the
API is scaled horizontally, replace this with a Redis-backed limiter; the
interface is intentionally tiny so that swap is local.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Record an attempt.

        Returns ``(allowed, retry_after_seconds)``.  When not allowed the
        attempt is not recorded, so an attacker cannot extend their own lockout
        indefinitely by hammering the endpoint.
        """

        now = time.monotonic()
        cutoff = now - window_seconds
        async with self._lock:
            bucket = self._events[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                retry_after = max(1, int(bucket[0] + window_seconds - now) + 1)
                return False, retry_after

            bucket.append(now)
            # Opportunistic cleanup of idle keys.
            if len(self._events) > 10_000:
                for stale_key in [k for k, v in self._events.items() if not v]:
                    del self._events[stale_key]
            return True, 0

    async def reset(self, key: str) -> None:
        async with self._lock:
            self._events.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._events.clear()


rate_limiter = SlidingWindowRateLimiter()
