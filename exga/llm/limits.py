"""request-rate and spending limits shared by all threads of a run (spec 0A.5).

both classes are thread-safe and take their clock and sleep function as arguments, so tests
run them on a fake clock without waiting.
"""

import threading
import time
from collections.abc import Callable

from exga.errors import BudgetExceededError

_SECONDS_PER_MINUTE = 60.0
_TOKENS_PER_MILLION = 1_000_000


class RateLimiter:
    """a token bucket: up to burst requests at once, refilled at requests_per_minute.

    acquire blocks the calling thread until a request may be sent. waiting happens outside
    the lock, so one sleeping thread never stops another from taking a token that has
    refilled meanwhile.
    """

    def __init__(
        self,
        requests_per_minute: float,
        burst: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if requests_per_minute <= 0 or burst <= 0:
            raise ValueError(
                f"requests_per_minute and burst must be positive, got {requests_per_minute}"
                f" and {burst}"
            )
        self._rate = requests_per_minute / _SECONDS_PER_MINUTE
        self._capacity = float(burst)
        self._tokens = float(burst)
        self._clock = clock
        self._sleep = sleep
        self._updated = clock()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """take one token, waiting until one is available."""
        while True:
            with self._lock:
                now = self._clock()
                self._tokens = min(
                    self._capacity, self._tokens + (now - self._updated) * self._rate
                )
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            self._sleep(wait)


class UsageMeter:
    """totals of requests, tokens and, when prices are given, cost in USD for one run.

    prices are USD per million tokens. with a budget, check_budget refuses new requests once
    the spent cost reaches it; a request already in flight may overshoot by its own cost.
    """

    def __init__(
        self,
        *,
        input_price_per_million: float | None = None,
        output_price_per_million: float | None = None,
        budget_usd: float | None = None,
    ) -> None:
        priced = input_price_per_million is not None and output_price_per_million is not None
        if budget_usd is not None and not priced:
            raise ValueError("a budget needs both token prices to measure spending against")
        self._input_price = input_price_per_million
        self._output_price = output_price_per_million
        self._budget = budget_usd
        self._lock = threading.Lock()
        self.requests = 0
        self.input_tokens = 0
        self.output_tokens = 0

    @property
    def cost_usd(self) -> float | None:
        """spending so far in USD, or None when prices are not configured."""
        if self._input_price is None or self._output_price is None:
            return None
        return (
            self.input_tokens * self._input_price + self.output_tokens * self._output_price
        ) / _TOKENS_PER_MILLION

    def check_budget(self) -> None:
        """raise BudgetExceededError when the budget is set and already spent."""
        with self._lock:
            cost = self.cost_usd
        if self._budget is not None and cost is not None and cost >= self._budget:
            raise BudgetExceededError(
                f"spent {cost:.2f} USD of a {self._budget:.2f} USD budget;"
                " no more requests are sent"
            )

    def record(self, *, input_tokens: int, output_tokens: int) -> None:
        """add one completed request and the tokens it was billed for."""
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError(
                f"token counts must be non-negative, got {input_tokens}, {output_tokens}"
            )
        with self._lock:
            self.requests += 1
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens

    def summary(self) -> dict[str, int | float | None]:
        """the totals as a dict, for the run's cost summary."""
        with self._lock:
            return {
                "requests": self.requests,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cost_usd": self.cost_usd,
            }
