import time
from collections import deque
from threading import Lock


class LoginLimiter:
    """Counts failed logins per (client address, email) in a sliding window. In memory, so per process: it slows
    password guessing but a multi-process deployment needs a shared store (e.g. Redis) to enforce it globally."""

    def __init__(self, max_failures: int, window_seconds: int, clock=time.monotonic):
        self.max_failures = max_failures
        self.window = window_seconds
        self._clock = clock
        self._failures: dict[tuple[str, str], deque[float]] = {}
        self._lock = Lock()

    def _recent(self, key: tuple[str, str]) -> deque[float]:
        events = self._failures.get(key)
        if events is None:
            return deque()
        cutoff = self._clock() - self.window
        while events and events[0] <= cutoff:
            events.popleft()
        if not events:
            del self._failures[key]
        return events

    def retry_after(self, key: tuple[str, str]) -> int:
        """Seconds until another attempt is allowed; 0 when not blocked."""
        if self.max_failures <= 0:
            return 0
        with self._lock:
            events = self._recent(key)
            if len(events) < self.max_failures:
                return 0
            return max(1, int(events[0] + self.window - self._clock()) + 1)

    def record_failure(self, key: tuple[str, str]) -> None:
        if self.max_failures <= 0:
            return
        with self._lock:
            events = self._recent(key)
            events.append(self._clock())
            self._failures[key] = events

    def reset(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._failures.pop(key, None)
