"""an `LLMClient` for any OpenAI-compatible chat-completions endpoint (ADR 0006).

the same client serves the hosted condition (OpenAI or a compatible provider) and the local
one (a vLLM or llama.cpp server); differences between endpoints are settings. the client is
thread-safe: worker threads share one instance, its connection pool, rate limiter and meter.
"""

import logging
import random
import time
from collections.abc import Callable, Mapping
from types import TracebackType
from typing import Self

import httpx
from pydantic import BaseModel, Field, ValidationError

from exga.errors import ConfigError, LLMResponseError
from exga.llm.limits import RateLimiter, UsageMeter
from exga.schemas import RawResponse, TokenLogprob
from exga.settings import HostedSettings

_log = logging.getLogger(__name__)

# request timeout, rate limit, server overload or failure: worth retrying
_TRANSIENT_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_HTTP_OK = 200
# provider error messages are quoted in exceptions up to this length
_MESSAGE_CHARS = 300
_JITTER = (0.5, 1.0)


class HostedLLMClient:
    """sends chat-completion requests and returns one `RawResponse` per sampled choice.

    per-sample token counts split the request's billed usage: the prompt tokens go to the
    first sample and completion tokens are shared out evenly, so summing a call's responses
    gives exactly what the provider billed.
    """

    def __init__(
        self,
        settings: HostedSettings,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        limiter: RateLimiter | None = None,
        meter: UsageMeter | None = None,
    ) -> None:
        if settings.model is None:
            raise ConfigError("hosted.model is not set; name the model to call")
        self._settings = settings
        self._model = settings.model
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._limiter = limiter or RateLimiter(
            settings.requests_per_minute, settings.burst, sleep=sleep
        )
        self.meter = meter or UsageMeter(
            input_price_per_million=settings.input_price_per_million,
            output_price_per_million=settings.output_price_per_million,
            budget_usd=settings.budget_usd,
        )
        headers: dict[str, str] = {}
        if settings.api_key is not None:
            headers["Authorization"] = f"Bearer {settings.api_key.get_secret_value()}"
        self._http = httpx.Client(
            base_url=settings.base_url,
            headers=headers,
            timeout=settings.timeout_seconds,
            transport=transport,
        )

    @property
    def model_id(self) -> str:
        """the model name together with its endpoint, so cached answers never mix servers."""
        return f"{self._model}@{self._settings.base_url}"

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """close the connection pool."""
        self._http.close()

    def generate(
        self,
        prompt: str,
        *,
        n: int,
        temperature: float,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,
    ) -> list[RawResponse]:
        """return n completions of prompt; see `LLMClient.generate`.

        when the endpoint cannot return n choices, n requests are sent with seeds seed,
        seed + 1, ... so that seeded samples still differ. raises LLMResponseError when the
        endpoint refuses the request or fails after all retries, and BudgetExceededError
        when the run's budget is spent.
        """
        if n < 1:
            raise ValueError(f"n must be at least 1, got {n}")
        if self._settings.supports_n:
            return self._complete(prompt, n, temperature, json_schema, seed)
        responses: list[RawResponse] = []
        for index in range(n):
            sample_seed = None if seed is None else seed + index
            responses += self._complete(prompt, 1, temperature, json_schema, sample_seed)
        return responses

    def _complete(
        self,
        prompt: str,
        n: int,
        temperature: float,
        json_schema: Mapping[str, object] | None,
        seed: int | None,
    ) -> list[RawResponse]:
        responses = self._post(self._body(prompt, n, temperature, json_schema, seed), n)
        _log.info(
            "model call: %s n=%d tokens in=%d out=%d",
            self._model,
            n,
            sum(response.input_tokens for response in responses),
            sum(response.output_tokens for response in responses),
        )
        return responses

    def _body(
        self,
        prompt: str,
        n: int,
        temperature: float,
        json_schema: Mapping[str, object] | None,
        seed: int | None,
    ) -> dict[str, object]:
        body: dict[str, object] = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "n": n,
            "temperature": temperature,
            self._settings.output_tokens_param: self._settings.max_output_tokens,
        }
        if seed is not None:
            body["seed"] = seed
        if self._settings.logprobs:
            body["logprobs"] = True
        if json_schema is not None and self._settings.structured_output:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "answer", "schema": dict(json_schema), "strict": True},
            }
        return body

    def _post(self, body: dict[str, object], n: int) -> list[RawResponse]:
        problem = ""
        retry_after: float | None = None
        for attempt in range(self._settings.max_retries + 1):
            if attempt:
                self._sleep(self._delay(attempt - 1, retry_after))
            self.meter.check_budget()
            self._limiter.acquire()
            retry_after = None
            try:
                response = self._http.post("/chat/completions", json=body)
            except httpx.TransportError as exc:
                problem = f"{type(exc).__name__}: {exc}"
                continue
            if response.status_code == _HTTP_OK:
                responses = _parse_completion(response.content, n)
                self.meter.record(
                    input_tokens=sum(r.input_tokens for r in responses),
                    output_tokens=sum(r.output_tokens for r in responses),
                )
                return responses
            problem = f"HTTP {response.status_code}: {_provider_message(response)}"
            if response.status_code not in _TRANSIENT_STATUS:
                raise LLMResponseError(f"{self._model} refused the request ({problem})")
            retry_after = _retry_after_seconds(response)
        attempts = self._settings.max_retries + 1
        raise LLMResponseError(f"{self._model} failed after {attempts} attempts ({problem})")

    def _delay(self, retry: int, retry_after: float | None) -> float:
        cap = self._settings.backoff_max_seconds
        if retry_after is not None:
            return min(retry_after, cap)
        # 2.0 ** retry, not 2 ** retry: int powers are typed Any because exponents can be negative
        backoff = min(cap, self._settings.backoff_initial_seconds * 2.0**retry)
        return backoff * self._rng.uniform(*_JITTER)


class _Usage(BaseModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)


class _TokenItem(BaseModel):
    token: str
    logprob: float


class _Logprobs(BaseModel):
    content: list[_TokenItem] | None = None


class _Message(BaseModel):
    content: str | None = None


class _Choice(BaseModel):
    index: int
    message: _Message
    logprobs: _Logprobs | None = None


class _Completion(BaseModel):
    """the part of a chat-completions response exga reads; other fields are ignored."""

    choices: list[_Choice]
    usage: _Usage


def _parse_completion(content: bytes, n: int) -> list[RawResponse]:
    try:
        completion = _Completion.model_validate_json(content)
    except ValidationError as exc:
        raise LLMResponseError(f"response is not a readable chat completion: {exc}") from exc
    if len(completion.choices) != n:
        raise LLMResponseError(f"asked for {n} choices, got {len(completion.choices)}")
    choices = sorted(completion.choices, key=lambda choice: choice.index)
    share, remainder = divmod(completion.usage.completion_tokens, n)
    return [
        RawResponse(
            text=choice.message.content or "",
            token_logprobs=_token_logprobs(choice.logprobs),
            input_tokens=completion.usage.prompt_tokens if index == 0 else 0,
            output_tokens=share + (1 if index < remainder else 0),
        )
        for index, choice in enumerate(choices)
    ]


def _token_logprobs(logprobs: _Logprobs | None) -> tuple[TokenLogprob, ...] | None:
    if logprobs is None or logprobs.content is None:
        return None
    # floating-point noise can put a near-certain token's logprob a hair above 0
    return tuple(
        TokenLogprob(token=item.token, logprob=min(0.0, item.logprob)) for item in logprobs.content
    )


def _provider_message(response: httpx.Response) -> str:
    try:
        message = str(response.json()["error"]["message"])
    except (ValueError, KeyError, TypeError):
        message = response.text
    return message[:_MESSAGE_CHARS]


def _retry_after_seconds(response: httpx.Response) -> float | None:
    # LLM APIs send Retry-After in seconds; the rare HTTP-date form falls back to backoff
    try:
        return max(0.0, float(response.headers["Retry-After"]))
    except (KeyError, ValueError):
        return None
