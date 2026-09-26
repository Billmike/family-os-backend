from collections import defaultdict
from threading import Lock
from time import monotonic


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def allow(self, key: str, *, max_hits: int, window_seconds: float) -> bool:
        now = monotonic()
        with self._lock:
            times = [t for t in self._hits[key] if now - t < window_seconds]
            if len(times) >= max_hits:
                self._hits[key] = times
                return False
            times.append(now)
            self._hits[key] = times
            return True

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


reset_ip_limiter = SlidingWindowLimiter()
