import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from exga.errors import LLMResponseError
from exga.llm.cache import CachedLLMClient, cache_key
from exga.llm.mock import MockCall, MockLLMClient


def numbered(call: MockCall, index: int) -> str:
    return f"{call.prompt} sample {index}"


@pytest.fixture
def inner() -> MockLLMClient:
    return MockLLMClient(numbered, token_logprob=-0.5)


def test_a_repeated_call_is_served_from_disk(tmp_path: Path, inner: MockLLMClient) -> None:
    client = CachedLLMClient(inner, tmp_path)

    first = client.generate("p", n=2, temperature=0.7, seed=1)
    second = client.generate("p", n=2, temperature=0.7, seed=1)

    assert second == first
    assert len(inner.calls) == 1
    assert (client.hits, client.misses) == (1, 1)


def test_a_new_client_on_the_same_folder_reuses_the_cache(
    tmp_path: Path, inner: MockLLMClient
) -> None:
    CachedLLMClient(inner, tmp_path).generate("p", n=1, temperature=0.0)
    replay = MockLLMClient(lambda _call, _index: "different", token_logprob=-0.5)

    [response] = CachedLLMClient(replay, tmp_path).generate("p", n=1, temperature=0.0)

    assert response.text == "p sample 0"
    assert replay.calls == []


@pytest.mark.parametrize(
    ("prompt", "n", "temperature", "seed", "json_schema"),
    [
        ("q", 2, 0.7, 1, None),
        ("p", 3, 0.7, 1, None),
        ("p", 2, 0.0, 1, None),
        ("p", 2, 0.7, 2, None),
        ("p", 2, 0.7, 1, {"type": "object"}),
    ],
)
def test_any_change_in_the_request_is_a_miss(
    tmp_path: Path,
    inner: MockLLMClient,
    prompt: str,
    n: int,
    temperature: float,
    seed: int,
    json_schema: dict[str, object] | None,
) -> None:
    client = CachedLLMClient(inner, tmp_path)

    client.generate("p", n=2, temperature=0.7, seed=1)
    client.generate(prompt, n=n, temperature=temperature, seed=seed, json_schema=json_schema)

    assert client.misses == 2


def test_the_key_depends_on_the_model() -> None:
    first = cache_key("a", "p", n=1, temperature=0.0, seed=None, json_schema=None)

    assert first != cache_key("b", "p", n=1, temperature=0.0, seed=None, json_schema=None)


def test_the_key_ignores_json_key_order() -> None:
    first = cache_key("m", "p", n=1, temperature=0.0, seed=None, json_schema={"a": 1, "b": 2})
    second = cache_key("m", "p", n=1, temperature=0.0, seed=None, json_schema={"b": 2, "a": 1})

    assert first == second


def test_entries_are_readable_json_that_names_the_request(
    tmp_path: Path, inner: MockLLMClient
) -> None:
    CachedLLMClient(inner, tmp_path).generate("p", n=1, temperature=0.0, seed=7)

    [entry] = tmp_path.rglob("*.json")
    content = json.loads(entry.read_text(encoding="utf-8"))

    assert content["request"] == {
        "model_id": "mock",
        "prompt": "p",
        "n": 1,
        "temperature": 0.0,
        "seed": 7,
        "json_schema": None,
    }
    assert content["responses"][0]["text"] == "p sample 0"


def test_no_temporary_files_are_left_behind(tmp_path: Path, inner: MockLLMClient) -> None:
    CachedLLMClient(inner, tmp_path).generate("p", n=1, temperature=0.0)

    assert [path.suffix for path in tmp_path.rglob("*") if path.is_file()] == [".json"]


def test_a_corrupt_entry_raises_instead_of_being_used(tmp_path: Path, inner: MockLLMClient) -> None:
    client = CachedLLMClient(inner, tmp_path)
    client.generate("p", n=1, temperature=0.0)
    [entry] = tmp_path.rglob("*.json")
    entry.write_text("{not json", encoding="utf-8")

    with pytest.raises(LLMResponseError, match="delete it"):
        client.generate("p", n=1, temperature=0.0)


def test_an_entry_with_the_wrong_number_of_responses_raises(
    tmp_path: Path, inner: MockLLMClient
) -> None:
    client = CachedLLMClient(inner, tmp_path)
    client.generate("p", n=2, temperature=0.7)
    [entry] = tmp_path.rglob("*.json")
    content = json.loads(entry.read_text(encoding="utf-8"))
    content["responses"] = content["responses"][:1]
    entry.write_text(json.dumps(content), encoding="utf-8")

    with pytest.raises(LLMResponseError, match="1 responses, expected 2"):
        client.generate("p", n=2, temperature=0.7)


def test_the_wrapper_reports_the_inner_model(tmp_path: Path, inner: MockLLMClient) -> None:
    assert CachedLLMClient(inner, tmp_path).model_id == "mock"


def test_counters_stay_exact_when_threads_share_the_client(
    tmp_path: Path, inner: MockLLMClient
) -> None:
    client = CachedLLMClient(inner, tmp_path)
    prompts = [f"p{i % 10}" for i in range(200)]
    for prompt in set(prompts):
        client.generate(prompt, n=1, temperature=0.0)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda prompt: client.generate(prompt, n=1, temperature=0.0), prompts))

    assert (client.hits, client.misses) == (200, 10)
