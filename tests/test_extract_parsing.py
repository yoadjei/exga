"""prompt rendering and answer parsing (spec 7.3, 0A.4 golden tests).

after an intended prompt change, regenerate the golden prompts and review the diff:
    uv run python tests/test_extract_parsing.py
"""

import math
from pathlib import Path

import pytest

from exga.errors import ConfigError
from exga.extract import (
    AnswerError,
    answer_schema,
    build_prompt,
    build_repair_prompt,
    load_prompts,
    merge_chunks,
    paper_text,
    read_answer,
    value_logprob,
)
from exga.schemas import Chunk, FieldSpec, RawResponse, SampleAnswer, TokenLogprob

GOLDEN = Path(__file__).parent / "golden"
PROMPTS = load_prompts("extract_v1")
SAMPLE_SIZE = FieldSpec(
    name="sample_size",
    description="total number of participants randomised",
    group="numeric",
    unit="participants",
)
DESIGN = FieldSpec(
    name="study_design",
    description="design of the study",
    group="categorical",
    allowed_values=("rct", "cohort", "case_control"),
    synonyms={"rct": ("randomised controlled trial",)},
)
COUNTRY = FieldSpec(name="country", description="country of recruitment", group="short_text")
PART = Chunk(
    index=0,
    text="\n\n".join(
        [
            "Abstract",
            "A total of 120 participants were randomised.",
            "2. Methods",
            "We recruited in Ghana.",
        ]
    ),
    paragraph_pages=(1, 1, 2, 2),
    sections=("abstract", "methods"),
)
GOLDEN_CASES = {
    "extract_v1_numeric.txt": SAMPLE_SIZE,
    "extract_v1_categorical.txt": DESIGN,
    "extract_v1_short_text.txt": COUNTRY,
}


def reply(text: str, logprobs: list[tuple[str, float]] | None = None) -> RawResponse:
    tokens = (
        None if logprobs is None else tuple(TokenLogprob(token=t, logprob=p) for t, p in logprobs)
    )
    return RawResponse(text=text, token_logprobs=tokens, input_tokens=0, output_tokens=0)


@pytest.mark.parametrize(("name", "spec"), GOLDEN_CASES.items())
def test_rendered_prompts_match_the_golden_files(name: str, spec: FieldSpec) -> None:
    expected = (GOLDEN / name).read_text(encoding="utf-8")

    assert build_prompt(PROMPTS, spec, PART) == expected


def test_paper_text_marks_where_each_page_starts() -> None:
    assert paper_text(PART).split("\n\n") == [
        "[page 1]",
        "Abstract",
        "A total of 120 participants were randomised.",
        "[page 2]",
        "2. Methods",
        "We recruited in Ghana.",
    ]


def test_the_repair_prompt_keeps_the_request_and_names_the_problem() -> None:
    repair = build_repair_prompt(
        PROMPTS, "ORIGINAL", "not json", "the reply contains no JSON object"
    )

    assert repair.startswith("ORIGINAL\n")
    assert "could not be used: the reply contains no JSON object" in repair
    assert "\nnot json\n" in repair


def test_a_missing_prompt_version_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "v9").mkdir()
    (tmp_path / "v9" / "main.txt").write_text("$paper_text", encoding="utf-8")

    with pytest.raises(ConfigError, match="lacks: numeric_unit, repair, numeric"):
        load_prompts("v9", root=tmp_path)


def test_the_schema_requires_every_key_and_lists_categorical_options() -> None:
    schema = answer_schema(DESIGN)

    assert schema["required"] == ["value", "evidence", "page"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["value"]["enum"] == ["rct", "cohort", "case_control", None]  # type: ignore[index]
    assert "enum" not in answer_schema(COUNTRY)["properties"]["value"]  # type: ignore[index]


@pytest.mark.parametrize(
    ("text", "spec", "expected"),
    [
        (
            '{"value": "120", "evidence": "A total of 120 participants", "page": 1}',
            SAMPLE_SIZE,
            SampleAnswer(value="120", evidence="A total of 120 participants", page_hint=1),
        ),
        (
            '{"value": 120, "evidence": null, "page": null}',
            SAMPLE_SIZE,
            SampleAnswer(value="120", evidence=None),
        ),
        (
            '{"value": 54.2, "evidence": "54.2 years"}',
            SAMPLE_SIZE,
            SampleAnswer(value="54.2", evidence="54.2 years"),
        ),
        (
            '{"value": 120.0, "evidence": null, "page": 2}',
            SAMPLE_SIZE,
            SampleAnswer(value="120", evidence=None, page_hint=2),
        ),
        (
            '{"value": null, "evidence": null, "page": null}',
            SAMPLE_SIZE,
            SampleAnswer(value=None, evidence=None),
        ),
        (
            '{"value": "  ", "evidence": "", "page": 0}',
            COUNTRY,
            SampleAnswer(value=None, evidence=None),
        ),
        (
            '```json\n{"value": "Ghana", "evidence": "in Ghana", "page": "2"}\n```',
            COUNTRY,
            SampleAnswer(value="Ghana", evidence="in Ghana", page_hint=2),
        ),
        (
            'Here is the answer: {"value": "Ghana", "evidence": null, "page": true}',
            COUNTRY,
            SampleAnswer(value="Ghana", evidence=None),
        ),
        (
            '{"value": "Randomised Controlled Trial", "evidence": null, "page": null}',
            DESIGN,
            SampleAnswer(value="rct", evidence=None),
        ),
        (
            '{"value": "Cohort", "evidence": null, "page": -3, "extra": 1}',
            DESIGN,
            SampleAnswer(value="cohort", evidence=None),
        ),
    ],
)
def test_replies_parse_to_fixed_answers(text: str, spec: FieldSpec, expected: SampleAnswer) -> None:
    assert read_answer(reply(text), spec) == expected


@pytest.mark.parametrize(
    ("text", "spec", "problem"),
    [
        ("I could not find it.", COUNTRY, "contains no JSON object"),
        ('{"value": "Ghana", "evidence": }', COUNTRY, "not valid JSON"),
        ('["Ghana"]', COUNTRY, "contains no JSON object"),
        ('{"evidence": "in Ghana"}', COUNTRY, 'no "value" key'),
        ('{"value": true}', COUNTRY, "string, a number or null"),
        ('{"value": ["a", "b"]}', COUNTRY, "string, a number or null"),
        ('{"value": "Ghana", "evidence": 3}', COUNTRY, '"evidence" must be a string'),
        ('{"value": "cross-sectional"}', DESIGN, 'one of "rct", "cohort", "case_control"'),
        ('{"value": "not reported"}', SAMPLE_SIZE, "must be a number"),
    ],
)
def test_unusable_replies_say_what_is_wrong(text: str, spec: FieldSpec, problem: str) -> None:
    with pytest.raises(AnswerError, match=problem):
        read_answer(reply(text), spec)


def test_the_logprob_covers_only_the_value_tokens() -> None:
    tokens = [
        ('{"', -0.1),
        ("value", -0.1),
        ('":"', -0.1),
        ("12", -1.0),
        ("0", -3.0),
        ('","', -0.1),
        ("evidence", -0.1),
        ('":null}', -0.1),
    ]
    text = "".join(token for token, _ in tokens)

    assert value_logprob(reply(text, tokens)) == pytest.approx(-2.0)


def test_a_null_value_is_scored_on_the_null_token() -> None:
    tokens = [('{"value": ', -0.2), ("null", -0.5), (', "evidence": null}', -0.2)]
    text = "".join(token for token, _ in tokens)

    assert value_logprob(reply(text, tokens)) == pytest.approx(-0.5)


def test_parsed_answers_carry_the_value_logprob() -> None:
    tokens = [('{"value": "', 0.0), ("Ghana", math.log(0.5)), ('"}', 0.0)]

    answer = read_answer(reply("".join(t for t, _ in tokens), tokens), COUNTRY)

    assert answer.mean_logprob == pytest.approx(math.log(0.5))


@pytest.mark.parametrize(
    ("text", "tokens"),
    [
        ('{"value": "a"}', None),
        ('{"value": "a"}', [("{", -0.1), ('"value": "b"}', -0.1)]),
        ('{"answer": "a"}', [('{"answer": "a"}', -0.1)]),
        ('{"value": "a', [('{"value": "a', -0.1)]),
    ],
)
def test_logprob_is_missing_when_it_cannot_be_attributed(
    text: str, tokens: list[tuple[str, float]] | None
) -> None:
    assert value_logprob(reply(text, tokens)) is None


def answer(value: str | None, evidence: str | None = None) -> SampleAnswer:
    return SampleAnswer(value=value, evidence=evidence)


FIRST = Chunk(index=0, text="Background only.", paragraph_pages=(1,), sections=())
SECOND = Chunk(
    index=1, text="A total of 120 participants were randomised.", paragraph_pages=(2,), sections=()
)


def test_a_single_chunk_is_returned_unchanged() -> None:
    answers = [answer("90", "made up"), None, answer(None)]

    assert merge_chunks([answers], [FIRST], 0.9) == answers


def test_each_slot_prefers_an_answer_supported_by_its_chunk() -> None:
    unsupported = answer("90", "ninety participants")
    supported = answer("120", "120 participants were randomised")

    [merged] = merge_chunks([[unsupported], [supported]], [FIRST, SECOND], 0.9)

    assert merged == supported


def test_without_support_the_first_answer_with_a_value_wins() -> None:
    [merged] = merge_chunks(
        [[answer(None)], [answer("90", "not in the text")]], [FIRST, SECOND], 0.9
    )

    assert merged == answer("90", "not in the text")


def test_a_slot_is_not_reported_only_when_no_chunk_has_a_value() -> None:
    [merged] = merge_chunks([[None], [answer(None)]], [FIRST, SECOND], 0.9)

    assert merged == answer(None)


def test_a_slot_that_failed_in_every_chunk_stays_failed() -> None:
    assert merge_chunks([[None], [None]], [FIRST, SECOND], 0.9) == [None]


if __name__ == "__main__":
    for file_name, field in GOLDEN_CASES.items():
        (GOLDEN / file_name).write_text(
            build_prompt(PROMPTS, field, PART), encoding="utf-8", newline="\n"
        )
