from app.ratelimit import LoginLimiter
from tests.conftest import register

KEY = ("1.2.3.4", "a@example.com")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_blocks_after_max_failures_and_recovers_when_window_passes():
    clock = Clock()
    limiter = LoginLimiter(3, 60, clock)
    for _ in range(3):
        assert limiter.retry_after(KEY) == 0
        limiter.record_failure(KEY)
    assert 0 < limiter.retry_after(KEY) <= 61
    assert limiter.retry_after(("1.2.3.4", "other@example.com")) == 0
    clock.now += 61
    assert limiter.retry_after(KEY) == 0


def test_success_clears_failures_and_zero_disables():
    limiter = LoginLimiter(2, 60, Clock())
    limiter.record_failure(KEY)
    limiter.reset(KEY)
    limiter.record_failure(KEY)
    assert limiter.retry_after(KEY) == 0
    off = LoginLimiter(0, 60, Clock())
    for _ in range(50):
        off.record_failure(KEY)
    assert off.retry_after(KEY) == 0


def test_login_locks_out_after_repeated_failures(make_client):
    c = make_client(login_max_failures=3)
    register(c, "a@example.com")
    bad = {"email": "a@example.com", "password": "wrong-wrong"}
    assert [c.post("/auth/login", json=bad).status_code for _ in range(3)] == [401, 401, 401]
    blocked = c.post("/auth/login", json=bad)
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0
    # Even the right password is refused during the lockout, and other accounts are unaffected.
    assert c.post("/auth/login", json={"email": "a@example.com", "password": "password-123"}).status_code == 429
    register(c, "b@example.com")
    assert c.post("/auth/login", json={"email": "b@example.com", "password": "password-123"}).status_code == 200


def test_unknown_emails_are_limited_too(make_client):
    c = make_client(login_max_failures=2)
    bad = {"email": "ghost@example.com", "password": "wrong-wrong"}
    assert [c.post("/auth/login", json=bad).status_code for _ in range(3)] == [401, 401, 429]
