from app.api.rate_limit import RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def make(max_requests: int = 2) -> tuple[RateLimiter, Clock]:
    clock = Clock()
    return RateLimiter(max_requests, 60, time_fn=clock), clock


def test_allows_requests_up_to_the_limit() -> None:
    limiter, _ = make(3)
    assert [limiter.check("a") for _ in range(3)] == [0, 0, 0]


def test_blocks_the_next_request_and_reports_the_wait() -> None:
    limiter, clock = make(2)
    limiter.check("a")
    limiter.check("a")
    clock.now = 10
    assert limiter.check("a") == 50  # 60 de ventana - 10 ya transcurridos


def test_slots_are_freed_when_the_window_expires() -> None:
    limiter, clock = make(2)
    limiter.check("a")
    limiter.check("a")
    clock.now = 60
    assert limiter.check("a") == 0


def test_blocked_attempts_do_not_extend_the_penalty() -> None:
    limiter, clock = make(1)
    limiter.check("a")
    clock.now = 30
    assert limiter.check("a") > 0  # bloqueado
    clock.now = 60
    assert limiter.check("a") == 0  # el intento bloqueado no se registró


def test_clients_are_independent() -> None:
    limiter, _ = make(1)
    assert limiter.check("a") == 0
    assert limiter.check("b") == 0
    assert limiter.check("a") > 0


def test_stale_clients_are_pruned() -> None:
    limiter, clock = make(1)
    for i in range(1100):
        limiter.check(f"ip-{i}")
    assert limiter.tracked_clients() == 1100

    clock.now = 100
    limiter.check("nuevo")
    assert limiter.tracked_clients() == 1