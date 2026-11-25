import json
import random
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from exga.errors import BudgetExceededError, ConfigError, LLMResponseError
from exga.llm.hosted import HostedLLMClient
from exga.llm.limits import RateLimiter
from exga.settings import HostedSettings

Handler = Callable[[httpx.Request], httpx.Response]
SCHEMA = {"type": "object", "properties": {"value": {"type": ["string", "null"]}}}


def completion(
    texts: list[str | None], *, prompt_tokens: int = 10, completion_tokens: int = 6
) -> dict[str, Any]:
    return {
        "id": "cmpl-1",
        "object": "chat.completion",
        "choices": [
            {
                "index": index,
                "message": {"role": "assistant", "content": text},
                "logprobs": {"content": [{"token": "ok", "logprob": -0.25, "top_logprobs": []}]},
                "finish_reason": "stop",
            }
            for index, text in enumerate(texts)
        ],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


class Recorder:
    """a MockTransport handler that replays queued outcomes and keeps every request body."""

    def __init__(self, *outcomes: httpx.Response | Exception) -> None:
        self.outcomes = list(outcomes)
        self.bodies: list[dict[str, object]] = []
        self.headers: list[httpx.Headers] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        self.headers.append(request.headers)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def ok(*texts: str | None, **usage: int) -> httpx.Response:
    return httpx.Response(200, json=completion(list(texts), **usage))


def make_client(
    recorder: Recorder, sleeps: list[float] | None = None, **overrides: object
) -> HostedLLMClient:
    settings = HostedSettings.model_validate(
        {"model": "test-model", "base_url": "https://llm.test/v1", "max_retries": 2} | overrides
    )
    record = sleeps if sleeps is not None else []
    return HostedLLMClient(
        settings,
        transport=httpx.MockTransport(recorder),
        sleep=record.append,
        rng=random.Random(0),
        limiter=RateLimiter(1e9, 1000),
    )


def test_the_request_carries_the_sampling_settings_and_schema() -> None:
    recorder = Recorder(ok("a", "b"))

    make_client(recorder).generate("prompt", n=2, temperature=0.7, json_schema=SCHEMA, seed=3)

    [body] = recorder.bodies
    assert body == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "prompt"}],
        "n": 2,
        "temperature": 0.7,
        "max_tokens": 512,
        "seed": 3,
        "logprobs": True,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": SCHEMA, "strict": True},
        },
    }


def test_optional_request_fields_follow_the_settings() -> None:
    recorder = Recorder(ok("a"))
    client = make_client(
        recorder,
        logprobs=False,
        structured_output=False,
        output_tokens_param="max_completion_tokens",
    )

    client.generate("prompt", n=1, temperature=0.0, json_schema=SCHEMA)

    [body] = recorder.bodies
    assert "logprobs" not in body
    assert "response_format" not in body
    assert "seed" not in body
    assert body["max_completion_tokens"] == 512


def test_the_api_key_is_sent_as_a_bearer_token_only_when_set() -> None:
    with_key = Recorder(ok("a"))
    without_key = Recorder(ok("a"))

    make_client(with_key, api_key=SecretStr("sk-x")).generate("p", n=1, temperature=0.0)
    make_client(without_key).generate("p", n=1, temperature=0.0)

    assert with_key.headers[0]["authorization"] == "Bearer sk-x"
    assert "authorization" not in without_key.headers[0]


def test_choices_come_back_in_index_order_with_logprobs() -> None:
    payload = completion(["first", "second"])
    payload["choices"] = list(reversed(payload["choices"]))
    recorder = Recorder(httpx.Response(200, json=payload))

    responses = make_client(recorder).generate("p", n=2, temperature=0.7)

    assert [r.text for r in responses] == ["first", "second"]
    assert responses[0].token_logprobs is not None
    assert responses[0].token_logprobs[0].logprob == -0.25


def test_token_counts_add_up_to_the_billed_usage() -> None:
    recorder = Recorder(ok("a", "b", "c", prompt_tokens=100, completion_tokens=31))
    client = make_client(recorder)

    responses = client.generate("p", n=3, temperature=0.7)

    assert [r.input_tokens for r in responses] == [100, 0, 0]
    assert [r.output_tokens for r in responses] == [11, 10, 10]
    assert client.meter.summary()["input_tokens"] == 100
    assert client.meter.summary()["output_tokens"] == 31


def test_a_refusal_with_no_content_becomes_empty_text() -> None:
    [response] = make_client(Recorder(ok(None))).generate("p", n=1, temperature=0.0)

    assert response.text == ""


def test_without_n_support_samples_are_separate_requests_with_distinct_seeds() -> None:
    recorder = Recorder(ok("a"), ok("b"), ok("c"))

    responses = make_client(recorder, supports_n=False).generate("p", n=3, temperature=0.7, seed=10)

    assert [r.text for r in responses] == ["a", "b", "c"]
    assert [body["seed"] for body in recorder.bodies] == [10, 11, 12]
    assert all(body["n"] == 1 for body in recorder.bodies)


def test_rate_limits_are_retried_after_the_server_requested_wait() -> None:
    sleeps: list[float] = []
    recorder = Recorder(httpx.Response(429, headers={"Retry-After": "7"}), ok("a"))

    [response] = make_client(recorder, sleeps).generate("p", n=1, temperature=0.0)

    assert response.text == "a"
    assert sleeps == [7.0]


def test_a_retry_after_beyond_the_cap_is_shortened() -> None:
    sleeps: list[float] = []
    recorder = Recorder(httpx.Response(503, headers={"Retry-After": "600"}), ok("a"))

    make_client(recorder, sleeps, backoff_max_seconds=30.0).generate("p", n=1, temperature=0.0)

    assert sleeps == [30.0]


def test_connection_failures_are_retried_with_growing_jittered_waits() -> None:
    sleeps: list[float] = []
    failure = httpx.ConnectError("connection refused")
    recorder = Recorder(failure, httpx.Response(500, text="boom"), ok("a"))

    make_client(recorder, sleeps, backoff_initial_seconds=1.0).generate("p", n=1, temperature=0.0)

    first, second = sleeps
    assert 0.5 <= first <= 1.0
    assert 1.0 <= second <= 2.0


def test_retries_stop_after_the_limit_and_report_the_last_problem() -> None:
    sleeps: list[float] = []
    recorder = Recorder(*(httpx.Response(502, text="bad gateway") for _ in range(3)))

    with pytest.raises(LLMResponseError, match=r"after 3 attempts \(HTTP 502: bad gateway\)"):
        make_client(recorder, sleeps).generate("p", n=1, temperature=0.0)

    assert len(sleeps) == 2


def test_client_errors_fail_at_once_with_the_provider_message() -> None:
    sleeps: list[float] = []
    error = {"error": {"message": "Unsupported parameter: 'logprobs'", "type": "invalid_request"}}
    recorder = Recorder(httpx.Response(400, json=error))

    with pytest.raises(LLMResponseError, match=r"refused the request.*Unsupported parameter"):
        make_client(recorder, sleeps).generate("p", n=1, temperature=0.0)

    assert sleeps == []


@pytest.mark.parametrize(
    "payload",
    [
        {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        {"choices": [{"index": 0, "message": {"content": "a"}}]},
        {"unexpected": True},
    ],
)
def test_malformed_completions_raise(payload: dict[str, object]) -> None:
    recorder = Recorder(httpx.Response(200, json=payload))

    with pytest.raises(LLMResponseError):
        make_client(recorder).generate("p", n=1, temperature=0.0)


def test_a_body_that_is_not_json_raises() -> None:
    recorder = Recorder(httpx.Response(200, text="<html>gateway</html>"))

    with pytest.raises(LLMResponseError, match="not a readable chat completion"):
        make_client(recorder).generate("p", n=1, temperature=0.0)


def test_the_budget_stops_requests_before_they_are_sent() -> None:
    recorder = Recorder(ok("a", prompt_tokens=1_000_000, completion_tokens=0), ok("b"))
    client = make_client(
        recorder, input_price_per_million=1.0, output_price_per_million=1.0, budget_usd=1.0
    )
    client.generate("p", n=1, temperature=0.0)

    with pytest.raises(BudgetExceededError):
        client.generate("p", n=1, temperature=0.0)

    assert len(recorder.bodies) == 1


def test_a_client_needs_a_model_name() -> None:
    with pytest.raises(ConfigError, match=r"hosted\.model"):
        HostedLLMClient(HostedSettings())


def test_the_model_id_names_model_and_endpoint() -> None:
    with make_client(Recorder()) as client:
        assert client.model_id == "test-model@https://llm.test/v1"


def test_n_below_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="n must be at least 1"):
        make_client(Recorder()).generate("p", n=0, temperature=0.0)
