"""Lightweight in-process rate limiting for the public, OpenAI-spending endpoints.

A fixed-window counter keyed by client IP (public form) or API key (partner
intake) keeps an anonymous flood from running up the OpenAI bill or spamming the
lead table. It's per-process — with multiple uvicorn workers the effective limit
is (limit x workers), which is fine for cost protection; a hard, cluster-wide
limit would need Redis.
"""
import time
from threading import Lock


class FixedWindowRateLimiter:
    def __init__(self, max_per_window: int, window_seconds: int = 60):
        self.max = max_per_window
        self.window = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        """Record a hit for `key`; return False if it's over the limit."""
        if self.max <= 0:
            return True  # disabled
        now = time.time()
        cutoff = now - self.window
        with self._lock:
            recent = [t for t in self._hits.get(key, ()) if t > cutoff]
            if len(recent) >= self.max:
                self._hits[key] = recent  # prune even when blocking
                return False
            recent.append(now)
            self._hits[key] = recent
            return True
