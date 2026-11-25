import threading

import pytest

from exga.errors import BudgetExceededError
from exga.llm.limits import RateLimiter, UsageMeter


class FakeClock:
    """a monotonic clock that only moves when the code under test sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_requests_within_the_burst_do_not_wait() -> None:
    clock = FakeClock()
    limiter = RateLimiter(requests_per_minute=60, burst=3, clock=clock, sleep=clock.sleep)

    for _ in range(3):
        limiter.acquire()

    assert clock.sleeps == []


def test_requests_beyond_the_burst_wait_for_the_refill() -> None:
    clock = FakeClock()
    limiter = RateLimiter(requests_per_minute=60, burst=1, clock=clock, sleep=clock.sleep)

    for _ in range(4):
        limiter.acquire()

    assert clock.sleeps == pytest.approx([1.0, 1.0, 1.0])


def test_idle_time_refills_the_bucket_up_to_the_burst_only() -> None:
    clock = FakeClock()
    limiter = RateLimiter(requests_per_minute=120, burst=2, clock=clock, sleep=clock.sleep)
    limiter.acquire()
    limiter.acquire()

    clock.now += 60.0
    for _ in range(3):
        limiter.acquire()

    assert clock.sleeps == pytest.approx([0.5])


def test_the_rate_holds_across_threads() -> None:
    clock = FakeClock()
    lock = threading.Lock()

    def sleep(seconds: float) -> None:
        with lock:
            clock.sleep(seconds)

    limiter = RateLimiter(requests_per_minute=60, burst=1, clock=clock, sleep=sleep)
    threads = [threading.Thread(target=limiter.acquire) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # eight requests at one per second after a burst of one take at least seven seconds
    assert clock.now >= 7.0 - 1e-9


@pytest.mark.parametrize(("rate", "burst"), [(0.0, 1), (-1.0, 1), (60.0, 0)])
def test_limiter_rejects_impossible_settings(rate: float, burst: int) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        RateLimiter(requests_per_minute=rate, burst=burst)


def test_the_meter_totals_requests_and_tokens() -> None:
    meter = UsageMeter()

    meter.record(input_tokens=100, output_tokens=20)
    meter.record(input_tokens=50, output_tokens=5)

    assert (meter.requests, meter.input_tokens, meter.output_tokens) == (2, 150, 25)
    assert meter.cost_usd is None


def test_cost_follows_the_per_million_token_prices() -> None:
    meter = UsageMeter(input_price_per_million=2.0, output_price_per_million=8.0)

    meter.record(input_tokens=1_000_000, output_tokens=250_000)

    assert meter.cost_usd == pytest.approx(4.0)


def test_requests_are_refused_once_the_budget_is_spent() -> None:
    meter = UsageMeter(input_price_per_million=1.0, output_price_per_million=1.0, budget_usd=1.0)
    meter.check_budget()
    meter.record(input_tokens=600_000, output_tokens=400_000)

    with pytest.raises(BudgetExceededError, match=r"1\.00 USD"):
        meter.check_budget()


def test_spending_below_the_budget_is_allowed() -> None:
    meter = UsageMeter(input_price_per_million=1.0, output_price_per_million=1.0, budget_usd=1.0)
    meter.record(input_tokens=500_000, output_tokens=0)

    meter.check_budget()


def test_a_budget_without_prices_is_rejected() -> None:
    with pytest.raises(ValueError, match="needs both token prices"):
        UsageMeter(input_price_per_million=1.0, budget_usd=5.0)


def test_negative_token_counts_are_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        UsageMeter().record(input_tokens=-1, output_tokens=0)


def test_the_summary_is_a_plain_dict_for_run_reports() -> None:
    meter = UsageMeter(input_price_per_million=1.0, output_price_per_million=2.0)
    meter.record(input_tokens=1000, output_tokens=500)

    assert meter.summary() == {
        "requests": 1,
        "input_tokens": 1000,
        "output_tokens": 500,
        "cost_usd": pytest.approx(0.002),
    }
