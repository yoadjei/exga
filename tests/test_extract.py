import json

import pytest

from exga.document import text_document
from exga.errors import BudgetExceededError, LLMResponseError
from exga.extract import answer_schema, extract_all, extract_item, load_prompts
from exga.llm.mock import MockCall, MockLLMClient
from exga.schemas import FieldSpec, RawResponse, SampleAnswer
from exga.settings import ExtractionSettings, Settings

PROMPTS = load_prompts("extract_v1")
SETTINGS = Settings(extraction=ExtractionSettings(samples=3, seed=11))
SAMPLE_SIZE = FieldSpec(
    name="sample_size", description="total number of participants randomised", group="numeric"
)
COUNTRY = FieldSpec(name="country", description="country of recruitment", group="short_text")
PAPER = text_document("A total of 120 participants were randomised in Ghana.", "paper.md")
GOOD = json.dumps({"value": "120", "evidence": "A total of 120 participants", "page": 1})


def is_repair(call: MockCall) -> bool:
    return "could not be used" in call.prompt


def test_one_greedy_and_k_sampled_answers_are_requested() -> None:
    client = MockLLMClient(lambda _call, _index: GOOD)

    item = extract_item(PAPER, SAMPLE_SIZE, client, PROMPTS, SETTINGS)

    greedy_call, sampled_call = client.calls
    assert (greedy_call.n, greedy_call.temperature) == (1, 0.0)
    assert (sampled_call.n, sampled_call.temperature) == (3, 0.7)
    assert greedy_call.json_schema == answer_schema(SAMPLE_SIZE)
    assert greedy_call.seed == sampled_call.seed == 11
    assert item.greedy == SampleAnswer(
        value="120", evidence="A total of 120 participants", page_hint=1
    )
    assert len(item.samples) == 3
    assert (item.failed_samples, item.error) == (0, None)
    assert (item.paper_id, item.field) == (PAPER.paper_id, "sample_size")
    assert (item.model_id, item.prompt_version) == ("mock", "extract_v1")


def test_an_unusable_sample_is_repaired_once() -> None:
    def reply(call: MockCall, index: int) -> str:
        if is_repair(call):
            return GOOD
        return "about 120 people" if call.temperature > 0 and index == 1 else GOOD

    client = MockLLMClient(reply)

    item = extract_item(PAPER, SAMPLE_SIZE, client, PROMPTS, SETTINGS)

    [repair] = [call for call in client.calls if is_repair(call)]
    assert (repair.n, repair.temperature) == (1, 0.0)
    assert repair.prompt.startswith(client.calls[0].prompt)
    assert "about 120 people" in repair.prompt
    assert (len(item.samples), item.failed_samples) == (3, 0)


def test_a_sample_that_fails_its_repair_counts_as_failed() -> None:
    def reply(call: MockCall, index: int) -> str:
        first_sample = call.temperature > 0 and index == 0
        return "no idea" if first_sample or is_repair(call) else GOOD

    client = MockLLMClient(reply)

    item = extract_item(PAPER, SAMPLE_SIZE, client, PROMPTS, SETTINGS)

    assert (len(item.samples), item.failed_samples) == (2, 1)
    assert item.greedy is not None


def test_a_greedy_answer_that_fails_its_repair_leaves_no_candidate() -> None:
    client = MockLLMClient(lambda call, _index: "no idea" if call.temperature == 0 else GOOD)

    item = extract_item(PAPER, SAMPLE_SIZE, client, PROMPTS, SETTINGS)

    assert item.greedy is None
    assert len(item.samples) == 3


class RefusingClient:
    model_id = "refusing"

    def __init__(self, error: Exception) -> None:
        self.error = error

    def generate(self, *_args: object, **_kwargs: object) -> list[RawResponse]:
        raise self.error


def test_a_refused_request_gives_an_item_without_answers() -> None:
    client = RefusingClient(LLMResponseError("HTTP 400: context length exceeded"))

    item = extract_item(PAPER, SAMPLE_SIZE, client, PROMPTS, SETTINGS)

    assert (item.greedy, item.samples, item.failed_samples) == (None, (), 3)
    assert item.error == "HTTP 400: context length exceeded"


def test_a_spent_budget_stops_the_run() -> None:
    client = RefusingClient(BudgetExceededError("spent"))

    with pytest.raises(BudgetExceededError):
        extract_item(PAPER, SAMPLE_SIZE, client, PROMPTS, SETTINGS)


def long_paper() -> str:
    filler = " ".join(["Background sentence about depression care."] * 120)
    finding = "A total of 120 participants were randomised."
    return "\n\n".join(["Abstract", filler, "Results", finding, filler])


def test_long_papers_are_split_and_the_supported_answer_wins() -> None:
    def reply(call: MockCall, _index: int) -> str:
        if "120 participants were randomised" in call.prompt:
            return json.dumps({"value": "120", "evidence": "120 participants were randomised"})
        return json.dumps({"value": "90", "evidence": "ninety were screened"})

    client = MockLLMClient(reply)
    settings = Settings(extraction=ExtractionSettings(samples=2, max_chunk_tokens=1_000))

    item = extract_item(
        text_document(long_paper(), "long.md"), SAMPLE_SIZE, client, PROMPTS, settings
    )

    assert len(client.calls) > 2
    assert item.greedy is not None
    assert item.greedy.value == "120"
    assert [sample.value for sample in item.samples] == ["120", "120"]


def test_extract_all_returns_items_in_paper_then_field_order() -> None:
    other = text_document("Sixty participants were randomised in Kenya.", "other.md")
    client = MockLLMClient(lambda _call, _index: GOOD)

    items = extract_all([PAPER, other], [SAMPLE_SIZE, COUNTRY], client, PROMPTS, SETTINGS)

    assert [(item.paper_id, item.field) for item in items] == [
        (PAPER.paper_id, "sample_size"),
        (PAPER.paper_id, "country"),
        (other.paper_id, "sample_size"),
        (other.paper_id, "country"),
    ]
