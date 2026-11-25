import pytest

from exga.llm.base import LLMClient
from exga.llm.mock import MockCall, MockLLMClient, Reply


def constant(text: str) -> Reply:
    return lambda _call, _sample_index: text


def test_mock_satisfies_the_client_interface() -> None:
    # the annotation makes mypy check that the mock matches the LLMClient protocol
    client: LLMClient = MockLLMClient(constant("120"), model_id="mock-v1")

    assert client.model_id == "mock-v1"


def test_returns_one_response_per_requested_sample_in_order() -> None:
    client = MockLLMClient(lambda _call, sample_index: f"answer {sample_index}")

    responses = client.generate("prompt", n=3, temperature=0.7)

    assert [response.text for response in responses] == ["answer 0", "answer 1", "answer 2"]


def test_reply_sees_the_request_so_greedy_and_sampled_calls_can_differ() -> None:
    client = MockLLMClient(lambda call, _index: "greedy" if call.temperature == 0 else "sampled")

    assert client.generate("prompt", n=1, temperature=0.0)[0].text == "greedy"
    assert client.generate("prompt", n=1, temperature=0.7)[0].text == "sampled"


def test_records_every_call_for_later_assertions() -> None:
    client = MockLLMClient(constant("120"))
    schema = {"type": "object"}

    client.generate("prompt", n=2, temperature=0.7, json_schema=schema, seed=7)

    assert client.calls == [
        MockCall(prompt="prompt", n=2, temperature=0.7, json_schema=schema, seed=7)
    ]


def test_identical_requests_give_identical_responses() -> None:
    client = MockLLMClient(lambda call, index: f"{call.prompt}:{index}", token_logprob=-0.1)

    first = client.generate("prompt", n=2, temperature=0.7, seed=1)
    second = client.generate("prompt", n=2, temperature=0.7, seed=1)

    assert first == second


def test_logprobs_are_absent_unless_configured() -> None:
    response = MockLLMClient(constant("120")).generate("prompt", n=1, temperature=0.0)[0]

    assert response.token_logprobs is None


def test_configured_logprob_is_given_to_every_token() -> None:
    client = MockLLMClient(constant("one two"), token_logprob=-0.5)

    response = client.generate("prompt", n=1, temperature=0.0)[0]

    assert response.token_logprobs is not None
    assert [(t.token, t.logprob) for t in response.token_logprobs] == [
        ("one", -0.5),
        ("two", -0.5),
    ]


def test_token_counts_are_whitespace_word_counts() -> None:
    response = MockLLMClient(constant("a b c")).generate("x y", n=1, temperature=0.0)[0]

    assert (response.input_tokens, response.output_tokens) == (2, 3)


def test_positive_logprob_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="token_logprob"):
        MockLLMClient(constant("120"), token_logprob=0.1)


def test_requesting_no_samples_is_rejected() -> None:
    client = MockLLMClient(constant("120"))

    with pytest.raises(ValueError, match="n must be at least 1"):
        client.generate("prompt", n=0, temperature=0.0)
    assert client.calls == []
