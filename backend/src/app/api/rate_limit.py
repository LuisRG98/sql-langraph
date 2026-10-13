import math
import threading
import time
from collections import deque
from collections.abc import Callable

_PRUNE_THRESHOLD = 1000


class RateLimiter:
    """Ventana deslizante en memoria: máximo N peticiones por ventana y por cliente."""

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        *,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._time = time_fn
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> int:
        """Devuelve 0 si la petición se permite (y la registra).

        Si no, devuelve los segundos que faltan para poder reintentar.
        """
        now = self._time()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self._window:
                hits.popleft()

            if len(hits) >= self._max:
                return max(1, math.ceil(self._window - (now - hits[0])))

            hits.append(now)
            if len(self._hits) > _PRUNE_THRESHOLD:
                self._prune(now)
            return 0

    def tracked_clients(self) -> int:
        with self._lock:
            return len(self._hits)

    def _prune(self, now: float) -> None:
        stale = [k for k, h in self._hits.items() if not h or now - h[-1] >= self._window]
        for key in stale:
            del self._hits[key]